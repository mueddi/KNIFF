"""Konto loeschen mit laufendem Abo: erst bei Stripe beenden, dann loeschen.

Vorher loeschte die App das Konto und liess das Abo bei Stripe laufen –
die Karte wurde Monat fuer Monat weiter belastet, ohne Konto zum Kuendigen."""
from datetime import datetime, timedelta

import httpx
import pytest

from app.database import SessionLocal
from app.models import Alert, User
from app.routers import pay
from app.services import alert

from .conftest import register
from .test_abo_webhooks import _Resp
from .test_pay import enable_payments

PW = {"password": "test-passwort-123"}


@pytest.fixture
def stripe(monkeypatch):
    enable_payments(monkeypatch)
    monkeypatch.setattr(alert, "_last_sent", {})  # Alarm-Drossel je Test frisch
    calls, antwort = [], {"resp": _Resp({"id": "sub_1", "status": "canceled"})}

    def fake(method, url, **kw):
        calls.append((method, url.replace("https://api.stripe.com", "")))
        r = antwort["resp"]
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(pay.httpx, "request", fake)
    return calls, antwort


def _abo(email, **felder):
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email).one()
        u.stripe_subscription_id = "sub_1"
        u.abo_bis = datetime.utcnow() + timedelta(days=20)
        u.abo_intervall = "monat"
        for k, v in felder.items():
            setattr(u, k, v)
        db.commit()


def _gibt_es(email):
    with SessionLocal() as db:
        return db.query(User).filter(User.email == email).count() == 1


def test_laufendes_abo_wird_vor_dem_loeschen_beendet(client, stripe):
    calls, _ = stripe
    headers = register(client, "mia@test.ch")
    _abo("mia@test.ch")
    r = client.post("/api/auth/delete-account", headers=headers, json=PW)
    assert r.status_code == 204, r.text
    assert calls == [("DELETE", "/v1/subscriptions/sub_1")]
    assert not _gibt_es("mia@test.ch")


@pytest.mark.parametrize("fehler, code", [
    (_Resp({"error": {"message": "kaputt"}}, status=500), 502),
    (httpx.ConnectError("weg"), 503),
])
def test_scheitert_das_beenden_bleibt_das_konto(client, stripe, fehler, code):
    calls, antwort = stripe
    headers = register(client, "mia@test.ch")
    _abo("mia@test.ch")
    antwort["resp"] = fehler
    r = client.post("/api/auth/delete-account", headers=headers, json=PW)
    assert r.status_code == code
    assert "bleibt das Konto bestehen" in r.json()["detail"]
    assert _gibt_es("mia@test.ch")
    with SessionLocal() as db:
        assert db.query(Alert).filter(Alert.kind == "zahlung").count() == 1


def test_stripe_kennt_das_abo_nicht_mehr(client, stripe):
    _, antwort = stripe
    headers = register(client, "mia@test.ch")
    _abo("mia@test.ch")
    antwort["resp"] = _Resp({"error": {"code": "resource_missing"}}, status=404)
    assert client.post("/api/auth/delete-account", headers=headers, json=PW).status_code == 204
    assert not _gibt_es("mia@test.ch")


@pytest.mark.parametrize("felder", [
    {"abo_gekuendigt": True},                                   # verlaengert sich nicht mehr
    {"abo_bis": datetime.utcnow() - timedelta(days=1)},         # schon abgelaufen
    {"stripe_subscription_id": None, "abo_bis": None},          # nie ein Abo
])
def test_ohne_verlaengerung_kein_stripe_aufruf(client, stripe, felder):
    calls, _ = stripe
    headers = register(client, "mia@test.ch")
    _abo("mia@test.ch", **felder)
    assert client.post("/api/auth/delete-account", headers=headers, json=PW).status_code == 204
    assert calls == []
    assert not _gibt_es("mia@test.ch")


def test_falsches_passwort_fasst_das_abo_nicht_an(client, stripe):
    calls, _ = stripe
    headers = register(client, "mia@test.ch")
    _abo("mia@test.ch")
    r = client.post("/api/auth/delete-account", headers=headers, json={"password": "falsch-falsch"})
    assert r.status_code == 403
    assert calls == [] and _gibt_es("mia@test.ch")
