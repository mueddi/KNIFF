"""Admin-Seite «Rueckmeldungen»: /api/admin/feedback – Zaehler, Wochen, Gruppen."""
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models import Feedback

from .test_library import make_admin, register_pw


def _admin(client):
    h = register_pw(client, "chef@test.ch")
    make_admin("chef@test.ch")
    return h


def _rueckdatieren(feedback_id: int, tage: int) -> None:
    with SessionLocal() as db:
        fb = db.get(Feedback, feedback_id)
        fb.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=tage)
        db.commit()


def test_nur_admin(client):
    mia = register_pw(client, "mia@test.ch")
    assert client.get("/api/admin/feedback", headers=mia).status_code == 403
    assert client.get("/api/admin/feedback").status_code == 401


def test_leere_uebersicht_hat_die_volle_form(client):
    d = client.get("/api/admin/feedback", headers=_admin(client)).json()
    assert d["zeitraum_tage"] == 90 and d["gesamt"] == 0 and d["offen"] == 0
    assert d["gekappt"] is False
    assert d["nach_art"] == {"feedback": 0, "problem": 0}
    assert [k["id"] for k in d["nach_kategorie"]] == ["feedback", "erkennung", "antwort", "verraten", "technik", "anderes"]
    assert all(k["anzahl"] == 0 and k["offen"] == 0 and k["label"] for k in d["nach_kategorie"])
    assert 13 <= len(d["wochen"]) <= 14          # 90 Tage = 13 Wochen, plus die angebrochene
    assert all(w["gesamt"] == 0 for w in d["wochen"])
    assert d["gruppen"] == []


def test_zaehlt_nach_art_und_kategorie(client):
    admin = _admin(client)
    mia = register_pw(client, "mia@test.ch")
    client.post("/api/feedback", headers=mia, json={"text": "Bitte mehr Geometrie-Aufgaben."})
    client.post("/api/feedback", headers=mia, json={"text": "Der Stift funktioniert super."})
    client.post("/api/feedback", headers=mia, json={"kind": "problem", "category": "technik", "text": "Seite hängt"})

    d = client.get("/api/admin/feedback", headers=admin).json()
    assert d["gesamt"] == 3 and d["offen"] == 3
    assert d["nach_art"] == {"feedback": 2, "problem": 1}
    kat = {k["id"]: k for k in d["nach_kategorie"]}
    assert kat["feedback"]["anzahl"] == 2 and kat["technik"]["anzahl"] == 1
    assert kat["technik"]["label"] == "Technisches Problem"
    assert d["wochen"][-1]["gesamt"] == 3 and d["wochen"][-1]["problem"] == 1
    # Einzeleintraege tragen Absender und Zeitzone
    e = d["gruppen"][0]["eintraege"][0]
    assert e["display_name"] == "mia" and e["role"] == "student"
    assert e["created_at"].endswith("+00:00")


def test_wochen_eimer_und_zeitfenster(client):
    admin = _admin(client)
    mia = register_pw(client, "mia@test.ch")
    alt = client.post("/api/feedback", headers=mia, json={"text": "Alte Rückmeldung von früher."}).json()["id"]
    client.post("/api/feedback", headers=mia, json={"text": "Frische Rückmeldung von heute."})
    _rueckdatieren(alt, 14)

    d = client.get("/api/admin/feedback?tage=90", headers=admin).json()
    assert d["gesamt"] == 2
    assert d["wochen"][-1]["gesamt"] == 1
    # zwei Wochen zurueck: je nach Wochentag Eimer -2 oder -3, aber nicht der letzte
    aeltere = [w["gesamt"] for w in d["wochen"][:-1]]
    assert sum(aeltere) == 1 and sum(aeltere[-3:]) == 1

    d7 = client.get("/api/admin/feedback?tage=7", headers=admin).json()
    assert d7["gesamt"] == 1 and d7["zeitraum_tage"] == 7
    assert client.get("/api/admin/feedback?tage=0", headers=admin).status_code == 422


def test_gruppen_und_offen_zaehler(client):
    admin = _admin(client)
    mia = register_pw(client, "mia@test.ch")
    leo = register_pw(client, "leo@test.ch")
    client.post("/api/feedback", headers=mia, json={"text": "Bitte mehr Geometrie-Aufgaben."})
    zweite = client.post("/api/feedback", headers=leo, json={"text": "Mehr Geometrie Aufgaben bitte!"}).json()["id"]
    client.post("/api/feedback", headers=leo, json={"text": "Der Stift funktioniert super."})

    d = client.get("/api/admin/feedback", headers=admin).json()
    assert [g["anzahl"] for g in d["gruppen"]] == [2, 1]
    g = d["gruppen"][0]
    assert g["text"] == "Mehr Geometrie Aufgaben bitte!"      # neuester Text ist der Repraesentant
    assert g["offen"] == 2 and g["label"] == "Freies Feedback" and g["kind"] == "feedback"
    assert g["erster"] <= g["letzter"]
    assert {e["display_name"] for e in g["eintraege"]} == {"mia", "leo"}

    assert client.patch(f"/api/feedback/{zweite}/erledigt", headers=admin).status_code == 200
    d = client.get("/api/admin/feedback", headers=admin).json()
    assert d["offen"] == 2 and d["gruppen"][0]["offen"] == 1
    erledigt = next(e for e in d["gruppen"][0]["eintraege"] if e["id"] == zweite)
    assert erledigt["resolved_at"] and erledigt["resolved_at"].endswith("+00:00")


def test_kappung_wird_gemeldet(client, monkeypatch):
    from app.services import feedback_gruppen

    monkeypatch.setattr(feedback_gruppen, "MAX_ZEILEN", 2)
    admin = _admin(client)
    mia = register_pw(client, "mia@test.ch")
    for text in ("Eins zwei drei", "Vier fünf sechs", "Sieben acht neun"):
        client.post("/api/feedback", headers=mia, json={"text": text})
    d = client.get("/api/admin/feedback", headers=admin).json()
    assert d["gekappt"] is True and d["gesamt"] == 2
