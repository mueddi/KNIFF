"""Aufgaben anlegen und Attempts (Hinweis-Leiter-Sessions) starten + Foto-OCR."""
import io
import logging
import secrets

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from .. import i18n
from ..deps import require_student
from ..models import Attempt, Exercise, Message, MessageRole, Topic, UploadedImage, User
from ..schemas import (
    AttemptOut,
    AttemptStateOut,
    ExerciseCreate,
    ExerciseOut,
    MessageOut,
    message_out,
    OcrResult,
)
from ..services import quota, usage
from ..services.ocr import OcrUnavailable, get_ocr_provider
from ..services.sympy_verifier import extract_expression

router = APIRouter(prefix="/api/exercises", tags=["exercises"])

# iPhone-Fotos (HEIC) lesbar machen – ohne das Paket bleibt alles wie bisher.
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # pragma: no cover
    pass

ALLOWED_IMG = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/heic"}
MAX_UPLOAD = 8 * 1024 * 1024


def _shrink_for_storage(data: bytes) -> tuple[bytes, str]:
    """Verkleinert Fotos fuer die DB-Ablage (laengste Kante 1600px, JPEG q85).

    Kleine PNGs (Stift-Eingabe) bleiben verlustfrei PNG. Haelt die Antwort des
    Bild-Endpoints sicher unter dem Vercel-Limit (~4.5 MB) und die DB schlank.
    """
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(data))
        if (img.format or "").upper() == "PNG" and len(data) <= 1024 * 1024:
            return data, "image/png"
        if max(img.size) > 1600:
            img.thumbnail((1600, 1600))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=85)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        # im Zweifel Original speichern – besser gross als gar kein Bild
        return data, "image/jpeg"


@router.post("/ocr", response_model=OcrResult)
async def ocr_upload(request: Request, file: UploadFile = File(...),
                     user: User = Depends(require_student), db: Session = Depends(get_db)):
    """Foto hochladen -> OCR-Preview (erkannter Text + Mathe-Ausdruck)."""
    if quota.blocked_unverified(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            i18n.t(i18n.lang_of(user), "Bitte bestätige zuerst deine E-Mail-Adresse – schau in dein Postfach.", "Please confirm your email address first – check your inbox."))
    if not quota.can_use_ki(db, user):
        raise quota.sperre(db, user, i18n.lang_of(user))
    if file.content_type not in ALLOWED_IMG:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, i18n.t(i18n.lang_of(user), "Bitte ein Bild hochladen (PNG/JPG/WebP).", "Please upload an image (PNG/JPG/WebP)."))
    # Groesse VOR dem Einlesen aus dem Header pruefen (kein RAM-DoS durch Riesen-Body).
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD + 4096:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, i18n.t(i18n.lang_of(user), "Bild zu gross (max. 8 MB).", "Image too large (max. 8 MB)."))
    # Chunk-weise lesen und bei Ueberschreitung abbrechen (falls Header fehlt/luegt).
    data = b""
    while chunk := await file.read(1024 * 256):
        data += chunk
        if len(data) > MAX_UPLOAD:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, i18n.t(i18n.lang_of(user), "Bild zu gross (max. 8 MB).", "Image too large (max. 8 MB)."))
    # Magic-Bytes pruefen: nur echte Bilddaten akzeptieren (Content-Type ist client-gesetzt).
    try:
        from PIL import Image
        import io

        Image.open(io.BytesIO(data)).verify()
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, i18n.t(i18n.lang_of(user), "Die Datei ist kein gueltiges Bild.", "The file is not a valid image."))
    # Frequenz-Bremse: jede Erkennung ist ein bezahlter KI-Aufruf; mehr als
    # 10 in 10 Minuten schafft kein Mensch beim Aufgaben-Erfassen.
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func

    from ..models import ApiUsage

    window = datetime.now(timezone.utc) - timedelta(minutes=10)
    recent_ocr = db.scalar(
        select(func.count(ApiUsage.id)).where(
            ApiUsage.user_id == user.id, ApiUsage.kind == "ocr",
            ApiUsage.created_at >= window,
        )
    ) or 0
    if recent_ocr >= 10:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            i18n.t(i18n.lang_of(user), "Viele Fotos auf einmal 🙂 – warte ein paar Minuten und versuch es dann nochmal.", "That's a lot of photos at once 🙂 – wait a few minutes and try again."))

    provider = get_ocr_provider()
    try:
        result = provider.recognize(data)
    except OcrUnavailable:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            i18n.t(i18n.lang_of(user), "Die Erkennung ist gerade nicht erreichbar – dein Geschriebenes bleibt erhalten, versuch es gleich nochmal.", "Recognition is unavailable right now – your input is kept, please try again in a moment."),
        )
    # Bild dauerhaft in der DB ablegen – /tmp verliert Dateien bei jedem Kaltstart.
    stored, mime = _shrink_for_storage(data)
    token = secrets.token_hex(16)
    db.add(UploadedImage(user_id=user.id, token=token, mime_type=mime,
                         size_bytes=len(stored), content=stored))
    last = getattr(provider, "last_usage", None)
    if last:
        charged = 0
        kstufe = quota.stufe(db, user)
        if kstufe != "school":
            charged = usage.charged_tokens(usage.cost_usd(last["model"], last["usage"]))
            quota.charge(db, user.id, charged, vom_guthaben=kstufe == "guthaben")
        usage.record(db, "ocr", last["model"], last["usage"], user_id=user.id, charged=charged)
    db.commit()
    result.image_path = f"/api/exercises/images/{token}"
    return result


@router.get("/images/{token}")
def get_image(token: str, db: Session = Depends(get_db)):
    """Liefert ein gespeichertes Aufgaben-Bild. Bewusst ohne Auth: <img src>
    schickt keinen Bearer-Header; der 128-Bit-Token macht die URL unerratbar."""
    img = db.scalar(select(UploadedImage).where(UploadedImage.token == token))
    if img is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bild nicht gefunden")
    # Der Inhalt hinter einem Token aendert sich nie – also darf ihn der Browser
    # UND das Vercel-Netz (s-maxage) ein Jahr lang behalten. Vorher lief jede
    # Anzeige desselben Fotos erneut durch die Funktion und die Datenbank;
    # jetzt nur die erste. Die Adresse bleibt das Geheimnis (128-Bit-Token),
    # daran aendert der Zwischenspeicher nichts.
    return Response(content=img.content, media_type=img.mime_type,
                    headers={"Cache-Control": "public, max-age=31536000, s-maxage=31536000, immutable"})


def _is_task_request(text: str) -> bool:
    """Erkennt Meta-Bitten wie «mache mir eine aufgabe» / "make me a task".

    Nur kurze Texte ohne Gleichung und mit hoechstens einer Ziffer –
    echte (Text-)Aufgaben enthalten Zahlen oder ein «=» und bleiben
    unangetastet.
    """
    import re

    t = (text or "").strip().lower()
    if not t or len(t) > 100 or "=" in t or sum(c.isdigit() for c in t) > 1:
        return False
    de = re.search(r"\b(mach|mache|gib|erstell|erstelle|generier|generiere|stell|stelle)\b.*\b(aufgabe|übung|uebung)", t)
    en = re.search(r"\b(make|give|create|generate)\b.*\b(task|exercise|problem)", t)
    return bool(de or en)


# Deterministische Beispiel-Aufgaben, falls keine KI konfiguriert ist (lokal/Tests)
_FALLBACK_TASKS = {
    "mittelstufe": {"de": "Berechne: 348 + 267", "en": "Calculate: 348 + 267"},
    "oberstufe": {"de": "Löse nach x auf: 3x + 5 = 20", "en": "Solve for x: 3x + 5 = 20"},
    "gymnasium": {"de": "Bestimme die Nullstellen von f(x) = x^2 - 5x + 6",
                  "en": "Find the zeros of f(x) = x^2 - 5x + 6"},
}


def _generate_task_text(db: Session, user: User, topic_name: str | None) -> str:
    """Erzeugt eine passende Uebungsaufgabe (Stufe/Thema/Sprache des Nutzers).

    Mit API-Key via Haiku (verrechnet wie eine Variante), sonst ein
    deterministischer Fallback pro Stufe.
    """
    lang = i18n.lang_of(user)
    grade = (user.grade_level or "oberstufe").lower()
    if not settings.anthropic_api_key:
        key = ("gymnasium" if "gym" in grade
               else "mittelstufe" if "mittel" in grade else "oberstufe")
        return _FALLBACK_TASKS[key][lang]

    import anthropic

    stufe = f"Stufe: {user.grade_level}" if user.grade_level else "Stufe: Oberstufe (Sek I)"
    thema = f" Thema: {topic_name}." if topic_name else ""
    sprache = "auf ENGLISCH" if lang == "en" else "auf Deutsch"
    resp = anthropic.Anthropic(api_key=settings.anthropic_api_key).messages.create(
        model=settings.anthropic_model_default,
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": (
                "Erzeuge GENAU EINE Mathe-Uebungsaufgabe fuer Schweizer "
                f"Schueler:innen ({stufe}).{thema} Schwierigkeitsgrad passend "
                f"zur Stufe, {sprache}. Gib NUR den Aufgabentext zurueck, "
                "ohne Einleitung oder Loesung."
            ),
        }],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    charged = 0
    kstufe = quota.stufe(db, user)
    if kstufe != "school":
        charged = usage.charged_tokens(usage.cost_usd(settings.anthropic_model_default, resp.usage))
        quota.charge(db, user.id, charged, vom_guthaben=kstufe == "guthaben")
    usage.record(db, "generiert", settings.anthropic_model_default, resp.usage,
                 user_id=user.id, charged=charged)
    if not text or len(text) > 1000:
        key = ("gymnasium" if "gym" in grade
               else "mittelstufe" if "mittel" in grade else "oberstufe")
        return _FALLBACK_TASKS[key][lang]
    return text


@router.post("", response_model=ExerciseOut, status_code=201)
def create_exercise(payload: ExerciseCreate, user: User = Depends(require_student), db: Session = Depends(get_db)):
    if quota.blocked_unverified(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            i18n.t(i18n.lang_of(user), "Bitte bestätige zuerst deine E-Mail-Adresse – schau in dein Postfach.", "Please confirm your email address first – check your inbox."))
    if not quota.can_use_ki(db, user):
        raise quota.sperre(db, user, i18n.lang_of(user))
    if payload.topic_id is not None:
        topic = db.get(Topic, payload.topic_id)
        if topic is None or topic.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, i18n.t(i18n.lang_of(user), "Thema nicht gefunden", "Topic not found"))
    # «Mache mir eine Aufgabe»: Meta-Bitte statt Aufgabe -> echte Aufgabe
    # erzeugen (Stufe/Thema/Sprache), sonst startet der Chat ins Leere.
    text = payload.text.strip()
    math_expr = (payload.math_expression or "").strip() or None
    if not payload.image_path and _is_task_request(text):
        topic_name = None
        if payload.topic_id is not None:
            topic_name = getattr(db.get(Topic, payload.topic_id), "name", None)
        text = _generate_task_text(db, user, topic_name)
        math_expr = None
    # Ohne expliziten Ausdruck versuchen, eine pruefbare Gleichung aus dem Text
    # zu ziehen («Löse 3x = 15» -> «3x = 15»); sonst waere die Aufgabe nie verifizierbar.
    if math_expr is None:
        math_expr = extract_expression(text)
    ex = Exercise(
        user_id=user.id,
        text=text,
        math_expression=math_expr,
        topic_id=payload.topic_id,
        image_path=payload.image_path,
    )
    db.add(ex)
    db.flush()
    if payload.image_path:
        _erkennung_der_aufgabe_zuordnen(db, user.id, ex.id)
    # Anlegen kostet nichts mehr – abgerechnet wird pro KI-Antwort im Chat.
    db.commit()
    db.refresh(ex)
    return ExerciseOut.model_validate(ex)


# Wie lange nach dem Foto darf die Aufgabe angelegt werden, damit die
# Erkennung noch ihr zugeordnet wird? Gemessen: zwischen Foto und Aufgabe
# liegen Sekunden; 30 Minuten decken auch den Fall «zuerst Text korrigiert».
ERKENNUNG_ZUORDNUNG_MINUTEN = 30


def _erkennung_der_aufgabe_zuordnen(db: Session, user_id: int, exercise_id: int) -> None:
    """Die juengste Foto-Erkennung dieses Nutzers an die neue Aufgabe haengen.

    Die Erkennung laeuft, BEVOR es die Aufgabe gibt – ihre Kostenzeile hatte
    deshalb nie eine exercise_id, und die Kostenauswertung «pro Aufgabe» sah
    nur den Chat. Gemessen in der Produktion: das Foto kostet so viel wie
    drei Chat-Runden und fehlte in jeder Aufgaben-Summe (116 von 116
    Erkennungen ohne Aufgabe). Nur die juengste, noch nicht zugeordnete
    Zeile aus den letzten 30 Minuten – eine Erkennung, ein Foto, eine Aufgabe.
    """
    from datetime import datetime, timedelta, timezone

    from ..models import ApiUsage

    seit = datetime.now(timezone.utc) - timedelta(minutes=ERKENNUNG_ZUORDNUNG_MINUTEN)
    zeile = db.scalars(
        select(ApiUsage)
        .where(ApiUsage.user_id == user_id, ApiUsage.kind == "ocr",
               ApiUsage.exercise_id.is_(None), ApiUsage.created_at >= seit)
        .order_by(ApiUsage.created_at.desc())
        .limit(1)
    ).first()
    if zeile is not None:
        zeile.exercise_id = exercise_id


# --------------------------------------------------------------------------
# Eroeffnungsnachricht
#
# Frueher stand hier EIN fester Satz. Bei der dritten Aufgabe klang der Tutor
# damit wie ein Automat – gemeldet als «roboterhaft», und zu Recht: die erste
# Zeile ist das Erste, was ein Kind von ihm liest.
#
# Die Auswahl haengt an der Attempt-Nummer, nicht am Zufall. Damit bleibt sie
# fuer dieselbe Aufgabe stabil (kein Wechsel beim Neuladen der Seite), wechselt
# aber von Aufgabe zu Aufgabe durch.
# --------------------------------------------------------------------------

ANREDE_MIT_TEXT = [
    ("Los geht's! Deine Aufgabe:", "Let's go! Your task:"),
    ("Schauen wir sie uns an:", "Let's take a look:"),
    ("Neue Aufgabe:", "New task:"),
    ("Die hier nehmen wir uns vor:", "Here's the one we'll tackle:"),
]

ANREDE_MIT_BILD = [
    ("Los geht's! Deine Aufgabe ist auf dem Bild oben 📷.",
     "Let's go! Your task is in the picture above 📷."),
    ("Dein Foto ist da 📷 – schauen wir es uns an.",
     "Your photo is here 📷 – let's take a look."),
    ("Ich hab dein Bild 📷.", "I've got your picture 📷."),
]

ANREDE_SCHLICHT = [
    ("Los geht's!", "Let's go!"),
    ("Fangen wir an.", "Let's begin."),
    ("Bereit?", "Ready?"),
]

EINSTIEGSFRAGEN = [
    ("Wie würdest du anfangen? Kein Stress – ich helf dir Schritt für Schritt.",
     "How would you start? No stress – I'll help you step by step."),
    ("Was fällt dir als Erstes auf?", "What do you notice first?"),
    ("Wo würdest du ansetzen? Wenn du nicht weiterweisst, frag einfach.",
     "Where would you start? Just ask if you get stuck."),
    ("Magst du einen ersten Versuch? Falsch ist völlig okay.",
     "Want to give it a first try? Getting it wrong is completely fine."),
    ("Erzähl mir, was du schon siehst.", "Tell me what you can already see."),
]


def _variante(saetze: list[tuple[str, str]], nummer: int, lang: str) -> str:
    de, en = saetze[nummer % len(saetze)]
    return i18n.t(lang, de, en)


def _strip_figure_notes(text: str) -> str:
    """Entfernt OCR-Beschreibungszeilen ([Figur: …]/[Graph: …]) fuer die Anzeige.

    Im gespeicherten Exercise.text bleiben sie erhalten (Tutor-Kontext),
    aber im sichtbaren Chat sind sie ueberfluessig – das Bild steht direkt
    darueber in der Aufgaben-Karte.
    """
    import re

    cleaned = re.sub(r"\[(figur|graph|zeichnung|skizze|bild|drawing|figure|sketch)\s*:[\s\S]*?\]",
                     "", text or "", flags=re.IGNORECASE)
    return re.sub(r"\n{2,}", "\n", cleaned).strip()


def _meaningful_task_text(text: str) -> bool:
    """Ist der Text alleine aussagekraeftig – oder nur lose Figur-Fragmente?

    Bei Geometrie-Zeichnungen transkribiert die Erkennung manchmal einzelne
    Beschriftungen («30», «x») als eigene Zeilen; ohne das Bild ergeben die
    keinen Sinn. Aussagekraeftig ist eine Zeile mit ganzem Satz/Formelzeile
    (>= 3 Tokens), einem echten Wort (>= 4 Buchstaben) oder einer
    Gleichung (enthaelt «=», z.B. «x = 6»).
    """
    import re

    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line.split()) >= 3:
            return True
        if re.search(r"[A-Za-zÄÖÜäöüß]{4,}", line):
            return True
        if "=" in line:
            return True
    return False


def _start_attempt_state(db: Session, ex: Exercise, user: User) -> AttemptStateOut:
    """Neuen Attempt mit Eroeffnungsnachricht anlegen (fuer Start, Retry, Variante)."""
    # Alt-Aufgaben heilen: fehlt der pruefbare Ausdruck (z.B. «2 + 4» aus der
    # Zeit, als nur Gleichungen erkannt wurden), einmalig nachziehen.
    if not ex.math_expression:
        guessed = extract_expression(ex.text)
        if guessed:
            ex.math_expression = guessed
    attempt = Attempt(exercise_id=ex.id, user_id=user.id, hint_level=0, own_attempts=0)
    db.add(attempt)
    db.flush()

    lang = i18n.lang_of(user)
    shown = _strip_figure_notes(ex.text)
    # Bei Bild-Aufgaben nur zitieren, was alleine Sinn ergibt – lose
    # Figur-Beschriftungen («30», «x») bleiben weg, das Bild ist die Aufgabe.
    if ex.image_path and not _meaningful_task_text(shown):
        shown = ""
    if shown and shown != "(Aufgabe auf dem Foto)":
        intro = _variante(ANREDE_MIT_TEXT, attempt.id, lang) + f"\n\n{shown}"
    elif ex.image_path:
        intro = _variante(ANREDE_MIT_BILD, attempt.id, lang)
    else:
        intro = _variante(ANREDE_SCHLICHT, attempt.id, lang)
    opener = Message(
        attempt_id=attempt.id,
        role=MessageRole.tutor,
        # Andere Verschiebung als bei der Anrede, damit sich nicht immer
        # dieselben zwei Saetze paaren.
        text=intro + "\n\n" + _variante(EINSTIEGSFRAGEN, attempt.id + 2, lang),
    )
    db.add(opener)
    db.commit()
    db.refresh(attempt)

    msgs = list(db.scalars(select(Message).where(Message.attempt_id == attempt.id).order_by(Message.id)))
    return AttemptStateOut(
        attempt=AttemptOut.model_validate(attempt),
        messages=[message_out(m) for m in msgs],
        exercise=ExerciseOut.model_validate(ex),
    )


@router.post("/{exercise_id}/attempts", response_model=AttemptStateOut, status_code=201)
def start_attempt(exercise_id: int, user: User = Depends(require_student), db: Session = Depends(get_db)):
    ex = db.get(Exercise, exercise_id)
    if ex is None or ex.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, i18n.t(i18n.lang_of(user), "Aufgabe nicht gefunden", "Task not found"))
    # Mit Kniff Plus zaehlt die Probe AUFGABEN: die Sperre greift beim Beginn
    # einer neuen Aufgabe, nicht erst bei der ersten Antwort.
    if settings.abo_enabled and not quota.can_use_ki(db, user, ex.id):
        raise quota.sperre(db, user, i18n.lang_of(user), ex.id)
    return _start_attempt_state(db, ex, user)


@router.post("/{exercise_id}/variante", response_model=AttemptStateOut, status_code=201)
def create_variant(exercise_id: int, user: User = Depends(require_student), db: Session = Depends(get_db)):
    """«Nochmal so eine»: KI erzeugt eine Uebungs-Variante (gleicher Typ, andere
    Zahlen) und startet sie direkt – der staerkste Lerneffekt nach dem Loesen."""
    ex = db.get(Exercise, exercise_id)
    if ex is None or ex.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, i18n.t(i18n.lang_of(user), "Aufgabe nicht gefunden", "Task not found"))
    if quota.blocked_unverified(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            i18n.t(i18n.lang_of(user), "Bitte bestätige zuerst deine E-Mail-Adresse – schau in dein Postfach.", "Please confirm your email address first – check your inbox."))
    if not quota.can_use_ki(db, user):
        raise quota.sperre(db, user, i18n.lang_of(user))
    if not settings.anthropic_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            i18n.t(i18n.lang_of(user), "Varianten brauchen die KI – sie ist gerade nicht konfiguriert.", "Variants need the AI – it is not configured right now."))

    import anthropic

    grade = f" (Stufe: {user.grade_level})" if user.grade_level else ""
    sprache = ("Schreibe die neue Aufgabe auf ENGLISCH."
               if i18n.lang_of(user) == "en" else "Gleiche Sprache wie das Original.")
    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=settings.anthropic_model_default,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": (
                    "Erzeuge GENAU EINE Variante dieser Mathe-Uebungsaufgabe: gleicher "
                    "Aufgabentyp und Schwierigkeitsgrad, aber andere Zahlen/Werte. "
                    f"{sprache}{grade} Gib NUR den neuen "
                    f"Aufgabentext zurueck, ohne Einleitung.\n\nOriginal:\n{ex.text}"
                ),
            }],
        )
        new_text = "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception:
        logging.getLogger("schrittweise.exercises").exception("Varianten-Erzeugung fehlgeschlagen")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            i18n.t(i18n.lang_of(user), "Konnte gerade keine Variante erzeugen – versuch es gleich nochmal.", "Couldn't create a variant right now – please try again in a moment."))
    if not new_text or len(new_text) > 1000:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            i18n.t(i18n.lang_of(user), "Konnte gerade keine Variante erzeugen – versuch es gleich nochmal.", "Couldn't create a variant right now – please try again in a moment."))

    new_ex = Exercise(
        user_id=user.id,
        text=new_text,
        math_expression=extract_expression(new_text),
        topic_id=ex.topic_id,
    )
    db.add(new_ex)
    db.flush()
    # Verrechnung wie jede KI-Leistung (nach echten Kosten, min. 1 Token)
    charged = 0
    kstufe = quota.stufe(db, user)
    if kstufe != "school":
        charged = usage.charged_tokens(usage.cost_usd(settings.anthropic_model_default, resp.usage))
        quota.charge(db, user.id, charged, vom_guthaben=kstufe == "guthaben")
    usage.record(db, "variante", settings.anthropic_model_default, resp.usage,
                 user_id=user.id, exercise_id=new_ex.id, charged=charged)
    return _start_attempt_state(db, new_ex, user)


@router.post("/generieren", response_model=AttemptStateOut, status_code=201)
def generate_exercise(payload: dict | None = None,
                      user: User = Depends(require_student), db: Session = Depends(get_db)):
    """«Keine Aufgabe zur Hand»: KI erzeugt eine passende Aufgabe (Stufe/
    Thema/Sprache) und startet sie direkt."""
    if quota.blocked_unverified(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            i18n.t(i18n.lang_of(user), "Bitte bestätige zuerst deine E-Mail-Adresse – schau in dein Postfach.", "Please confirm your email address first – check your inbox."))
    if not quota.can_use_ki(db, user):
        raise quota.sperre(db, user, i18n.lang_of(user))
    topic_id = (payload or {}).get("topic_id")
    topic_name = None
    if topic_id is not None:
        topic = db.get(Topic, int(topic_id))
        if topic is None or topic.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, i18n.t(i18n.lang_of(user), "Thema nicht gefunden", "Topic not found"))
        topic_name = topic.name
    try:
        text = _generate_task_text(db, user, topic_name)
    except Exception:
        logging.getLogger("schrittweise.exercises").exception("Aufgaben-Erzeugung fehlgeschlagen")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            i18n.t(i18n.lang_of(user), "Konnte gerade keine Aufgabe erzeugen – versuch es gleich nochmal.", "Couldn't create a task right now – please try again in a moment."))
    ex = Exercise(user_id=user.id, text=text,
                  math_expression=extract_expression(text),
                  topic_id=int(topic_id) if topic_id is not None else None)
    db.add(ex)
    db.flush()
    return _start_attempt_state(db, ex, user)

