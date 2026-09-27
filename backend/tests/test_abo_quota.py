"""Kniff Plus: Probe in Aufgaben, Abo mit Fair-Use, altes Guthaben bleibt."""
from datetime import datetime, timedelta

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import User
from app.services import quota as quota_mod
from app.services.quota import charge, current_month, quota_state, stufe

from .test_billing import _fresh, _user
from .test_library import register_pw


@pytest.fixture(autouse=True)
def abo_an(monkeypatch):
    monkeypatch.setattr(settings, "abo_enabled", True)
    monkeypatch.setattr(settings, "trial_tasks", 3)  # kurz, damit der Test schnell ist


def _aufgabe(client, headers, text="3x+5=20"):
    r = client.post("/api/exercises", headers=headers, json={"text": text, "math_expression": "3*x+5=20"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _starten(client, headers, ex_id):
    return client.post(f"/api/exercises/{ex_id}/attempts", headers=headers)


def _quota(client, headers):
    return client.get("/api/quota", headers=headers).json()


def test_probe_zaehlt_aufgaben_nicht_tokens(client):
    headers = register_pw(client, "mia@test.ch")
    assert _quota(client, headers)["stufe"] == "trial"
    ids = [_aufgabe(client, headers) for _ in range(4)]
    for ex_id in ids[:3]:
        assert _starten(client, headers, ex_id).status_code == 201
    q = _quota(client, headers)
    assert (q["trial_used"], q["trial_left"], q["remaining"]) == (3, 0, 0)
    # Die vierte Aufgabe ist nicht mehr gedeckt ...
    r = _starten(client, headers, ids[3])
    assert r.status_code == 402
    assert r.headers["x-kniff-grund"] == "trial"
    assert "Probe-Aufgaben" in r.json()["detail"]
    assert _quota(client, headers)["stufe"] == "gesperrt"
    # ... eine Probe-Aufgabe darf aber weiter bearbeitet und wiederholt werden.
    assert _starten(client, headers, ids[0]).status_code == 201
    aid = _starten(client, headers, ids[1]).json()["attempt"]["id"]
    with client.stream("POST", f"/api/attempts/{aid}/chat", headers=headers, json={"text": "x = 5"}) as r:
        assert r.status_code == 200
        "".join(r.iter_text())
    # Neue Aufgaben ueber Foto/Eingabe/Variante sind ebenfalls zu.
    assert client.post("/api/exercises", headers=headers, json={"text": "y=2"}).status_code == 402
    assert client.post(f"/api/exercises/{ids[0]}/variante", headers=headers).status_code == 402


def test_probe_bucht_kein_guthaben_ab(client):
    headers = register_pw(client, "mia@test.ch")
    _user("mia@test.ch", token_balance=100)
    ex_id = _aufgabe(client, headers)
    _starten(client, headers, ex_id)
    with SessionLocal() as db:
        u = _fresh("mia@test.ch")
        assert stufe(db, u, ex_id) == "trial"
        charge(db, u.id, 7, vom_guthaben=False)
        db.commit()
    u = _fresh("mia@test.ch")
    assert u.token_balance == 100
    assert u.free_used_tokens == 7  # Monatszaehler laeuft trotzdem mit


def test_nach_der_probe_zahlt_altes_guthaben(client):
    headers = register_pw(client, "mia@test.ch")
    for _ in range(3):
        _starten(client, headers, _aufgabe(client, headers))
    _user("mia@test.ch", token_balance=20)
    q = _quota(client, headers)
    assert q["stufe"] == "guthaben" and q["remaining"] == 20
    assert _starten(client, headers, _aufgabe(client, headers)).status_code == 201
    with SessionLocal() as db:
        charge(db, _fresh("mia@test.ch").id, 5, vom_guthaben=True)
        db.commit()
    assert _fresh("mia@test.ch").token_balance == 15


def test_plus_bucht_zuerst_abo_dann_gekauft_und_sperrt_bei_null(client):
    """Das Abo ist kein Freifahrschein: jeder Abo-Monat bringt Abo-Tokens,
    dazu kommt gekauftes Guthaben. Abgebucht wird zuerst vom Abo. Beide leer
    heisst zu – mit dem Grund plus_leer, damit die Oberflaeche den Nachkauf
    anbietet statt das Abo."""
    monat = settings.plus_tokens_monat
    headers = register_pw(client, "mia@test.ch")
    _user("mia@test.ch", abo_bis=datetime.utcnow() + timedelta(days=20), abo_intervall="monat", token_balance=50)
    for _ in range(5):  # weit ueber die Probe hinaus
        assert _starten(client, headers, _aufgabe(client, headers)).status_code == 201
    q = _quota(client, headers)
    assert q["stufe"] == "plus" and q["abo_intervall"] == "monat"
    assert (q["abo_tokens"], q["token_balance"], q["remaining"]) == (monat, 50, monat + 50)
    assert q["plus_tokens_monat"] == monat
    assert [p["key"] for p in q["pakete"]] == ["schnupper", "starter", "power"]
    naechste = _aufgabe(client, headers)  # solange noch Tokens da sind
    # Zuerst das Abo: das Gekaufte bleibt unberuehrt
    with SessionLocal() as db:
        charge(db, _fresh("mia@test.ch").id, monat - 10, vom_guthaben=True)
        db.commit()
    u = _fresh("mia@test.ch")
    assert (u.abo_tokens, u.token_balance) == (10, 50)
    # Reicht das Abo nicht, zahlt der Rest vom Gekauften
    with SessionLocal() as db:
        charge(db, u.id, 30, vom_guthaben=True)
        db.commit()
    u = _fresh("mia@test.ch")
    assert (u.abo_tokens, u.token_balance, u.free_used_tokens) == (0, 30, monat + 20)
    q = _quota(client, headers)
    assert (q["abo_tokens"], q["remaining"]) == (0, 30) and 0 < q["percent_used"] < 100
    with SessionLocal() as db:
        charge(db, u.id, 30, vom_guthaben=True)
        db.commit()
    # Beide leer: zu, mit Nachkauf-Grund, Abo bleibt die Stufe
    r = _starten(client, headers, naechste)
    assert r.status_code == 402
    assert r.headers["x-kniff-grund"] == "plus_leer"
    assert "Token-Paket" in r.json()["detail"]
    q = _quota(client, headers)
    assert q["stufe"] == "plus" and q["remaining"] == 0 and q["percent_used"] == 100
    assert client.post("/api/exercises", headers=headers, json={"text": "y=2"}).status_code == 402
    # Nachgekauft: mehr als eine Monatsmenge zaehlt als voll
    _user("mia@test.ch", token_balance=monat + 300)
    assert _quota(client, headers)["percent_used"] == 0


def _zeitreise(monkeypatch, tage):
    """«Jetzt» fuer die Kontingent-Logik um tage verschieben."""
    echt = quota_mod._utcnow_naiv
    monkeypatch.setattr(quota_mod, "_utcnow_naiv", lambda: echt() + timedelta(days=tage))


def test_abo_tokens_verfallen_gekaufte_bleiben(client, monkeypatch):
    """Was vom Abo-Monat uebrig bleibt, verfaellt: der neue Monat bringt
    wieder genau die Monatsmenge, nicht Rest + Monatsmenge. Gekauftes bleibt."""
    monat = settings.plus_tokens_monat
    headers = register_pw(client, "mia@test.ch")
    _user("mia@test.ch", abo_bis=datetime.utcnow() + timedelta(days=20), abo_intervall="monat", token_balance=40)
    with SessionLocal() as db:
        charge(db, _fresh("mia@test.ch").id, 100, vom_guthaben=True)
        db.commit()
    assert _fresh("mia@test.ch").abo_tokens == monat - 100
    # Zweite Buchung im selben Monat: kein neues Auffuellen
    with SessionLocal() as db:
        charge(db, _fresh("mia@test.ch").id, 10, vom_guthaben=True)
        db.commit()
    assert _quota(client, headers)["abo_tokens"] == monat - 110
    # Die Rechnung verlaengert das Abo um einen Monat - und «jetzt» ist dort
    alt_bis = _fresh("mia@test.ch").abo_bis
    _user("mia@test.ch", abo_bis=quota_mod._monate_zurueck(alt_bis, -1))
    _zeitreise(monkeypatch, 21)
    q = _quota(client, headers)
    assert (q["abo_tokens"], q["token_balance"], q["remaining"]) == (monat, 40, monat + 40)
    with SessionLocal() as db:
        charge(db, _fresh("mia@test.ch").id, 5, vom_guthaben=True)
        db.commit()
    u = _fresh("mia@test.ch")
    assert (u.abo_tokens, u.token_balance) == (monat - 5, 40)


def test_jahresabo_bekommt_jeden_monat_die_monatsmenge(client, monkeypatch):
    """Jahresabo: nicht zwoelf Monate auf einmal, sondern jeden Monat frisch."""
    monat = settings.plus_tokens_monat
    headers = register_pw(client, "mia@test.ch")
    _user("mia@test.ch", abo_bis=datetime.utcnow() + timedelta(days=300), abo_intervall="jahr")
    q = _quota(client, headers)
    assert (q["abo_tokens"], q["token_balance"]) == (monat, 0)
    naechster = datetime.fromisoformat(q["abo_neu"])
    assert datetime.utcnow() < naechster <= datetime.utcnow() + timedelta(days=31)
    with SessionLocal() as db:
        charge(db, _fresh("mia@test.ch").id, monat, vom_guthaben=True)
        db.commit()
    assert _quota(client, headers)["remaining"] == 0
    _zeitreise(monkeypatch, 31)
    assert _quota(client, headers)["abo_tokens"] == monat
    _zeitreise(monkeypatch, 31)  # nichts verbraucht: trotzdem nur eine Monatsmenge
    assert _quota(client, headers)["abo_tokens"] == monat


def test_abo_monat_rechnet_mit_dem_monatsende():
    assert quota_mod._monate_zurueck(datetime(2027, 3, 31, 9, 15), 1) == datetime(2027, 2, 28, 9, 15)
    assert quota_mod._monate_zurueck(datetime(2028, 3, 31), 1) == datetime(2028, 2, 29)
    assert quota_mod._monate_zurueck(datetime(2027, 1, 15), 1) == datetime(2026, 12, 15)
    assert quota_mod._monate_zurueck(datetime(2027, 1, 15), -1) == datetime(2027, 2, 15)
    assert quota_mod._monate_zurueck(datetime(2027, 1, 15), 13) == datetime(2025, 12, 15)


def test_abgelaufenes_abo_laesst_gekauftes_stehen(client):
    headers = register_pw(client, "mia@test.ch")
    _user("mia@test.ch", abo_bis=datetime.utcnow() - timedelta(hours=1), abo_tokens=300,
          abo_periode="2000-01-01T00:00", token_balance=40)
    q = _quota(client, headers)
    assert (q["abo_tokens"], q["token_balance"], q["abo_neu"]) == (0, 40, None)


def test_abgelaufenes_abo_ist_kein_plus(client):
    headers = register_pw(client, "mia@test.ch")
    _user("mia@test.ch", abo_bis=datetime.utcnow() - timedelta(minutes=1), abo_gekuendigt=True)
    q = _quota(client, headers)
    assert q["stufe"] == "trial" and q["abo_gekuendigt"] is True


def test_monatswechsel_setzt_fair_use_zaehler_zurueck(client):
    register_pw(client, "mia@test.ch")
    _user("mia@test.ch", abo_bis=datetime.utcnow() + timedelta(days=5),
          free_used_tokens=1400, free_month="2000-01")
    with SessionLocal() as db:
        u = _fresh("mia@test.ch")
        assert quota_state(db, u)["monat_verbraucht"] == 0
        charge(db, u.id, 3, vom_guthaben=False)
        db.commit()
    u = _fresh("mia@test.ch")
    assert (u.free_used_tokens, u.free_month) == (3, current_month())


def test_ohne_schalter_alles_wie_bisher(client, monkeypatch):
    monkeypatch.setattr(settings, "abo_enabled", False)
    headers = register_pw(client, "mia@test.ch")
    q = _quota(client, headers)
    assert q["stufe"] == "gratis" and q["remaining"] == settings.free_monthly_tokens
    for _ in range(5):  # keine Aufgaben-Zaehlung im Altpfad
        assert _starten(client, headers, _aufgabe(client, headers)).status_code == 201
