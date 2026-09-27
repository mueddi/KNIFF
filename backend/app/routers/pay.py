"""Kniff Plus – Abo über Stripe Checkout, Token-Pakete als Nachschub.

Ablauf: Frontend ruft /checkout auf -> Stripe-Bezahlseite (Karte/TWINT,
mode=subscription) -> Stripe meldet per signiertem Webhook, was mit dem Abo
passiert (abgeschlossen, verlaengert, gekuendigt, beendet) -> abo_bis am
Konto wird nachgefuehrt. Die Abo-Tokens bucht keine Rechnung: solange abo_bis
in der Zukunft liegt, gibt services/quota jeden Abo-Monat frische
plus_tokens_monat (der Rest verfaellt), beim Jahresabo Monat fuer Monat.
Kuendigen laeuft ueber die eigenen Endpunkte (cancel_at_period_end), kein
Stripe-Kundenportal noetig.

Token-Pakete (/tokens, mode=payment) gibt es nur mit aktivem Abo; sie landen
im gekauften Guthaben (token_balance) und verfallen nie.

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
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import i18n
from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models import ParentLink, Payment, Plan, Role, StripeEvent, TokenAdjustment, User
from ..schemas import AboRequest, CheckoutRequest, TokenKaufRequest
from ..services import alert, quota
from ..services.quota import PAKETE as PACKAGES

router = APIRouter(prefix="/api/pay", tags=["pay"])
log = logging.getLogger("schrittweise.pay")


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


def abo_vor_loeschung_beenden(user: User) -> None:
    """Laeuft auf dem Konto ein Abo, das sich noch verlaengern wuerde, wird es
    bei Stripe SOFORT beendet - bevor das Konto geloescht wird.

    Sonst bucht Stripe Monat fuer Monat weiter ab, und das Konto, ueber das
    man kuendigen koennte, gibt es nicht mehr. Klappt das Beenden nicht,
    bricht die Loeschung ab (HTTPException): lieber ein Konto zu viel als
    Abbuchungen ohne Konto. Ein gekuendigtes Abo verlaengert sich nicht mehr
    und braucht nichts; kennt Stripe das Abo nicht (404), ist nichts offen."""
    if not user.stripe_subscription_id or not quota.plus_aktiv(user) or user.abo_gekuendigt:
        return
    lang = i18n.lang_of(user)
    fehler = i18n.t(lang,
                    "Dein Abo konnte gerade nicht beendet werden. Damit nichts weiter abgebucht wird, bleibt das Konto bestehen – versuch es in ein paar Minuten nochmal.",
                    "Your subscription could not be ended right now. So that nothing keeps being charged, the account stays – please try again in a few minutes.")
    sid = user.stripe_subscription_id
    try:
        if not settings.payments_enabled:
            raise RuntimeError("Zahlung nicht konfiguriert")
        resp = httpx.request(
            "DELETE", f"https://api.stripe.com/v1/subscriptions/{sid}",
            auth=(settings.stripe_secret_key, ""),
            headers={"Stripe-Version": settings.stripe_api_version},
            timeout=20,
        )
    except (httpx.HTTPError, RuntimeError) as e:
        log.error("Abo %s vor Kontoloeschung nicht beendet: %s", sid, e)
        alert.notify("zahlung", f"Kontoloeschung abgebrochen: Abo {sid} liess sich nicht beenden ({e}).", key=sid)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, fehler)
    if resp.status_code == 404:
        log.warning("Abo %s bei Stripe unbekannt – Kontoloeschung laeuft weiter", sid)
        return
    if resp.status_code != 200:
        log.error("Abo %s vor Kontoloeschung nicht beendet: HTTP %s – %s", sid, resp.status_code, resp.text[:400])
        alert.notify("zahlung", f"Kontoloeschung abgebrochen: Abo {sid} liess sich nicht beenden (HTTP {resp.status_code}).", key=sid)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, fehler)
    log.info("Abo %s vor Kontoloeschung beendet (Nutzer %s)", sid, user.id)


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


@router.get("/preise")
def preise():
    """Oeffentlich, ohne Anmeldung: was Kniff kostet und welches Modell gilt.

    Die Startseite und die AGB lesen das hier, statt Zahlen fest einzubauen –
    sonst stuende auf der Startseite «50 Gratis-Tokens», waehrend die App
    schon Kniff Plus verkauft (oder umgekehrt). Keine Geheimnisse drin."""
    return {
        "abo_enabled": settings.abo_enabled,
        "zahlung": settings.payments_enabled,
        "plus_name": settings.plus_name,
        "monat_rappen": settings.plus_preis_monat_rappen,
        "jahr_rappen": settings.plus_preis_jahr_rappen,
        "trial_tasks": settings.trial_tasks,
        "plus_tokens_monat": settings.plus_tokens_monat,
        "pakete": [{"key": k, "tokens": p["tokens"], "rappen": p["rappen"]} for k, p in PACKAGES.items()],
        "free_monthly_tokens": settings.free_monthly_tokens,
    }


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


@router.post("/tokens")
def tokens_kaufen(request: Request, payload: TokenKaufRequest | None = None,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Token-Paket nachkaufen – nur mit aktivem Abo. Eltern kaufen mit
    student_id fuer ihr Kind. Gutschrift kommt per Webhook (_paket_gutschrift)."""
    lang = i18n.lang_of(user)
    zahler = user
    user = _zielkonto(db, zahler, payload.student_id if payload else None)
    if quota.blocked_unverified(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            i18n.t(lang, "Bitte bestätige zuerst deine E-Mail-Adresse, bevor du kaufst – schau in dein Postfach.", "Please confirm your email address before buying – check your inbox."))
    if not settings.abo_enabled or not settings.payments_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            i18n.t(lang, "Die Zahlung ist noch nicht freigeschaltet – es wurde nichts belastet.", "Payments are not enabled yet – nothing was charged."))
    key = (payload.paket if payload else "starter") or "starter"
    pkg = PACKAGES.get(key)
    if pkg is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, i18n.t(lang, "Unbekanntes Paket.", "Unknown package."))
    if not quota.plus_aktiv(user):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            i18n.t(lang, f"Token-Pakete gibt es nur zusammen mit {settings.plus_name}.", f"Token packages are only available together with {settings.plus_name}."))
    base = _return_base(request)
    zurueck = f"{base}/eltern" if zahler.role == Role.parent else f"{base}/app/einstellungen"
    data = {
        "mode": "payment",
        "success_url": f"{zurueck}?zahlung=ok",
        "cancel_url": f"{zurueck}?zahlung=abbruch",
        "client_reference_id": str(user.id),
        "metadata[user_id]": str(user.id),
        "metadata[zahler_id]": str(zahler.id),
        "metadata[package]": key,
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "chf",
        "line_items[0][price_data][unit_amount]": str(pkg["rappen"]),
        "line_items[0][price_data][product_data][name]": pkg["name"],
    }
    if user.stripe_customer_id:
        data["customer"] = user.stripe_customer_id
    else:
        data["customer_email"] = zahler.email
    session = _stripe("POST", "/v1/checkout/sessions", data)
    return {"url": session["url"]}


def _zahlung_verbuchen(db: Session, user: User, kennung: str, betrag: int | None) -> bool:
    """Abo-Zahlung festhalten, genau einmal pro Kennung (Rechnungs- oder
    Session-ID): die Payment-Zeile mit unique session_id ist der Riegel.
    Tokens bucht sie keine (tokens=0) - die Abo-Tokens kommen monatlich aus
    services/quota. Rueckgabe: ob neu verbucht wurde."""
    db.add(Payment(user_id=user.id, session_id=kennung,
                   amount_rappen=betrag if isinstance(betrag, int) else 0, tokens=0))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return False
    return True


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
    # Zahlung festhalten. Kennung ist die Rechnung der Session, damit das
    # invoice.paid derselben Rechnung sie nicht ein zweites Mal verbucht -
    # egal, welches der beiden Ereignisse zuerst eintrifft.
    kennung = session.get("invoice") if isinstance(session.get("invoice"), str) else session.get("id")
    if kennung:
        _zahlung_verbuchen(db, user, kennung, session.get("amount_total"))
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
    # Intervall aus der Rechnungszeile nachfuehren (Anzeige «Monat»/«Jahr»).
    for line in lines:
        recurring = ((line.get("price") or {}).get("recurring") or {}) or (line.get("plan") or {})
        if recurring.get("interval") in ("month", "year"):
            user.abo_intervall = "jahr" if recurring["interval"] == "year" else "monat"
            break
    if invoice.get("id") and not _zahlung_verbuchen(db, user, invoice["id"], invoice.get("amount_paid")):
        return  # schon verbucht (z.B. ueber checkout.session.completed)
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
    """Einmal-Kauf eines Token-Pakets (mode=payment): Nachschub fuer
    Abonnenten, und weiterhin verspaetete Retries alter Kaeufe."""
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


def _kauf_zur_zahlung(db: Session, obj: dict) -> tuple[Payment | None, str | None]:
    """Welcher Kauf steckt hinter einer Charge bzw. einem Streitfall?

    Stripe meldet Erstattung und Streitfall an der Zahlung (payment_intent),
    die App kennt aber die Bezahlseite (Checkout-Session). Also fragen wir
    Stripe nach der Session zu dieser Zahlung. Rueckgabe: (Payment-Zeile oder
    None, Modus der Session "payment"|"subscription"|None). Ist Stripe nicht
    erreichbar, fliegt die HTTPException durch - der Webhook antwortet mit
    Fehler, das Ereignis bleibt unverbucht und Stripe versucht es erneut."""
    pi = obj.get("payment_intent")
    if not isinstance(pi, str) or not pi:
        return None, None
    sessions = (_stripe("GET", f"/v1/checkout/sessions?payment_intent={pi}").get("data")) or []
    for s in sessions:
        sid = s.get("id")
        zahlung = db.query(Payment).filter(Payment.session_id == sid).one_or_none() if sid else None
        return zahlung, s.get("mode")
    return None, None


def _tokens_zurueckbuchen(db: Session, zahlung: Payment, charge_id: str, ziel: int, art: str) -> int:
    """Nimmt die Tokens eines erstatteten/angefochtenen Pakets wieder weg -
    insgesamt hoechstens ``ziel`` je Charge (Stripe meldet Erstattungen
    kumuliert; Teil- und Folge-Erstattungen buchen nur die Differenz). Das
    Guthaben faellt nie unter 0: schon Verbrauchtes ist verbraucht. Jede
    Buchung steht als TokenAdjustment im Protokoll. Rueckgabe: abgezogen."""
    marke = f"Stripe-Rueckbuchung {charge_id}"
    schon = -int(db.scalar(
        select(func.coalesce(func.sum(TokenAdjustment.tokens), 0))
        .where(TokenAdjustment.user_id == zahlung.user_id, TokenAdjustment.reason.like(f"{marke}%"))
    ) or 0)
    abzug = min(ziel, zahlung.tokens) - schon
    if abzug <= 0:
        return 0
    db.add(TokenAdjustment(user_id=zahlung.user_id, admin_id=None, tokens=-abzug, reason=f"{marke} ({art})"))
    db.execute(update(User).where(User.id == zahlung.user_id).values(
        token_balance=case((User.token_balance - abzug > 0, User.token_balance - abzug), else_=0)))
    log.info("%s: Nutzer %s -%s Tokens (Charge %s)", art, zahlung.user_id, abzug, charge_id)
    return abzug


def _erstattet(db: Session, charge: dict) -> None:
    """charge.refunded: bei einem Token-Paket die erstatteten Tokens abziehen
    (1 Token = 1 Rappen, also so viele wie Rappen erstattet). Alles andere -
    etwa eine erstattete Abo-Rechnung - braucht einen Blick des Betreibers."""
    cid = charge.get("id") or "?"
    zahlung, modus = _kauf_zur_zahlung(db, charge)
    betrag = f"CHF {int(charge.get('amount_refunded') or 0) / 100:.2f}"
    if zahlung is None or modus != "payment":
        alert.notify("zahlung", f"Erstattung {cid} ({betrag}) gehoert zu keinem Token-Paket der App"
                     f"{' (Abo-Zahlung)' if modus == 'subscription' else ''} – im Stripe-Dashboard pruefen, "
                     "ob das Abo beendet werden soll.", key=cid)
        return
    _tokens_zurueckbuchen(db, zahlung, cid, int(charge.get("amount_refunded") or 0), "Erstattung")


def _angefochten(db: Session, dispute: dict) -> None:
    """charge.dispute.created: jemand hat die Zahlung bei der Bank angefochten.
    Der Betreiber muss in Stripe fristgerecht antworten -> immer Alarm. Bei
    einem Token-Paket sind die Tokens sofort weg (das Geld ist es auch)."""
    cid = dispute.get("charge") if isinstance(dispute.get("charge"), str) else "?"
    betrag = f"CHF {int(dispute.get('amount') or 0) / 100:.2f}"
    alert.notify("zahlung", f"Zahlung angefochten: Streitfall {dispute.get('id')} zu Charge {cid} ({betrag}). "
                 "Im Stripe-Dashboard vor Ablauf der Frist Belege einreichen oder akzeptieren.",
                 key=str(dispute.get("id")))
    zahlung, modus = _kauf_zur_zahlung(db, dispute)
    if zahlung is not None and modus == "payment":
        _tokens_zurueckbuchen(db, zahlung, cid, zahlung.tokens, "Streitfall")


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Von Stripe aufgerufen. Fuehrt Abos nach, schreibt Abo-Tokens und
    Paket-Kaeufe gut, bucht erstattete/angefochtene Pakete zurueck –
    idempotent pro Ereignis-ID, 200 (sonst Retry-Sturm); nur wenn Stripe
    selbst fuer eine Rueckfrage nicht erreichbar ist, ein Fehler, damit
    Stripe das Ereignis spaeter nochmal schickt."""
    if not settings.payments_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Zahlung nicht konfiguriert.")
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    if not verify_stripe_signature(payload, sig, settings.stripe_webhook_secret):
        alert.notify("webhook", "Ungueltige Stripe-Signatur – falsches STRIPE_WEBHOOK_SECRET oder fremder Aufruf.")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ungültige Signatur.")

    # Signiert heisst nicht wohlgeformt: kein JSON-Objekt -> 400 statt Absturz.
    try:
        event = json.loads(payload)
    except ValueError:
        event = None
    if not isinstance(event, dict):
        log.error("Webhook: Inhalt ist kein JSON-Objekt")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ungültiger Inhalt.")
    typ = event.get("type")
    obj = (event.get("data") or {}).get("object") or {}
    if not isinstance(obj, dict):
        obj = {}
    handler = {
        "checkout.session.completed": lambda: (_abo_abgeschlossen(db, obj) if obj.get("mode") == "subscription"
                                               else _paket_gutschrift(db, obj)),
        "invoice.paid": lambda: _abo_verlaengert(db, obj),
        "customer.subscription.updated": lambda: _abo_geaendert(db, obj, geloescht=False),
        "customer.subscription.deleted": lambda: _abo_geaendert(db, obj, geloescht=True),
        "charge.refunded": lambda: _erstattet(db, obj),
        "charge.dispute.created": lambda: _angefochten(db, obj),
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
