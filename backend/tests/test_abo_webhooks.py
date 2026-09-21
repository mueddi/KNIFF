"""Kniff Plus: Checkout als Abo, Kuendigen, Stripe-Webhooks (beide Objektformen)."""
import json
import time
from datetime import datetime, timedelta

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import Payment, User
from app.routers import pay

from .test_library import register_pw
from .test_pay import enable_payments, signed_headers


class _Resp:
    def __init__(self, body, status=200):
        self._body, self.status_code, self.text = body, status, json.dumps(body)

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def abo_an(monkeypatch):
    enable_payments(monkeypatch)
    monkeypatch.setattr(settings, "abo_enabled", True)


@pytest.fixture
def stripe(monkeypatch):
    """Faengt alle Stripe-Aufrufe ab: calls = [(method, path, data, headers)]."""
    calls = []
    antworten = {}

    def fake_request(method, url, data=None, auth=None, headers=None, timeout=None):
        path = url.replace("https://api.stripe.com", "")
        calls.append((method, path, data or {}, headers or {}))
        return antworten.get((method, path)) or _Resp({"url": "https://checkout.stripe.com/c/test", "id": "cs_test"})

    monkeypatch.setattr(pay.httpx, "request", fake_request)
    return calls, antworten


def _me(client, headers):
    return client.get("/api/auth/me", headers=headers).json()


def _user(email):
    with SessionLocal() as db:
        return db.query(User).filter(User.email == email).one()


def _event(typ, obj, event_id="evt_1"):
    return json.dumps({"id": event_id, "type": typ, "data": {"object": obj}}).encode()


def _post_event(client, typ, obj, event_id="evt_1"):
    payload = _event(typ, obj, event_id)
    r = client.post("/api/pay/webhook", content=payload, headers=signed_headers(payload))
    assert r.status_code == 200, r.text


def _ts(days):
    return int((datetime.utcnow() + timedelta(days=days)).timestamp())


# ---- Checkout ----

def test_checkout_startet_ein_abo(client, stripe):
    calls, _ = stripe
    headers = register_pw(client, "mia@test.ch")
    r = client.post("/api/pay/checkout", headers=headers, json={"intervall": "monat"})
    assert r.status_code == 200 and r.json()["url"].startswith("https://checkout.stripe.com/")
    method, path, data, hdrs = calls[-1]
    assert (method, path) == ("POST", "/v1/checkout/sessions")
    assert data["mode"] == "subscription"
    assert data["line_items[0][price_data][recurring][interval]"] == "month"
    assert data["line_items[0][price_data][unit_amount]"] == str(settings.plus_preis_monat_rappen)
    assert data["line_items[0][price_data][currency]"] == "chf"
    assert data["customer_email"] == "mia@test.ch"
    assert data["subscription_data[metadata][user_id]"] == str(_me(client, headers)["id"])
    assert "/app/einstellungen?zahlung=ok" in data["success_url"]
    assert hdrs["Stripe-Version"] == settings.stripe_api_version  # TWINT-Abos

    r = client.post("/api/pay/checkout", headers=headers, json={"intervall": "jahr"})
    assert r.status_code == 200
    data = calls[-1][2]
    assert data["line_items[0][price_data][recurring][interval]"] == "year"
    assert data["line_items[0][price_data][unit_amount]"] == str(settings.plus_preis_jahr_rappen)


def test_checkout_mit_aktivem_abo_ist_409(client, stripe):
    headers = register_pw(client, "mia@test.ch")
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == "mia@test.ch").one()
        u.abo_bis = datetime.utcnow() + timedelta(days=10)
        db.commit()
    assert client.post("/api/pay/checkout", headers=headers, json={"intervall": "monat"}).status_code == 409


# ---- Webhooks ----

def _sub_obj(sub_id, user_id, ende_days, neue_form=True, **extra):
    obj = {"id": sub_id, "object": "subscription", "customer": "cus_1", "status": "active",
           "cancel_at_period_end": False, "metadata": {"user_id": str(user_id), "intervall": "monat"}}
    if neue_form:
        obj["items"] = {"data": [{"current_period_end": _ts(ende_days)}]}
    else:
        obj["current_period_end"] = _ts(ende_days)
    obj.update(extra)
    return obj


def test_abo_abschluss_setzt_plus(client, stripe):
    calls, antworten = stripe
    headers = register_pw(client, "mia@test.ch")
    uid = _me(client, headers)["id"]
    antworten[("GET", "/v1/subscriptions/sub_1")] = _Resp(_sub_obj("sub_1", uid, 30))
    _post_event(client, "checkout.session.completed", {
        "id": "cs_1", "mode": "subscription", "payment_status": "paid",
        "client_reference_id": str(uid), "customer": "cus_1", "subscription": "sub_1",
        "metadata": {"user_id": str(uid), "intervall": "monat"},
    })
    u = _user("mia@test.ch")
    assert (u.stripe_customer_id, u.stripe_subscription_id, u.abo_intervall) == ("cus_1", "sub_1", "monat")
    assert u.abo_bis > datetime.utcnow() + timedelta(days=29)
    assert client.get("/api/quota", headers=headers).json()["stufe"] == "plus"

    # Dasselbe Ereignis nochmal (Stripe-Retry) aendert nichts
    antworten[("GET", "/v1/subscriptions/sub_1")] = _Resp(_sub_obj("sub_1", uid, 5))
    _post_event(client, "checkout.session.completed", {
        "id": "cs_1", "mode": "subscription", "client_reference_id": str(uid),
        "customer": "cus_1", "subscription": "sub_1", "metadata": {"user_id": str(uid)},
    })
    assert _user("mia@test.ch").abo_bis > datetime.utcnow() + timedelta(days=29)


def test_abo_abschluss_ohne_lesbares_abo_sperrt_niemanden_aus(client, stripe):
    calls, antworten = stripe
    headers = register_pw(client, "mia@test.ch")
    uid = _me(client, headers)["id"]
    antworten[("GET", "/v1/subscriptions/sub_x")] = _Resp({"error": "nope"}, status=500)
    _post_event(client, "checkout.session.completed", {
        "id": "cs_2", "mode": "subscription", "client_reference_id": str(uid),
        "subscription": "sub_x", "metadata": {"intervall": "jahr"},
    })
    u = _user("mia@test.ch")
    assert u.abo_bis > datetime.utcnow() + timedelta(days=360)


@pytest.mark.parametrize("neue_form", [True, False])
def test_rechnung_verlaengert_das_abo(client, stripe, neue_form):
    headers = register_pw(client, "mia@test.ch")
    uid = _me(client, headers)["id"]
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == "mia@test.ch").one()
        u.stripe_subscription_id, u.abo_bis = "sub_1", datetime.utcnow() + timedelta(days=2)
        db.commit()
    invoice = {"id": "in_1", "object": "invoice", "customer": "cus_1", "amount_paid": 990,
               "lines": {"data": [{"period": {"end": _ts(32)}}]}}
    if neue_form:
        invoice["parent"] = {"subscription_details": {"subscription": "sub_1", "metadata": {"user_id": str(uid)}}}
    else:
        invoice["subscription"] = "sub_1"
    _post_event(client, "invoice.paid", invoice, event_id=f"evt_inv_{neue_form}")
    u = _user("mia@test.ch")
    assert u.abo_bis > datetime.utcnow() + timedelta(days=31)
    with SessionLocal() as db:
        zahlung = db.query(Payment).filter(Payment.session_id == "in_1").one()
        assert (zahlung.amount_rappen, zahlung.tokens, zahlung.user_id) == (990, 0, uid)


def test_rechnung_ohne_bekanntes_abo_gibt_200_und_alarm(client, stripe, monkeypatch):
    register_pw(client, "mia@test.ch")
    alarme = []
    monkeypatch.setattr(pay.alert, "notify", lambda kind, detail, key=None: alarme.append(detail))
    _post_event(client, "invoice.paid", {"id": "in_fremd", "subscription": "sub_fremd", "amount_paid": 990})
    assert alarme and "in_fremd" in alarme[0]


def test_kuendigung_und_ende_ueber_webhook(client, stripe):
    headers = register_pw(client, "mia@test.ch")
    uid = _me(client, headers)["id"]
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == "mia@test.ch").one()
        u.stripe_subscription_id, u.abo_bis = "sub_1", datetime.utcnow() + timedelta(days=20)
        db.commit()
    _post_event(client, "customer.subscription.updated", _sub_obj("sub_1", uid, 20, cancel_at_period_end=True), "evt_u1")
    u = _user("mia@test.ch")
    assert u.abo_gekuendigt is True and u.abo_bis > datetime.utcnow() + timedelta(days=19)
    assert client.get("/api/quota", headers=headers).json()["stufe"] == "plus"  # bis zum Periodenende

    _post_event(client, "customer.subscription.updated", _sub_obj("sub_1", uid, 20, cancel_at_period_end=False), "evt_u2")
    assert _user("mia@test.ch").abo_gekuendigt is False

    _post_event(client, "customer.subscription.deleted", _sub_obj("sub_1", uid, 20, status="canceled"), "evt_d1")
    u = _user("mia@test.ch")
    assert u.abo_bis <= datetime.utcnow() and u.abo_gekuendigt is True
    assert client.get("/api/quota", headers=headers).json()["stufe"] == "trial"


def test_doppeltes_ereignis_wird_ignoriert(client, stripe):
    headers = register_pw(client, "mia@test.ch")
    uid = _me(client, headers)["id"]
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == "mia@test.ch").one()
        u.stripe_subscription_id, u.abo_bis = "sub_1", datetime.utcnow() + timedelta(days=20)
        db.commit()
    _post_event(client, "customer.subscription.updated", _sub_obj("sub_1", uid, 20, cancel_at_period_end=True), "evt_same")
    assert _user("mia@test.ch").abo_gekuendigt is True
    # gleiche Ereignis-ID, anderer Inhalt -> keine Wirkung
    _post_event(client, "customer.subscription.updated", _sub_obj("sub_1", uid, 20, cancel_at_period_end=False), "evt_same")
    assert _user("mia@test.ch").abo_gekuendigt is True


# ---- Kuendigen / Weiter ----

def test_kuendigen_und_zuruecknehmen(client, stripe):
    calls, _ = stripe
    headers = register_pw(client, "mia@test.ch")
    assert client.post("/api/pay/abo/kuendigen", headers=headers).status_code == 404  # kein Abo
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == "mia@test.ch").one()
        u.stripe_subscription_id, u.abo_bis = "sub_1", datetime.utcnow() + timedelta(days=20)
        db.commit()
    r = client.post("/api/pay/abo/kuendigen", headers=headers)
    assert r.status_code == 200 and r.json()["abo_gekuendigt"] is True and r.json()["stufe"] == "plus"
    assert calls[-1][:3] == ("POST", "/v1/subscriptions/sub_1", {"cancel_at_period_end": "true"})
    r = client.post("/api/pay/abo/weiter", headers=headers)
    assert r.status_code == 200 and r.json()["abo_gekuendigt"] is False
    assert calls[-1][2] == {"cancel_at_period_end": "false"}


def test_health_meldet_abo_schalter(client, monkeypatch):
    body = client.get("/api/health").json()
    assert body["abo"] is True and body["zahlung"] is True
    assert not any("sk_" in str(v) or "whsec" in str(v) for v in body.values())
    monkeypatch.setattr(settings, "abo_enabled", False)
    assert client.get("/api/health").json()["abo"] is False
