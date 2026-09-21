"""Kniff Plus: Probe in Aufgaben, Abo mit Fair-Use, altes Guthaben bleibt."""
from datetime import datetime, timedelta

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import User
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


def test_plus_ist_unbegrenzt_bis_zur_fair_use_grenze(client, monkeypatch):
    headers = register_pw(client, "mia@test.ch")
    _user("mia@test.ch", abo_bis=datetime.utcnow() + timedelta(days=20), abo_intervall="monat", token_balance=50)
    for _ in range(5):  # weit ueber die Probe hinaus
        assert _starten(client, headers, _aufgabe(client, headers)).status_code == 201
    q = _quota(client, headers)
    assert q["stufe"] == "plus" and q["remaining"] == 10**9 and q["abo_intervall"] == "monat"
    # Plus bucht das alte Guthaben nicht an, zaehlt aber den Monat
    with SessionLocal() as db:
        charge(db, _fresh("mia@test.ch").id, 40, vom_guthaben=False)
        db.commit()
    u = _fresh("mia@test.ch")
    assert (u.token_balance, u.free_used_tokens) == (50, 40)
    # Fair-Use: ab der Grenze freundlich zu, ohne Verkaufsversuch
    naechste = _aufgabe(client, headers)
    monkeypatch.setattr(settings, "plus_monatslimit_tokens", 40)
    r = _starten(client, headers, naechste)
    assert r.status_code == 402
    assert r.headers["x-kniff-grund"] == "fairuse"
    assert "Plus" not in r.json()["detail"]
    assert _quota(client, headers)["percent_used"] == 100
    assert client.post("/api/exercises", headers=headers, json={"text": "y=2"}).status_code == 402


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
