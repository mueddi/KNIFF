"""Token-Pakete als Nachschub: nur mit aktivem Abo, fuer sich oder als Eltern fuers Kind."""
from datetime import datetime, timedelta

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import User

from .test_abo_webhooks import _Resp, _me, _user  # noqa: F401  (Fixtures/Helfer)
from .test_abo_webhooks import stripe  # noqa: F401
from .conftest import register
from .test_library import register_pw
from .test_pay import enable_payments, paid_event, signed_headers


@pytest.fixture(autouse=True)
def abo_an(monkeypatch):
    enable_payments(monkeypatch)
    monkeypatch.setattr(settings, "abo_enabled", True)


def _abo(email, tage=10):
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email).one()
        u.abo_bis = datetime.utcnow() + timedelta(days=tage)
        u.abo_intervall = "monat"
        db.commit()


def test_ohne_abo_gibt_es_keine_pakete(client, stripe):
    headers = register_pw(client, "mia@test.ch")
    r = client.post("/api/pay/tokens", headers=headers, json={"paket": "starter"})
    assert r.status_code == 409
    assert settings.plus_name in r.json()["detail"]


def test_mit_abo_startet_der_paketkauf(client, stripe):
    calls, _ = stripe
    headers = register_pw(client, "mia@test.ch")
    _abo("mia@test.ch")
    r = client.post("/api/pay/tokens", headers=headers, json={"paket": "starter"})
    assert r.status_code == 200 and r.json()["url"].startswith("https://checkout.stripe.com/")
    method, path, data, _ = calls[-1]
    assert (method, path) == ("POST", "/v1/checkout/sessions")
    assert data["mode"] == "payment"
    assert data["metadata[package]"] == "starter"
    assert data["line_items[0][price_data][unit_amount]"] == "900"
    assert data["line_items[0][price_data][currency]"] == "chf"
    assert "/app/einstellungen?zahlung=ok" in data["success_url"]
    assert client.post("/api/pay/tokens", headers=headers, json={"paket": "gibtsnicht"}).status_code == 400


def test_paketkauf_schreibt_dem_abonnenten_gut(client, stripe):
    headers = register_pw(client, "mia@test.ch")
    _abo("mia@test.ch")
    uid = _me(client, headers)["id"]
    payload = paid_event(uid, session_id="cs_paket", package="starter")
    assert client.post("/api/pay/webhook", content=payload, headers=signed_headers(payload)).status_code == 200
    assert _user("mia@test.ch").token_balance == 900
    assert client.get("/api/quota", headers=headers).json()["stufe"] == "plus"


def test_eltern_kaufen_pakete_fuer_das_kind(client, stripe):
    calls, _ = stripe
    kind = register_pw(client, "kind@test.ch")
    code = client.get("/api/parents/invite", headers=kind).json()["invite_code"]
    eltern_h = register(client, "mama@test.ch", role="parent", name="Mama")
    assert client.post("/api/parents/redeem", headers=eltern_h, json={"invite_code": code}).status_code == 200
    kind_id = _me(client, kind)["id"]
    # ohne Abo des Kindes: nein
    assert client.post("/api/pay/tokens", headers=eltern_h, json={"paket": "power", "student_id": kind_id}).status_code == 409
    _abo("kind@test.ch")
    r = client.post("/api/pay/tokens", headers=eltern_h, json={"paket": "power", "student_id": kind_id})
    assert r.status_code == 200
    data = calls[-1][2]
    assert data["client_reference_id"] == str(kind_id) and data["customer_email"] == "mama@test.ch"
    assert "/eltern?zahlung=ok" in data["success_url"]
