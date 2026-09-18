"""Token-Paket-Kauf über Stripe Checkout.

Ablauf: Frontend ruft /checkout auf -> Stripe-Bezahlseite (Karte/TWINT) ->
Stripe meldet die Zahlung per signiertem Webhook -> Tokens werden gutgeschrieben.
Die Stripe-API wird direkt über httpx angesprochen (form-encoded REST), die
Webhook-Signatur (HMAC-SHA256) wird mit der Standardbibliothek geprüft –
keine zusätzliche SDK-Abhängigkeit.
"""
import hashlib
import hmac
import json
import logging
import os
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import i18n
from ..config import settings
from ..database import get_db
from ..deps import require_student
from ..models import Payment, Plan, User
from ..schemas import CheckoutRequest
from ..services import alert, quota

router = APIRouter(prefix="/api/pay", tags=["pay"])
log = logging.getLogger("schrittweise.pay")

# Die Token-Pakete der Preise-Seite (Sackgeld-Modell: Einmal-Käufe, kein Abo).
# 1 Token = 1 Rappen verrechnete KI-Leistung – Paketmenge = Preis in Rappen.
PACKAGES = {
    "schnupper": {"tokens": 200, "rappen": 200, "name": "Kniff Schnupper-Paket – 200 Tokens"},
    "starter": {"tokens": 900, "rappen": 900, "name": "Kniff Starter-Paket – 900 Tokens"},
    "power": {"tokens": 1900, "rappen": 1900, "name": "Kniff Power-Paket – 1900 Tokens"},
}


def _return_base(request: Request | None) -> str:
    """Wohin Stripe nach der Zahlung zurueckschickt.

    Bevorzugt die Adresse, von der aus der Kauf gestartet wurde (Origin-
    Header) – sonst landet man auf einer ANDEREN Herkunft, wo die
    Anmeldung im Browser nicht gilt, und wird scheinbar ausgeloggt.
    Erlaubt sind nur die konfigurierte Adresse und Vercel-Adressen
    desselben Projekts – nie ein fremdes Ziel (kein offener Redirect).
    """
    configured = settings.frontend_base_url.rstrip("/")
    origin = ""
    if request is not None:
        origin = (request.headers.get("origin") or "").rstrip("/")
        if not origin:
            ref = request.headers.get("referer") or ""
            if "://" in ref:
                scheme, _, rest = ref.partition("://")
                origin = f"{scheme}://{rest.split('/', 1)[0]}"
    if not origin or origin == configured:
        return configured
    # Eine Vorschau kennt ihre eigene Adresse aus der Vercel-Umgebung. Noetig,
    # seit die Produktion unter kniff.app laeuft: der Projektname
    # (schrittweise-2-0-git-…) steckt dann nicht mehr in der Live-Adresse.
    eigene = {f"https://{os.environ.get(k, '').strip()}"
              for k in ("VERCEL_URL", "VERCEL_BRANCH_URL") if os.environ.get(k, "").strip()}
    if origin in eigene:
        return origin
    try:
        host = origin.split("://", 1)[1].split("/", 1)[0].lower()
        conf_host = configured.split("://", 1)[1].split("/", 1)[0].lower()
        slug = conf_host.split(".", 1)[0]  # z.B. "schrittweise-2-0"
        if origin.startswith("https://") and (
            host == conf_host or (host.startswith(slug) and host.endswith(".vercel.app"))
        ):
            return origin
    except Exception:
        pass
    return configured


@router.post("/checkout")
def create_checkout(request: Request, payload: CheckoutRequest | None = None,
                    user: User = Depends(require_student)):
    """Erstellt eine Stripe-Checkout-Session und gibt deren Bezahl-URL zurück."""
    if quota.blocked_unverified(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            i18n.t(i18n.lang_of(user), "Bitte bestätige zuerst deine E-Mail-Adresse, bevor du kaufst – schau in dein Postfach.", "Please confirm your email address before buying – check your inbox."))
    if not settings.payments_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            i18n.t(i18n.lang_of(user), "Die Zahlung ist noch nicht freigeschaltet – es wurde nichts belastet. Der Betreiber schaltet sie in Kürze frei.", "Payments are not enabled yet – nothing was charged. The operator will enable them shortly."),
        )
    pkg_key = payload.package if payload else "power"
    pkg = PACKAGES.get(pkg_key)
    if pkg is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, i18n.t(i18n.lang_of(user), "Unbekanntes Paket.", "Unknown package."))
    base = _return_base(request)
    data = {
        "mode": "payment",
        "success_url": f"{base}/app/preise?zahlung=ok",
        "cancel_url": f"{base}/app/preise?zahlung=abbruch",
        "client_reference_id": str(user.id),
        "customer_email": user.email,
        "metadata[user_id]": str(user.id),
        "metadata[package]": pkg_key,
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "chf",
        "line_items[0][price_data][unit_amount]": str(pkg["rappen"]),
        "line_items[0][price_data][product_data][name]": pkg["name"],
    }
    try:
        resp = httpx.post(
            "https://api.stripe.com/v1/checkout/sessions",
            data=data,
            auth=(settings.stripe_secret_key, ""),
            timeout=20,
        )
    except httpx.HTTPError:
        log.exception("Stripe nicht erreichbar")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Zahlungsanbieter nicht erreichbar – versuch es gleich nochmal.")
    if resp.status_code != 200:
        log.error("Stripe-Checkout fehlgeschlagen: HTTP %s – %s", resp.status_code, resp.text[:400])
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Zahlung konnte nicht gestartet werden – versuch es gleich nochmal.")
    return {"url": resp.json()["url"]}


def verify_stripe_signature(payload: bytes, sig_header: str, secret: str, tolerance: int = 300) -> bool:
    """Prüft die Stripe-Webhook-Signatur (t=…,v1=… / HMAC-SHA256 über 't.payload')."""
    try:
        pairs = [kv.split("=", 1) for kv in sig_header.split(",") if "=" in kv]
        timestamp = next(int(v) for k, v in pairs if k == "t")
        v1_signatures = [v for k, v in pairs if k == "v1"]
        if not v1_signatures or abs(time.time() - timestamp) > tolerance:
            return False
        expected = hmac.new(
            secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
        ).hexdigest()
        return any(hmac.compare_digest(expected, sig) for sig in v1_signatures)
    except Exception:
        return False


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Von Stripe aufgerufen. Schreibt Tokens gut – idempotent pro Checkout-Session."""
    if not settings.payments_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Zahlung nicht konfiguriert.")
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    if not verify_stripe_signature(payload, sig, settings.stripe_webhook_secret):
        alert.notify("webhook", "Ungueltige Stripe-Signatur – falsches STRIPE_WEBHOOK_SECRET oder fremder Aufruf.")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ungültige Signatur.")

    event = json.loads(payload)
    if event.get("type") != "checkout.session.completed":
        return {"received": True}
    session = event["data"]["object"]
    if session.get("payment_status") != "paid":
        return {"received": True}

    # Paket bestimmen und Betrag/Waehrung HART validieren: gutgeschrieben wird
    # nur, was exakt zum Paket passt – ein manipulierter/fremder Event kann so
    # keine Tokens erschleichen. Bei Abweichung: loggen, aber 200 zurueckgeben
    # (sonst wiederholt Stripe den Webhook endlos).
    pkg_key = (session.get("metadata") or {}).get("package") or "power"
    pkg = PACKAGES.get(pkg_key)
    amount = session.get("amount_total")
    currency = (session.get("currency") or "").lower()
    if pkg is None or amount != pkg["rappen"] or currency != "chf":
        log.error(
            "Webhook: Betrag/Waehrung passt nicht zum Paket (%s: %s %s, Session %s) – KEINE Gutschrift",
            pkg_key, amount, currency, session.get("id"),
        )
        alert.notify("webhook", f"Betrag/Waehrung passt nicht zum Paket ({pkg_key}: {amount} {currency}, Session {session.get('id')}) – keine Gutschrift.")
        return {"received": True}

    try:
        user_id = int(session.get("client_reference_id") or session["metadata"]["user_id"])
    except (TypeError, ValueError, KeyError):
        log.error("Webhook: Nutzer-ID fehlt oder ungueltig (Session %s)", session.get("id"))
        alert.notify("webhook", f"Nutzer-ID fehlt/ungueltig (Session {session.get('id')}) – Zahlung ohne Gutschrift!")
        return {"received": True}
    user = db.get(User, user_id)
    if user is None:
        log.error("Webhook: unbekannter Nutzer %s (Session %s)", user_id, session.get("id"))
        alert.notify("webhook", f"Unbekannter Nutzer {user_id} (Session {session.get('id')}) – Zahlung ohne Gutschrift!")
        return {"received": True}

    # Idempotenz: unique session_id – ein Stripe-Retry schreibt nicht doppelt gut.
    db.add(
        Payment(
            user_id=user.id,
            session_id=session["id"],
            amount_rappen=amount,
            tokens=pkg["tokens"],
        )
    )
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"received": True}  # schon verarbeitet

    db.execute(
        update(User).where(User.id == user.id).values(token_balance=User.token_balance + pkg["tokens"])
    )
    if user.plan == Plan.free:
        user.plan = Plan.token
    db.commit()
    log.info("Zahlung verbucht: Nutzer %s, +%s Tokens (%s, Session %s)", user.id, pkg["tokens"], pkg_key, session["id"])
    return {"received": True}
