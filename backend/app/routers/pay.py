"""Kniff Plus – Abo über Stripe Checkout.

Ablauf: Frontend ruft /checkout auf -> Stripe-Bezahlseite (Karte/TWINT,
mode=subscription) -> Stripe meldet per signiertem Webhook, was mit dem Abo
passiert (abgeschlossen, verlaengert, gekuendigt, beendet) -> abo_bis am
Konto wird nachgefuehrt. Kuendigen laeuft ueber die eigenen Endpunkte
(cancel_at_period_end), kein Stripe-Kundenportal noetig.

Die Stripe-API wird direkt über httpx angesprochen (form-encoded REST), die
Webhook-Signatur (HMAC-SHA256) wird mit der Standardbibliothek geprüft –
keine zusätzliche SDK-Abhängigkeit. Die alten Token-Pakete (Einmal-Kauf)
kann man nicht mehr kaufen; ihr Webhook-Zweig bleibt, damit ein verspaeteter
Stripe-Retry weiterhin sauber verbucht wird.
"""
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import i18n
from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models import ParentLink, Payment, Plan, Role, StripeEvent, User
from ..schemas import AboRequest, CheckoutRequest
from ..services import alert, quota

router = APIRouter(prefix="/api/pay", tags=["pay"])
log = logging.getLogger("schrittweise.pay")

# Die frueheren Token-Pakete: nicht mehr kaufbar, nur noch fuer den
# Webhook-Zweig mode=payment (verspaetete Retries alter Kaeufe).
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


def _stripe(method: str, path: str, data: dict | None = None) -> dict:
    """Ein Aufruf der Stripe-API; Fehler werden zu 503/502 fuer den Aufrufer."""
    try:
        resp = httpx.request(
            method, f"https://api.stripe.com{path}", data=data,
            auth=(settings.stripe_secret_key, ""),
            headers={"Stripe-Version": settings.stripe_api_version},
            timeout=20,
        )
    except httpx.HTTPError:
        log.exception("Stripe nicht erreichbar (%s %s)", method, path)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Zahlungsanbieter nicht erreichbar – versuch es gleich nochmal.")
    if resp.status_code != 200:
        log.error("Stripe %s %s fehlgeschlagen: HTTP %s – %s", method, path, resp.status_code, resp.text[:400])
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Zahlung konnte nicht gestartet werden – versuch es gleich nochmal.")
    return resp.json()


def _utcnow_naiv() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _abo_ende(sub: dict) -> datetime | None:
    """Periodenende eines Stripe-Abos – neue API-Version: am Abo-Posten,
    aeltere: am Abo selbst. Beides lesen."""
    ts = None
    items = ((sub.get("items") or {}).get("data")) or []
    if items:
        ts = items[0].get("current_period_end")
    ts = ts or sub.get("current_period_end")
    return datetime.utcfromtimestamp(int(ts)) if ts else None


def _zielkonto(db: Session, user: User, student_id: int | None) -> User:
    """Fuer wen gilt Kauf oder Kuendigung? Schueler:innen fuer sich selbst,
    Eltern fuer ein verknuepftes Kind – nie fuer ein fremdes Konto."""
    lang = i18n.lang_of(user)
    if user.role == Role.student:
        if student_id not in (None, user.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, i18n.t(lang, "Nur für das eigene Konto.", "Only for your own account."))
        return user
    if user.role == Role.parent:
        if student_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, i18n.t(lang, "Für welches Kind? Bitte das Kind angeben.", "For which child? Please specify the child."))
        link = db.scalar(select(ParentLink).where(ParentLink.parent_id == user.id,
                                                  ParentLink.student_id == student_id,
                                                  ParentLink.status == "linked"))
        student = db.get(User, student_id) if link is not None else None
        if student is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                i18n.t(lang, "Dieses Kind ist nicht mit deinem Konto verknüpft.", "This child is not linked to your account."))
        return student
    raise HTTPException(status.HTTP_403_FORBIDDEN, i18n.t(lang, "Nur für Schüler- und Eltern-Konten.", "Only for student and parent accounts."))


@router.post("/checkout")
def create_checkout(request: Request, payload: CheckoutRequest | None = None,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Erstellt eine Stripe-Checkout-Session (Abo) und gibt deren Bezahl-URL zurück.

    Eltern kaufen mit student_id fuer ihr Kind: das Abo haengt am Kind,
    die Rechnung geht an die Eltern-Adresse."""
    lang = i18n.lang_of(user)
    zahler = user
    user = _zielkonto(db, zahler, payload.student_id if payload else None)
    if quota.blocked_unverified(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            i18n.t(lang, "Bitte bestätige zuerst deine E-Mail-Adresse, bevor du kaufst – schau in dein Postfach.", "Please confirm your email address before buying – check your inbox."))
    if not settings.abo_enabled or not settings.payments_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            i18n.t(lang, "Die Zahlung ist noch nicht freigeschaltet – es wurde nichts belastet. Der Betreiber schaltet sie in Kürze frei.", "Payments are not enabled yet – nothing was charged. The operator will enable them shortly."),
        )
    intervall = (payload.intervall if payload else "monat") or "monat"
    if intervall not in ("monat", "jahr"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, i18n.t(lang, "Unbekanntes Abo-Intervall.", "Unknown subscription interval."))
    if quota.plus_aktiv(user):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            i18n.t(lang, f"{settings.plus_name} ist auf diesem Konto schon aktiv.", f"{settings.plus_name} is already active on this account."))
    base = _return_base(request)
    zurueck = f"{base}/eltern" if zahler.role == Role.parent else f"{base}/app/einstellungen"
    if intervall == "jahr":
        rappen, interval, name = settings.plus_preis_jahr_rappen, "year", f"{settings.plus_name} – jährlich"
    else:
        rappen, interval, name = settings.plus_preis_monat_rappen, "month", f"{settings.plus_name} – monatlich"
    data = {
        "mode": "subscription",
        "success_url": f"{zurueck}?zahlung=ok",
        "cancel_url": f"{zurueck}?zahlung=abbruch",
        "client_reference_id": str(user.id),
        "metadata[user_id]": str(user.id),
        "metadata[zahler_id]": str(zahler.id),
        "metadata[intervall]": intervall,
        "subscription_data[metadata][user_id]": str(user.id),
        "subscription_data[metadata][intervall]": intervall,
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "chf",
        "line_items[0][price_data][unit_amount]": str(rappen),
        "line_items[0][price_data][recurring][interval]": interval,
        "line_items[0][price_data][product_data][name]": name,
    }
    if user.stripe_customer_id:
        data["customer"] = user.stripe_customer_id
    else:
        data["customer_email"] = zahler.email
    session = _stripe("POST", "/v1/checkout/sessions", data)
    return {"url": session["url"]}


def _abo_umstellen(user: User, db: Session, kuendigen: bool) -> dict:
    lang = i18n.lang_of(user)
    if not user.stripe_subscription_id or not quota.plus_aktiv(user):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            i18n.t(lang, "Auf diesem Konto läuft kein Abo.", "There is no subscription on this account."))
    if not settings.payments_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Zahlung nicht konfiguriert.")
    _stripe("POST", f"/v1/subscriptions/{user.stripe_subscription_id}",
            {"cancel_at_period_end": "true" if kuendigen else "false"})
    user.abo_gekuendigt = kuendigen
    db.commit()
    db.refresh(user)
    return quota.quota_state(db, user)


@router.post("/abo/kuendigen")
def abo_kuendigen(payload: AboRequest | None = None, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Abo zum Periodenende beenden – bis dahin bleibt Plus aktiv."""
    ziel = _zielkonto(db, user, payload.student_id if payload else None)
    return _abo_umstellen(ziel, db, kuendigen=True)


@router.post("/abo/weiter")
def abo_weiter(payload: AboRequest | None = None, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    """Kündigung zurücknehmen, solange die Periode noch läuft."""
    ziel = _zielkonto(db, user, payload.student_id if payload else None)
    return _abo_umstellen(ziel, db, kuendigen=False)


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


def _nutzer_zum_abo(db: Session, sub_id: str | None, obj: dict) -> User | None:
    """Konto zu einem Abo-Ereignis: ueber die Abo-ID, sonst ueber die
    Nutzer-ID in den Metadaten, sonst ueber die Stripe-Kundennummer."""
    if sub_id:
        u = db.query(User).filter(User.stripe_subscription_id == sub_id).first()
        if u:
            return u
    meta = obj.get("metadata") or {}
    if not meta.get("user_id"):
        meta = ((obj.get("parent") or {}).get("subscription_details") or {}).get("metadata") or {}
    try:
        if meta.get("user_id"):
            return db.get(User, int(meta["user_id"]))
    except (TypeError, ValueError):
        pass
    cust = obj.get("customer")
    if isinstance(cust, str):
        return db.query(User).filter(User.stripe_customer_id == cust).first()
    return None


def _abo_id_der_rechnung(invoice: dict) -> str | None:
    sid = invoice.get("subscription")
    if not sid:
        sid = ((invoice.get("parent") or {}).get("subscription_details") or {}).get("subscription")
    return sid if isinstance(sid, str) else None


def _abo_abgeschlossen(db: Session, session: dict) -> None:
    try:
        user_id = int(session.get("client_reference_id") or session["metadata"]["user_id"])
        user = db.get(User, user_id)
    except (TypeError, ValueError, KeyError):
        user = None
    if user is None:
        log.error("Webhook: Nutzer zum Abo fehlt (Session %s)", session.get("id"))
        alert.notify("webhook", f"Abo ohne bekannten Nutzer (Session {session.get('id')}) – bitte in Stripe nachsehen!")
        return
    sid = session.get("subscription")
    intervall = (session.get("metadata") or {}).get("intervall") or "monat"
    if isinstance(session.get("customer"), str):
        user.stripe_customer_id = session["customer"]
    user.stripe_subscription_id = sid if isinstance(sid, str) else None
    user.abo_intervall = intervall
    user.abo_gekuendigt = False
    ende = None
    if user.stripe_subscription_id:
        try:
            ende = _abo_ende(_stripe("GET", f"/v1/subscriptions/{user.stripe_subscription_id}"))
        except HTTPException:
            log.warning("Webhook: Abo %s nicht lesbar – vorlaeufiges Periodenende", sid)
    if ende is None:
        # Nie ein bezahltes Kind aussperren: vorlaeufig; invoice.paid korrigiert.
        ende = _utcnow_naiv() + timedelta(days=367 if intervall == "jahr" else 32)
    user.abo_bis = ende
    log.info("Abo abgeschlossen: Nutzer %s, %s, bis %s", user.id, intervall, ende)


def _abo_verlaengert(db: Session, invoice: dict) -> None:
    sid = _abo_id_der_rechnung(invoice)
    user = _nutzer_zum_abo(db, sid, invoice)
    if user is None:
        log.error("Webhook: Rechnung %s ohne bekanntes Abo/Nutzer", invoice.get("id"))
        alert.notify("webhook", f"Abo-Rechnung {invoice.get('id')} ohne bekannten Nutzer – Abo wird nicht verlaengert! Fehlen dem Webhook die Ereignisse?")
        return
    if sid and not user.stripe_subscription_id:
        user.stripe_subscription_id = sid
    if isinstance(invoice.get("customer"), str) and not user.stripe_customer_id:
        user.stripe_customer_id = invoice["customer"]
    ende = None
    lines = ((invoice.get("lines") or {}).get("data")) or []
    for line in lines:
        ts = (line.get("period") or {}).get("end")
        if ts:
            ende = max(ende or datetime.min, datetime.utcfromtimestamp(int(ts)))
    if ende is None and sid:
        try:
            ende = _abo_ende(_stripe("GET", f"/v1/subscriptions/{sid}"))
        except HTTPException:
            pass
    if ende and (user.abo_bis is None or ende > user.abo_bis):
        user.abo_bis = ende
    betrag = invoice.get("amount_paid")
    if invoice.get("id") and isinstance(betrag, int):
        db.add(Payment(user_id=user.id, session_id=invoice["id"], amount_rappen=betrag, tokens=0))
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return
    log.info("Abo verlaengert: Nutzer %s bis %s (Rechnung %s)", user.id, user.abo_bis, invoice.get("id"))


def _abo_geaendert(db: Session, sub: dict, geloescht: bool) -> None:
    user = _nutzer_zum_abo(db, sub.get("id"), sub)
    if user is None:
        log.error("Webhook: Abo %s ohne bekannten Nutzer", sub.get("id"))
        alert.notify("webhook", f"Abo-Aenderung {sub.get('id')} ohne bekannten Nutzer.")
        return
    if geloescht or sub.get("status") in ("canceled", "unpaid", "incomplete_expired"):
        user.abo_bis = _utcnow_naiv()
        user.abo_gekuendigt = True
        log.info("Abo beendet: Nutzer %s (%s)", user.id, sub.get("status"))
        return
    user.abo_gekuendigt = bool(sub.get("cancel_at_period_end"))
    ende = _abo_ende(sub)
    if ende:
        user.abo_bis = ende
    if isinstance(sub.get("id"), str):
        user.stripe_subscription_id = sub["id"]
    if isinstance(sub.get("customer"), str):
        user.stripe_customer_id = sub["customer"]


def _paket_gutschrift(db: Session, session: dict) -> None:
    """Alt: Einmal-Kauf eines Token-Pakets (mode=payment)."""
    if session.get("payment_status") != "paid":
        return
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
        return

    try:
        user_id = int(session.get("client_reference_id") or session["metadata"]["user_id"])
    except (TypeError, ValueError, KeyError):
        log.error("Webhook: Nutzer-ID fehlt oder ungueltig (Session %s)", session.get("id"))
        alert.notify("webhook", f"Nutzer-ID fehlt/ungueltig (Session {session.get('id')}) – Zahlung ohne Gutschrift!")
        return
    user = db.get(User, user_id)
    if user is None:
        log.error("Webhook: unbekannter Nutzer %s (Session %s)", user_id, session.get("id"))
        alert.notify("webhook", f"Unbekannter Nutzer {user_id} (Session {session.get('id')}) – Zahlung ohne Gutschrift!")
        return

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
        return  # schon verarbeitet

    db.execute(
        update(User).where(User.id == user.id).values(token_balance=User.token_balance + pkg["tokens"])
    )
    if user.plan == Plan.free:
        user.plan = Plan.token
    log.info("Zahlung verbucht: Nutzer %s, +%s Tokens (%s, Session %s)", user.id, pkg["tokens"], pkg_key, session["id"])


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Von Stripe aufgerufen. Fuehrt Abos nach (und schreibt alte Paket-Kaeufe
    gut) – idempotent pro Ereignis-ID, immer 200 (sonst Retry-Sturm)."""
    if not settings.payments_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Zahlung nicht konfiguriert.")
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    if not verify_stripe_signature(payload, sig, settings.stripe_webhook_secret):
        alert.notify("webhook", "Ungueltige Stripe-Signatur – falsches STRIPE_WEBHOOK_SECRET oder fremder Aufruf.")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ungültige Signatur.")

    event = json.loads(payload)
    typ = event.get("type")
    obj = (event.get("data") or {}).get("object") or {}
    handler = {
        "checkout.session.completed": lambda: (_abo_abgeschlossen(db, obj) if obj.get("mode") == "subscription"
                                               else _paket_gutschrift(db, obj)),
        "invoice.paid": lambda: _abo_verlaengert(db, obj),
        "customer.subscription.updated": lambda: _abo_geaendert(db, obj, geloescht=False),
        "customer.subscription.deleted": lambda: _abo_geaendert(db, obj, geloescht=True),
    }.get(typ)
    if handler is None:
        return {"received": True}

    # Idempotenz pro Ereignis: die ID wird im SELBEN Commit wie die Wirkung
    # gespeichert – scheitert die Verarbeitung, bleibt auch die ID weg und
    # Stripes Wiederholung darf es nochmal versuchen.
    if event.get("id"):
        db.add(StripeEvent(id=event["id"]))
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return {"received": True}  # schon verarbeitet
    handler()
    db.commit()
    return {"received": True}
