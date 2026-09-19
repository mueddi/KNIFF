"""Admin-Kostenauswertung: Preisberechnung, Zugriffsschutz, Aggregate."""
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models import ApiUsage, Exercise, User
from app.services.usage import cost_usd, record

from .test_library import make_admin, register_pw


# ---- Preisberechnung ----

def test_cost_usd_haiku():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    assert cost_usd("claude-haiku-4-5", usage) == 6.00  # 1 + 5 USD


def test_cost_usd_sonnet_mit_cache():
    usage = {
        "input_tokens": 1_000_000,
        "output_tokens": 0,
        "cache_read_input_tokens": 1_000_000,   # 0.1x Input-Preis
        "cache_creation_input_tokens": 1_000_000,  # 1.25x Input-Preis
    }
    # 3 + 0.3 + 3.75 = 7.05 USD
    assert abs(cost_usd("claude-sonnet-4-6", usage) - 7.05) < 1e-9


def test_cache_schreiben_mit_stundenfrist_kostet_das_doppelte():
    """Gemessen in der Vorschau (7.9.): der erste Turn einer Aufgabe schreibt
    ~6700 Token in den 1-Stunden-Cache. Die alte Formel rechnete dafuer 1.25x
    und verbuchte 0.0088 USD – tatsaechlich sind es 2x, also 0.0138 USD. Die
    Auswertung lag damit bei jedem Aufgabenstart um ein Drittel zu tief."""
    from app.services.usage import cache_write_split

    # Aufteilung wie sie die API liefert (als dict oder als Objekt mit Attributen)
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
             "cache_creation_input_tokens": 1_000_000,
             "cache_creation": {"ephemeral_5m_input_tokens": 250_000,
                                "ephemeral_1h_input_tokens": 750_000}}
    assert cache_write_split(usage) == (250_000, 750_000)
    # Haiku: 0.25 * 1.25 + 0.75 * 2.0 = 1.8125 USD
    assert abs(cost_usd("claude-haiku-4-5", usage) - 1.8125) < 1e-9

    # Ohne Aufteilung (aeltere Antworten): alles gilt als 5-Minuten-Schreiben
    ohne = {"cache_creation_input_tokens": 1_000_000}
    assert cache_write_split(ohne) == (1_000_000, 0)
    assert abs(cost_usd("claude-haiku-4-5", ohne) - 1.25) < 1e-9

    # Aufteilung darf den Gesamtwert nie uebersteigen
    kaputt = {"cache_creation_input_tokens": 100,
              "cache_creation": {"ephemeral_1h_input_tokens": 500}}
    assert cache_write_split(kaputt) == (0, 100)


def test_record_haelt_stundenfrist_fest(client):
    usage = {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 300,
             "cache_creation": {"ephemeral_1h_input_tokens": 200, "ephemeral_5m_input_tokens": 100}}
    with SessionLocal() as db:
        record(db, "chat", "claude-haiku-4-5", usage)
        db.commit()
        zeile = db.query(ApiUsage).one()
        assert zeile.cache_write_tokens == 300
        assert zeile.cache_write_1h_tokens == 200


def test_cost_usd_unbekanntes_modell_faellt_auf_sonnet_preis():
    usage = {"input_tokens": 1_000_000, "output_tokens": 0}
    assert cost_usd("irgendwas-neues", usage) == 3.00


def test_record_vertraegt_kaputte_eingaben(client):
    # darf nie werfen – auch mit None-Usage oder leerem Modell
    with SessionLocal() as db:
        record(db, "chat", "", None)
        record(db, "chat", "claude-haiku-4-5", None)
        db.commit()
        assert db.query(ApiUsage).count() == 0


# ---- Endpoint ----

def _insert_usage(exercise_id, cost, kind="chat", model="claude-haiku-4-5", days_ago=0):
    with SessionLocal() as db:
        # Fremdschluessel werden auch in SQLite geprueft: die Aufgabe muss es geben.
        if exercise_id is not None and db.get(Exercise, exercise_id) is None:
            owner = db.query(User).first()
            db.add(Exercise(id=exercise_id, user_id=owner.id, text=f"Aufgabe {exercise_id}"))
            db.flush()
        db.add(ApiUsage(
            kind=kind, model=model, exercise_id=exercise_id,
            input_tokens=100, output_tokens=50,
            cost_usd=cost,
            created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        ))
        db.commit()


def test_foto_erkennung_wird_der_aufgabe_zugeordnet(client):
    """In der Produktion hatte KEINE der 116 Erkennungs-Zeilen eine Aufgabe:
    das Foto wird erkannt, bevor die Aufgabe existiert. Beim Anlegen der
    Aufgabe mit Bild wird die juengste offene Erkennung nachtraeglich
    zugeordnet – nur die eigene, nur die juengste, nur aus den letzten
    30 Minuten."""
    from app.models import User

    headers = register_pw(client, "mia@test.ch")
    fremd = register_pw(client, "leo@test.ch")
    with SessionLocal() as db:
        mia = db.query(User).filter(User.email == "mia@test.ch").one().id
        leo = db.query(User).filter(User.email == "leo@test.ch").one().id
        jetzt = datetime.now(timezone.utc)
        db.add(ApiUsage(user_id=mia, kind="ocr", model="claude-sonnet-5", cost_usd=0.004,
                        created_at=jetzt - timedelta(hours=2)))         # zu alt
        db.add(ApiUsage(user_id=mia, kind="ocr", model="claude-sonnet-5", cost_usd=0.004,
                        created_at=jetzt - timedelta(minutes=3)))       # aelter
        db.add(ApiUsage(user_id=mia, kind="ocr", model="claude-sonnet-5", cost_usd=0.004,
                        created_at=jetzt - timedelta(seconds=10)))      # die juengste
        db.add(ApiUsage(user_id=leo, kind="ocr", model="claude-sonnet-5", cost_usd=0.004,
                        created_at=jetzt))                              # fremdes Konto
        db.commit()

    ex = client.post("/api/exercises", headers=headers,
                     json={"text": "3x + 5 = 20", "image_path": "/api/exercises/images/abc"}).json()
    # Eine Aufgabe OHNE Bild ordnet nichts zu
    client.post("/api/exercises", headers=headers, json={"text": "2x = 10"})
    client.post("/api/exercises", headers=fremd, json={"text": "x = 1"})

    with SessionLocal() as db:
        zeilen = db.query(ApiUsage).order_by(ApiUsage.created_at).all()
        assert [z.exercise_id for z in zeilen] == [None, None, ex["id"], None]


def test_kosten_nur_fuer_admin(client):
    headers = register_pw(client, "mia@test.ch")
    assert client.get("/api/admin/kosten", headers=headers).status_code == 403
    assert client.get("/api/admin/kosten").status_code == 401


def test_kosten_aggregate_stimmen(client):
    admin = register_pw(client, "chef@test.ch")
    make_admin("chef@test.ch")

    # Aufgabe 1: zwei Chat-Aufrufe à 0.01 USD -> 0.02 USD; Aufgabe 2: 0.06 USD
    _insert_usage(1, 0.01)
    _insert_usage(1, 0.01)
    _insert_usage(2, 0.06, model="claude-sonnet-4-6")
    # OCR ohne exercise_id zaehlt NICHT in pro_aufgabe, aber ins Gesamt
    _insert_usage(None, 0.005, kind="ocr", model="claude-sonnet-4-6")
    # Alte Zeile ausserhalb des 30-Tage-Fensters bleibt draussen
    _insert_usage(3, 9.99, days_ago=40)

    r = client.get("/api/admin/kosten?tage=30", headers=admin)
    assert r.status_code == 200, r.text
    data = r.json()

    pa = data["pro_aufgabe"]
    assert pa["anzahl_aufgaben"] == 2
    # Kurs 0.90: 0.02 USD = 1.8 Rp., 0.06 USD = 5.4 Rp., Ø = 3.6 Rp.
    assert abs(pa["min_rappen"] - 1.8) < 0.01
    assert abs(pa["max_rappen"] - 5.4) < 0.01
    assert abs(pa["durchschnitt_rappen"] - 3.6) < 0.01

    assert data["gesamt"]["aufrufe"] == 4
    assert abs(data["gesamt"]["kosten_usd"] - 0.085) < 1e-6

    typen = {row["typ"]: row for row in data["nach_typ"]}
    assert typen["chat"]["aufrufe"] == 3
    assert typen["ocr"]["aufrufe"] == 1
    modelle = {row["modell"]: row for row in data["nach_modell"]}
    assert modelle["claude-haiku-4-5"]["aufrufe"] == 2
    assert modelle["claude-sonnet-4-6"]["aufrufe"] == 2


def _insert_tokens(exercise_id, *, kind="chat", model="claude-haiku-4-5", user_id=None,
                   input_tokens=0, output_tokens=0, cache_read=0, cache_write=0, cache_write_1h=0,
                   charged=0):
    from app.services.usage import cost_usd
    usage = {"input_tokens": input_tokens, "output_tokens": output_tokens,
             "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_write,
             "cache_creation": {"ephemeral_1h_input_tokens": cache_write_1h}}
    with SessionLocal() as db:
        db.add(ApiUsage(kind=kind, model=model, exercise_id=exercise_id, user_id=user_id,
                        input_tokens=input_tokens, output_tokens=output_tokens,
                        cache_read_tokens=cache_read, cache_write_tokens=cache_write,
                        cache_write_1h_tokens=cache_write_1h,
                        cost_usd=cost_usd(model, usage), charged_tokens=charged,
                        created_at=datetime.now(timezone.utc)))
        db.commit()


def test_auswertung_erklaert_woher_die_kosten_kommen(client):
    """Die Auswertung soll nicht nur sagen, WIE VIEL es kostet, sondern
    WOHER: Bestandteile, Foto-Anteil pro Aufgabe, Cache netto, Marge nur auf
    verrechnete Aufrufe – und Klartext-Hinweise dazu."""
    from app.models import User

    admin = register_pw(client, "chef@test.ch")
    make_admin("chef@test.ch")
    schueler = register_pw(client, "mia@test.ch")
    with SessionLocal() as db:
        chef = db.query(User).filter(User.email == "chef@test.ch").one().id
        mia = db.query(User).filter(User.email == "mia@test.ch").one().id
    ex = client.post("/api/exercises", headers=schueler, json={"text": "3x + 5 = 20"}).json()

    # Aufgabe: ein Foto (Sonnet) + zwei Chat-Runden (Haiku), die zweite aus dem Cache
    _insert_tokens(ex["id"], kind="ocr", model="claude-sonnet-5", user_id=mia,
                   input_tokens=2000, output_tokens=20, charged=2)
    _insert_tokens(ex["id"], user_id=mia, input_tokens=300, output_tokens=100,
                   cache_write=7000, cache_write_1h=7000, charged=3)
    _insert_tokens(ex["id"], user_id=mia, input_tokens=300, output_tokens=100,
                   cache_read=7000, cache_write=100, charged=1)
    # Sechs Fotos, aus denen nie eine Aufgabe wurde (Betreiber-Konto, gratis)
    for _ in range(6):
        _insert_tokens(None, kind="ocr", model="claude-sonnet-5", user_id=chef,
                       input_tokens=1300, output_tokens=10)

    data = client.get("/api/admin/kosten?tage=7", headers=admin).json()

    # Bestandteile summieren sich zu den Gesamtkosten
    a = data["anteile"]
    summe = a["eingabe_chf"] + a["cache_lesen_chf"] + a["cache_schreiben_chf"] + a["ausgabe_chf"]
    assert abs(summe - data["gesamt"]["kosten_chf"]) < 0.001
    for row in data["nach_typ"] + data["nach_modell"]:
        teile = row["eingabe_chf"] + row["cache_lesen_chf"] + row["cache_schreiben_chf"] + row["ausgabe_chf"]
        assert abs(teile - row["kosten_chf"]) < 0.001, row

    # Pro Aufgabe zaehlt das Foto mit
    pa = data["pro_aufgabe"]
    assert pa["anzahl_aufgaben"] == 1
    assert pa["fotos_pro_aufgabe"] == 1.0 and pa["chats_pro_aufgabe"] == 2.0
    typen = {r["typ"]: r for r in data["nach_typ"]}
    assert abs(pa["durchschnitt_rappen"] - (typen["chat"]["kosten_chf"] * 100 + 2000 * 3 / 1e6 * 0.9 * 100 + 20 * 15 / 1e6 * 0.9 * 100)) < 0.05

    # Cache: 7000 gelesen (spart 0.9x), 7000 mit Stundenfrist geschrieben (kostet +1.0x)
    # -> netto praktisch null, brutto und Mehrkosten getrennt sichtbar
    c = data["cache"]
    assert c["schreiben_1h_tokens"] == 7000 and c["lesen_tokens"] == 7000
    assert c["brutto_chf"] > 0 and c["mehrkosten_chf"] > c["brutto_chf"]
    assert c["netto_chf"] < 0
    haiku = next(r for r in data["nach_modell"] if r["modell"] == "claude-haiku-4-5")
    assert haiku["cache_netto_chf"] < 0

    # Marge nur auf die verrechneten Aufrufe (die sechs Gratis-Fotos verzerren sie nicht)
    g = data["gesamt"]
    assert g["verrechnete_aufrufe"] == 3 and g["verrechnet_tokens"] == 6
    assert g["kosten_gratis_chf"] > 0
    assert abs(g["kosten_verrechnet_chf"] + g["kosten_gratis_chf"] - g["kosten_chf"]) < 0.001
    assert abs(g["marge_ist"] - 6 / (g["kosten_verrechnet_chf"] * 100)) < 0.01

    # Fotos ohne Aufgabe als eigener Posten
    assert data["fotos_ohne_aufgabe"]["aufrufe"] == 6
    teuerste = data["teuerste_aufgaben"]
    assert teuerste[0]["exercise_id"] == ex["id"] and teuerste[0]["fotos"] == 1 and teuerste[0]["chats"] == 2
    assert teuerste[0]["text"].startswith("3x + 5")

    # Klartext-Hinweise: Fotos ohne Aufgabe, Gratis-Anteil, Cache-Netto negativ
    texte = " ".join(h["text"] for h in data["hinweise"])
    assert "6 Foto-Erkennungen" in texte
    assert "niemandem verrechnet" in texte
    assert "kostet der Cache mehr" in texte


def test_kosten_leer_ohne_daten(client):
    admin = register_pw(client, "chef@test.ch")
    make_admin("chef@test.ch")
    r = client.get("/api/admin/kosten", headers=admin)
    assert r.status_code == 200
    data = r.json()
    assert data["pro_aufgabe"]["anzahl_aufgaben"] == 0
    assert data["gesamt"]["kosten_chf"] == 0
    assert data["nach_typ"] == []


def test_admin_hat_unbegrenzte_aufgaben(client):
    """Betreiber-Konto: kein Gratis-Limit, keine Token-Abbuchung."""
    admin = register_pw(client, "chef@test.ch")
    make_admin("chef@test.ch")

    # viele Aufgaben anlegen – alle gehen durch, nichts wird abgebucht
    for i in range(8):
        r = client.post("/api/exercises", headers=admin, json={"text": f"{i}x + 1 = {i + 2}"})
        assert r.status_code == 201, r.text

    q = client.get("/api/quota", headers=admin).json()
    assert q["unlimited"] is True
    assert q["token_balance"] == 0  # nichts abgebucht, nichts noetig
    assert q["percent_used"] == 0

    # Schueler mit leerem Guthaben laufen ins 402
    student = register_pw(client, "mia@test.ch")
    from app.services.quota import current_month
    with SessionLocal() as db:
        from app.models import User
        u = db.query(User).filter(User.email == "mia@test.ch").one()
        u.free_used_tokens = 50
        u.free_month = current_month()
        u.token_balance = 0
        db.commit()
    assert client.post("/api/exercises", headers=student,
                       json={"text": "z = 1"}).status_code == 402
    assert client.get("/api/quota", headers=student).json()["unlimited"] is False


def test_mock_chat_erzeugt_keine_usage_zeile(client):
    # Ohne API-Key antwortet der Mock-Tutor – es darf KEINE Kostenzeile entstehen
    headers = register_pw(client, "mia@test.ch")
    ex = client.post("/api/exercises", headers=headers,
                     json={"text": "3x+5=20", "math_expression": "3*x+5=20"}).json()
    aid = client.post(f"/api/exercises/{ex['id']}/attempts", headers=headers).json()["attempt"]["id"]
    with client.stream("POST", f"/api/attempts/{aid}/chat", headers=headers,
                       json={"text": "x = 5"}) as r:
        assert r.status_code == 200
        "".join(r.iter_text())  # Stream konsumieren, damit das finally laeuft
    with SessionLocal() as db:
        assert db.query(ApiUsage).count() == 0
