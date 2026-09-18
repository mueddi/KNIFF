"""Zahlung: Checkout-Guard, Webhook-Signatur, Betrags-Validierung, idempotente Gutschrift."""
import hashlib
import hmac
import json
import time

from app.config import settings
from app.database import SessionLocal
from app.models import User
from app.routers.pay import PACKAGES

from .test_library import register_pw

WEBHOOK_SECRET = "whsec_test_1234"


def signed_headers(payload: bytes, secret: str = WEBHOOK_SECRET, ts: int | None = None) -> dict:
    t = ts if ts is not None else int(time.time())
    sig = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return {"stripe-signature": f"t={t},v1={sig}"}


def paid_event(user_id, session_id: str = "cs_test_1", package: str = "power",
               amount: int | None = None, currency: str = "chf") -> bytes:
    return json.dumps(
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": session_id,
                    "payment_status": "paid",
                    "client_reference_id": str(user_id),
                    "metadata": {"user_id": str(user_id), "package": package},
                    "amount_total": amount if amount is not None else PACKAGES[package]["rappen"],
                    "currency": currency,
                }
            },
        }
    ).encode()


def token_balance(email: str) -> int:
    with SessionLocal() as db:
        return db.query(User).filter(User.email == email).one().token_balance


def enable_payments(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_webhook_secret", WEBHOOK_SECRET)


def test_checkout_disabled_without_config(client):
    headers = register_pw(client, "mia@test.ch")
    r = client.post("/api/pay/checkout", headers=headers)
    assert r.status_code == 503


def test_checkout_rejects_unknown_package(client, monkeypatch):
    enable_payments(monkeypatch)
    headers = register_pw(client, "mia@test.ch")
    r = client.post("/api/pay/checkout", headers=headers, json={"package": "gratisluxus"})
    assert r.status_code == 400


def test_webhook_credits_tokens_idempotently(client, monkeypatch):
    enable_payments(monkeypatch)
    headers = register_pw(client, "mia@test.ch")
    me = client.get("/api/auth/me", headers=headers).json()
    payload = paid_event(me["id"])

    # Falsche Signatur -> 400, nichts gutgeschrieben
    bad = client.post("/api/pay/webhook", content=payload,
                      headers={"stripe-signature": "t=1,v1=deadbeef"})
    assert bad.status_code == 400
    assert token_balance("mia@test.ch") == 0

    # Abgelaufener Zeitstempel -> 400
    old = client.post("/api/pay/webhook", content=payload,
                      headers=signed_headers(payload, ts=int(time.time()) - 3600))
    assert old.status_code == 400

    # Gültig -> Tokens gutgeschrieben, Plan wechselt auf token
    ok = client.post("/api/pay/webhook", content=payload, headers=signed_headers(payload))
    assert ok.status_code == 200, ok.text
    assert token_balance("mia@test.ch") == PACKAGES["power"]["tokens"]
    assert client.get("/api/auth/me", headers=headers).json()["plan"] == "token"

    # Stripe-Retry derselben Session -> keine doppelte Gutschrift
    again = client.post("/api/pay/webhook", content=payload, headers=signed_headers(payload))
    assert again.status_code == 200
    assert token_balance("mia@test.ch") == PACKAGES["power"]["tokens"]

    # Andere Session -> weitere Gutschrift
    payload2 = paid_event(me["id"], session_id="cs_test_2")
    client.post("/api/pay/webhook", content=payload2, headers=signed_headers(payload2))
    assert token_balance("mia@test.ch") == 2 * PACKAGES["power"]["tokens"]


def test_webhook_credits_each_package_size(client, monkeypatch):
    enable_payments(monkeypatch)
    headers = register_pw(client, "mia@test.ch")
    me = client.get("/api/auth/me", headers=headers).json()

    p1 = paid_event(me["id"], session_id="cs_s1", package="schnupper")
    assert client.post("/api/pay/webhook", content=p1, headers=signed_headers(p1)).status_code == 200
    assert token_balance("mia@test.ch") == 200

    p2 = paid_event(me["id"], session_id="cs_s2", package="starter")
    client.post("/api/pay/webhook", content=p2, headers=signed_headers(p2))
    assert token_balance("mia@test.ch") == 1100


def test_webhook_rejects_wrong_amount_or_currency(client, monkeypatch):
    """Betrag/Währung müssen exakt zum Paket passen – sonst keine Gutschrift."""
    enable_payments(monkeypatch)
    headers = register_pw(client, "mia@test.ch")
    me = client.get("/api/auth/me", headers=headers).json()

    # Power-Paket behauptet, aber nur 2.– bezahlt -> keine Gutschrift (200, kein Retry-Sturm)
    cheap = paid_event(me["id"], session_id="cs_bad1", package="power", amount=200)
    assert client.post("/api/pay/webhook", content=cheap, headers=signed_headers(cheap)).status_code == 200
    assert token_balance("mia@test.ch") == 0

    # Falsche Währung -> keine Gutschrift
    eur = paid_event(me["id"], session_id="cs_bad2", package="power", currency="eur")
    client.post("/api/pay/webhook", content=eur, headers=signed_headers(eur))
    assert token_balance("mia@test.ch") == 0

    # Unbekanntes Paket -> keine Gutschrift
    fake = paid_event(me["id"], session_id="cs_bad3", package="gratisluxus", amount=1)
    client.post("/api/pay/webhook", content=fake, headers=signed_headers(fake))
    assert token_balance("mia@test.ch") == 0


def test_webhook_survives_broken_user_reference(client, monkeypatch):
    """Kaputte Nutzer-ID darf keinen 500 auslösen (Stripe würde endlos retrien)."""
    enable_payments(monkeypatch)
    register_pw(client, "mia@test.ch")
    payload = json.dumps(
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_broken",
                    "payment_status": "paid",
                    "client_reference_id": "keine-zahl",
                    "metadata": {"package": "power"},
                    "amount_total": PACKAGES["power"]["rappen"],
                    "currency": "chf",
                }
            },
        }
    ).encode()
    r = client.post("/api/pay/webhook", content=payload, headers=signed_headers(payload))
    assert r.status_code == 200
    assert token_balance("mia@test.ch") == 0


def test_webhook_ignores_other_events(client, monkeypatch):
    enable_payments(monkeypatch)
    register_pw(client, "mia@test.ch")

    payload = json.dumps({"type": "invoice.created", "data": {"object": {}}}).encode()
    r = client.post("/api/pay/webhook", content=payload, headers=signed_headers(payload))
    assert r.status_code == 200
    assert token_balance("mia@test.ch") == 0


def test_health_zeigt_zahlungs_status(client):
    """/api/health meldet, OB die Zahlung freigeschaltet ist – als Boolean,
    niemals Schluessel oder Konfigurationsdetails (das Frontend sperrt
    darueber die Kauf-Knoepfe)."""
    body = client.get("/api/health").json()
    assert "zahlung" in body
    assert body["zahlung"] is False  # Test-Umgebung ohne Stripe-Schluessel
    assert not any("sk_" in str(v) or "whsec" in str(v) for v in body.values())


def test_return_base_bleibt_auf_der_startadresse():
    """Nach der Zahlung zurueck auf DIE Adresse, von der aus gekauft wurde –
    sonst gilt die Anmeldung dort nicht (scheinbarer Logout). Fremde Ziele
    werden ignoriert (kein offener Redirect)."""
    from app.config import settings
    from app.routers.pay import _return_base

    konfiguriert = settings.frontend_base_url.rstrip("/")

    class Req:
        def __init__(self, headers):
            self.headers = headers

    # kein Origin -> konfigurierte Adresse
    assert _return_base(Req({})) == konfiguriert
    assert _return_base(None) == konfiguriert

    # Vercel-Vorschau-Adresse desselben Projekts -> wird uebernommen
    slug = konfiguriert.split("://", 1)[1].split(".", 1)[0]
    vorschau = f"https://{slug}-git-main-abc123.vercel.app"
    assert _return_base(Req({"origin": vorschau})) == vorschau

    # Referer als Fallback (manche Browser senden kein Origin)
    assert _return_base(Req({"referer": f"{vorschau}/app/preise"})) == vorschau

    # fremde Ziele und unverschluesselt -> immer die konfigurierte Adresse
    for boese in ("https://boese.example", "https://schrittweise-2-0.boese.example",
                  "http://schrittweise-2-0.vercel.app", "https://evil.vercel.app"):
        assert _return_base(Req({"origin": boese})) == konfiguriert


def test_return_base_kennt_die_vorschau_auch_unter_eigener_domain(monkeypatch):
    """Laeuft die Produktion unter kniff.app, steckt der Projektname nicht mehr
    in der Live-Adresse – die Vorschau muss trotzdem auf sich selbst
    zurueckfuehren, sonst landet man nach der Zahlung scheinbar ausgeloggt."""
    from app.routers.pay import _return_base

    monkeypatch.setattr(settings, "frontend_base_url", "https://kniff.app")
    monkeypatch.setenv("VERCEL_ENV", "preview")
    monkeypatch.setenv("VERCEL_BRANCH_URL", "schrittweise-2-0-git-mein-zweig-mahmmoud-said.vercel.app")
    monkeypatch.setenv("VERCEL_URL", "schrittweise-2-0-7bh8v7uza-mahmmoud-said.vercel.app")

    class Req:
        def __init__(self, headers):
            self.headers = headers

    assert _return_base(Req({"origin": "https://schrittweise-2-0-git-mein-zweig-mahmmoud-said.vercel.app"})) \
        == "https://schrittweise-2-0-git-mein-zweig-mahmmoud-said.vercel.app"
    assert _return_base(Req({"origin": "https://schrittweise-2-0-7bh8v7uza-mahmmoud-said.vercel.app"})) \
        == "https://schrittweise-2-0-7bh8v7uza-mahmmoud-said.vercel.app"
    assert _return_base(Req({"origin": "https://kniff.app"})) == "https://kniff.app"
    for boese in ("https://evil.vercel.app", "https://kniff.app.boese.example", "http://kniff.app"):
        assert _return_base(Req({"origin": boese})) == "https://kniff.app"
