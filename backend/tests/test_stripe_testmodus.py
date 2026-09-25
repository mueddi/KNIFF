"""Echter Stripe-Testmodus: legt wirklich Bezahlseiten bei Stripe an.

Alle anderen Zahlungs-Tests spielen Stripe nur nach. Genau deshalb kam am
25.9. die falsche API-Version durch: der nachgespielte Stripe sagte zu
allem ja. Dieser Test fragt den echten – im Testmodus, ohne Geld.

Laeuft nur, wenn STRIPE_TEST_SECRET_KEY gesetzt ist (GitHub-Secret), und
nur mit einem Test-Schluessel (sk_test_…). Ein Live-Schluessel bricht den
Test sofort ab, bevor irgendetwas an Stripe geht. Jede angelegte
Bezahlseite wird am Ende wieder geschlossen.
"""
import os
from datetime import datetime, timedelta

import httpx
import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import User
from app.routers import pay

from .test_library import register_pw

SCHLUESSEL = os.environ.get("STRIPE_TEST_SECRET_KEY", "").strip()

pytestmark = pytest.mark.skipif(not SCHLUESSEL, reason="STRIPE_TEST_SECRET_KEY nicht gesetzt")


@pytest.fixture()
def echter_stripe(monkeypatch):
    if not SCHLUESSEL.startswith(("sk_test_", "rk_test_")):
        pytest.fail("STRIPE_TEST_SECRET_KEY ist kein Test-Schluessel – Abbruch, es geht nichts an Stripe.")
    monkeypatch.setattr(settings, "stripe_secret_key", SCHLUESSEL)
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_nur_damit_zahlung_aktiv_ist")
    monkeypatch.setattr(settings, "abo_enabled", True)

    # Echte Aufrufe durchlassen, aber die angelegten Sitzungen merken
    echt = httpx.request
    sitzungen = []

    def mitschreiben(method, url, **kw):
        r = echt(method, url, **kw)
        if r.status_code == 200 and url.endswith("/v1/checkout/sessions"):
            sitzungen.append(r.json()["id"])
        return r

    monkeypatch.setattr(pay.httpx, "request", mitschreiben)
    yield sitzungen
    for sid in sitzungen:  # aufraeumen: nichts bleibt offen im Testkonto
        echt("POST", f"https://api.stripe.com/v1/checkout/sessions/{sid}/expire",
             auth=(SCHLUESSEL, ""), headers={"Stripe-Version": settings.stripe_api_version}, timeout=20)


def _abo_setzen(email):
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email).one()
        u.abo_bis = datetime.utcnow() + timedelta(days=10)
        u.abo_intervall = "monat"
        db.commit()


def test_stripe_nimmt_version_und_abo_checkout_an(client, echter_stripe):
    headers = register_pw(client, "stripe-test@test.ch")
    for intervall in ("monat", "jahr"):
        r = client.post("/api/pay/checkout", headers=headers, json={"intervall": intervall})
        assert r.status_code == 200, f"{intervall}: {r.status_code} {r.text}"
        assert r.json()["url"].startswith("https://checkout.stripe.com/")
    assert len(echter_stripe) == 2


def test_stripe_nimmt_paket_checkout_an(client, echter_stripe):
    headers = register_pw(client, "stripe-paket@test.ch")
    _abo_setzen("stripe-paket@test.ch")
    for paket in ("schnupper", "starter", "power"):
        r = client.post("/api/pay/tokens", headers=headers, json={"paket": paket})
        assert r.status_code == 200, f"{paket}: {r.status_code} {r.text}"
        assert r.json()["url"].startswith("https://checkout.stripe.com/")
    assert len(echter_stripe) == 3


def test_falsche_version_wuerde_auffallen(echter_stripe, monkeypatch):
    """Gegenprobe: der Test merkt wirklich, wenn Stripe ablehnt."""
    monkeypatch.setattr(settings, "stripe_api_version", "2026-05-27")  # ohne Namenszusatz
    with pytest.raises(Exception) as e:
        pay._stripe("GET", "/v1/balance")
    assert "502" in str(e.value) or getattr(e.value, "status_code", None) == 502
