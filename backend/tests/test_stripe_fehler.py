"""Stripe-Fehlerwege: was passiert, wenn Stripe nicht antwortet, ablehnt oder
etwas Unerwartetes schickt. Keiner davon darf ein unbehandelter Absturz sein,
und keiner darf Tokens oder ein Abo gutschreiben."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import User
from app.routers import pay

from .test_library import register_pw
from .test_pay import enable_payments, signed_headers


@pytest.fixture(autouse=True)
def abo_an(monkeypatch):
    enable_payments(monkeypatch)
    monkeypatch.setattr(settings, "abo_enabled", True)


def _konto(email):
    with SessionLocal() as db:
        return db.query(User).filter(User.email == email).one()


def test_stripe_nicht_erreichbar_gibt_503_ohne_buchung(client, monkeypatch):
    def kaputt(*a, **k):
        raise httpx.ConnectError("keine Verbindung")

    monkeypatch.setattr(pay.httpx, "request", kaputt)
    headers = register_pw(client, "mia@test.ch")
    r = client.post("/api/pay/checkout", headers=headers, json={"intervall": "monat"})
    assert r.status_code == 503
    u = _konto("mia@test.ch")
    assert u.abo_bis is None and u.token_balance == 0


def test_stripe_lehnt_ab_gibt_502_ohne_buchung(client, monkeypatch):
    """Genau der Fall vom 25.9. (falsche API-Version): Stripe sagt 400."""
    class Antwort:
        status_code, text = 400, '{"error": {"message": "Invalid Stripe API version"}}'

    monkeypatch.setattr(pay.httpx, "request", lambda *a, **k: Antwort())
    headers = register_pw(client, "mia@test.ch")
    r = client.post("/api/pay/checkout", headers=headers, json={"intervall": "jahr"})
    assert r.status_code == 502
    assert "Zahlung" in r.json()["detail"]
    assert _konto("mia@test.ch").abo_bis is None


def test_jeder_stripe_aufruf_schickt_die_version(client, monkeypatch):
    gesehen = []

    class Antwort:
        status_code, text = 200, "{}"

        def json(self):
            return {"url": "https://checkout.stripe.com/c/x", "id": "cs_x"}

    def fang(method, url, data=None, auth=None, headers=None, timeout=None):
        gesehen.append((headers or {}).get("Stripe-Version"))
        return Antwort()

    monkeypatch.setattr(pay.httpx, "request", fang)
    headers = register_pw(client, "mia@test.ch")
    client.post("/api/pay/checkout", headers=headers, json={"intervall": "monat"})
    assert gesehen and all(v == settings.stripe_api_version for v in gesehen)


@pytest.mark.parametrize("payload", [
    b"kein json",
    b"[]",
    b'{"type": "checkout.session.completed"}',
    b'{"type": "checkout.session.completed", "data": {"object": []}}',
    b'{"type": "invoice.paid", "data": {"object": {"lines": "kaputt"}}}',
    b'{"type": "customer.subscription.updated", "data": {"object": {"items": 5}}}',
])
def test_signierter_muell_im_webhook_stuerzt_nicht_ab(client, payload):
    """Nur Stripe kann signieren – aber auch ein Stripe-Ereignis in unerwarteter
    Form darf die Funktion nicht abstuerzen lassen (Stripe wiederholt sonst
    stundenlang, und die Stoerungsseite bleibt leer)."""
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/api/pay/webhook", content=payload, headers=signed_headers(payload))
    assert r.status_code < 500, (payload, r.status_code, r.text[:200])


def test_webhook_ohne_signatur_ist_400(client):
    payload = json.dumps({"id": "evt_x", "type": "invoice.paid", "data": {"object": {}}}).encode()
    r = client.post("/api/pay/webhook", content=payload, headers={"stripe-signature": "t=1,v1=falsch"})
    assert r.status_code == 400
