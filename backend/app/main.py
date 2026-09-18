"""Kniff – FastAPI-Backend (Einstiegspunkt)."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import SessionLocal, init_db
from .routers import (admin, auth, topics, exercises, attempts, parents, quota, library,
                      pay, feedback, stats, grades, exams)


logger = logging.getLogger("schrittweise")


def _check_production_config() -> None:
    """Verhindert unsichere Konfiguration in Produktion (Vercel).

    Ein Default-JWT-Secret erlaubt Token-Faelschung, ein Dev-Login-Leak den
    Account-Takeover – in Produktion beides ein harter Startfehler statt Warnung.
    """
    if not settings.is_production:
        return
    if settings.jwt_secret_is_placeholder:
        raise RuntimeError(
            "JWT_SECRET ist der Platzhalter-Wert. In Produktion einen langen "
            "Zufallswert setzen (openssl rand -hex 32), sonst sind Tokens faelschbar."
        )
    if settings.magic_link_dev_return and not settings.allow_insecure_dev_login:
        raise RuntimeError(
            "MAGIC_LINK_DEV_RETURN=true in Produktion: Login-Links wuerden im "
            "Klartext zurueckgegeben (Account-Takeover). SMTP konfigurieren und "
            "MAGIC_LINK_DEV_RETURN=false setzen – oder fuer einen bewussten "
            "Test-Deploy zusaetzlich ALLOW_INSECURE_DEV_LOGIN=true setzen."
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    _check_production_config()
    init_db()
    if settings.jwt_secret_is_placeholder:
        logger.warning(
            "JWT_SECRET ist der Default-Wert – fuer den Betrieb einen langen "
            "Zufallswert setzen (openssl rand -hex 32)."
        )
    if settings.magic_link_dev_return:
        logger.warning(
            "MAGIC_LINK_DEV_RETURN=true: Login-Links werden direkt zurueckgegeben. "
            "NUR fuer Entwicklung – in Produktion ausschalten und SMTP konfigurieren!"
        )
    yield


app = FastAPI(title="Kniff API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(Exception)
async def unhandled_error(request, exc):
    """Unbehandelte Server-Fehler: loggen + als Stoerung im Admin sichtbar
    machen (Alert-Zeile, gedrosselt pro Route+Fehlertyp), generisch antworten."""
    from fastapi.responses import JSONResponse

    from . import i18n
    from .services import alert

    logger.exception("Unbehandelter Fehler bei %s %s", request.method, request.url.path)
    alert.notify("server", f"{request.method} {request.url.path} – {type(exc).__name__}: {exc}",
                 key=f"{request.url.path}:{type(exc).__name__}")
    lang = i18n.lang_of(request=request)
    return JSONResponse(status_code=500, content={
        "detail": i18n.t(lang,
                         "Unerwarteter Fehler – der Betreiber wurde informiert. Versuch es gleich nochmal.",
                         "Unexpected error – the operator has been notified. Please try again in a moment."),
    })


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Kein /uploads-Verzeichnis mehr: Bilder liegen seit dem Umbau in der
# Datenbank und werden ueber /api/exercises/images/{token} ausgeliefert.
# Auf Serverless war der Ordner ohnehin eine Attrappe – /tmp ueberlebt keinen
# Deploy. Entfernt am 30.07.2026.


def _datenbank_erreichbar() -> bool:
    """Ein billiger Anschlag auf die Datenbank: laeuft sie ueberhaupt?

    Bewusst ``SELECT 1`` und nichts Teureres – die Ueberwachung ruft das alle
    paar Minuten auf. Kein Zaehlen, keine Aggregate.

    Bewusst OHNE ``alert.notify``: der Alarm wuerde selbst eine Zeile in die
    Datenbank schreiben – also genau dorthin, wo es gerade klemmt. Der Fehler
    geht ins Log, gemeldet wird er von der Ueberwachung VON AUSSEN, die den
    503er sieht. Sonst haetten wir eine Alarmanlage, die nur funktioniert,
    solange nichts brennt.
    """
    from sqlalchemy import text

    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("Health-Pruefung: Datenbank nicht erreichbar")
        return False


@app.get("/api/health")
def health():
    # "mail": kann die App E-Mails verschicken (Passwort-vergessen /
    # E-Mail-Bestaetigung)? "zahlung": sind beide Stripe-Schluessel gesetzt?
    # Nur Booleans – niemals Konfigurationsdetails oder Schluessel selbst.
    # "rueckkehr_adresse": die oeffentliche Adresse der App, auf die Mail-Links
    # zurueckfuehren. Kein Geheimnis (sie steht in jeder URL-Zeile), aber der
    # haeufigste Konfigurationsfehler: steht sie falsch – oder fehlt sie in der
    # Freigabeliste von Supabase – landet der Klick im Mail auf einer
    # unerreichbaren Seite. Sichtbar machen erspart das Raten.
    # "datenbank": ohne sie kann sich niemand anmelden, keine Aufgabe speichern,
    # keinen Chat fuehren. Vorher meldete diese Auskunft froehlich "ok", waehrend
    # der Dienst in Wahrheit tot war – eine Ueberwachung darauf haette nichts
    # gemerkt. Faellt sie aus, antwortet die Auskunft mit 503 und OHNE das Wort
    # "ok", damit ein Monitor ueberhaupt anschlagen kann.
    datenbank = _datenbank_erreichbar()
    auskunft = {
        "status": "ok" if datenbank else "datenbank-nicht-erreichbar",
        "app": "schrittweise",
        "datenbank": datenbank,
        "mail": bool(settings.supabase_auth_enabled or settings.smtp_enabled),
        "zahlung": settings.payments_enabled,
        "abo": bool(settings.abo_enabled and settings.payments_enabled),
        "rueckkehr_adresse": settings.frontend_base_url,
    }
    if not datenbank:
        from fastapi.responses import JSONResponse

        # Keine Einzelheiten nach aussen: kein Fehlertext, keine
        # Verbindungszeichenfolge. Die stehen im Log.
        return JSONResponse(status_code=503, content=auskunft)
    return auskunft


app.include_router(auth.router)
app.include_router(topics.router)
app.include_router(exercises.router)
app.include_router(attempts.router)
app.include_router(parents.router)
app.include_router(quota.router)
app.include_router(library.router)
app.include_router(pay.router)
app.include_router(feedback.router)
app.include_router(admin.router)
app.include_router(stats.router)
app.include_router(grades.router)
app.include_router(exams.router)
