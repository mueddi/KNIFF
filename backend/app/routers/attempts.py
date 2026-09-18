"""Hinweis-Leiter-Chat: Schuelerantwort -> SymPy -> Leiter-Zustand -> Tutor (Streaming)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..deps import require_student
from ..models import Attempt, AttemptStatus, Exercise, Message, MessageRole, UploadedImage, User
from ..schemas import (
    AttemptOut,
    AttemptStateOut,
    ChatRequest,
    ExerciseOut,
    MessageOut,
    message_out,
)
from .. import i18n
from ..services import aggregates, alert, quota, tutor, usage
from ..services.sympy_verifier import check_reply_math, verify

router = APIRouter(prefix="/api/attempts", tags=["attempts"])

# Frequenz-Bremse: mehr Nachrichten pro Minute schafft kein Mensch beim Lernen.
# Verhindert, dass viele PARALLELE Anfragen das Guthaben-Gate ueberholen
# (Abbuchung erfolgt erst nach der Antwort, Boden bei 0).
CHAT_MAX_PER_MINUTE = 8
# Kostenschranke pro Aufgabe: mit Kniff Plus sind die Probe-Aufgaben in
# Runden unbegrenzt - ohne Deckel koennte eine einzige Aufgabe beliebig
# teuer werden. 40 Nachrichten sind mehr, als je eine Aufgabe brauchte.
CHAT_MAX_PER_ATTEMPT = 40


def _ohne_offenen_figur_block(text: str) -> str:
    """Unfertigen [[FIGUR]]-Block am Ende abschneiden.

    Bricht die Antwort mitten in einer Skizze ab (Client weg, Timeout), wird
    der Torso gespeichert. Die Anzeige blendet unfertige Bloecke nur WAEHREND
    des Streams aus – im gespeicherten Verlauf stand danach fuer immer rohes
    JSON: «[[FIGUR]]{"typ":"waage","links":"3x + 5».
    """
    auf = text.rfind("[[FIGUR]]")
    if auf != -1 and text.find("[[/FIGUR]]", auf) == -1:
        return text[:auf].rstrip()
    return text


GELOEST_MARKER = "[[GELOEST]]"


def _marker_teilen(puffer: str, marker: str = GELOEST_MARKER) -> tuple[str, str, bool]:
    """Marker aus dem Textstrom fischen, ohne ihn je anzuzeigen.

    Der Tutor haengt ``[[GELOEST]]`` ans Ende, wenn das Kind die Aufgabe
    geloest hat. Beim Streamen kann der Marker ueber zwei Haeppchen verteilt
    ankommen (``[[GEL`` + ``OEST]]``) – deshalb wird ein moegliches Marker-
    Ende zurueckbehalten, bis feststeht, ob es wirklich der Marker ist.

    Rueckgabe: (jetzt ausgeben, zurueckbehalten, Marker gesehen).
    """
    gesehen = marker in puffer
    if gesehen:
        puffer = puffer.replace(marker, "")
    halten = 0
    for i in range(1, min(len(marker), len(puffer)) + 1):
        if puffer.endswith(marker[:i]):
            halten = i
    if not halten:
        return puffer, "", gesehen
    return puffer[:-halten], puffer[-halten:], gesehen


def _shrink_for_tutor(data: bytes, mime: str) -> tuple[bytes, str]:
    """Bild fuers LLM verkleinern (max. 1100 px): die praezise Text-Extraktion
    hat schon das OCR in voller Aufloesung gemacht – fuers Mitschauen im Chat
    reicht weniger, halbiert aber die Bild-Tokens pro Turn."""
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(data))
        if max(img.size) <= 1100:
            return data, mime
        img.thumbnail((1100, 1100))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=85)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return data, mime


def _load_owned(db: Session, attempt_id: int, user: User) -> Attempt:
    attempt = db.get(Attempt, attempt_id)
    if attempt is None or attempt.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            i18n.t(i18n.lang_of(user), "Session nicht gefunden", "Session not found"))
    return attempt


@router.get("/{attempt_id}", response_model=AttemptStateOut)
def get_state(attempt_id: int, user: User = Depends(require_student), db: Session = Depends(get_db)):
    attempt = _load_owned(db, attempt_id, user)
    ex = db.get(Exercise, attempt.exercise_id)
    msgs = list(db.scalars(select(Message).where(Message.attempt_id == attempt.id).order_by(Message.id)))
    return AttemptStateOut(
        attempt=AttemptOut.model_validate(attempt),
        messages=[message_out(m) for m in msgs],
        exercise=ExerciseOut.model_validate(ex),
    )


def _setze_geloest(db: Session, attempt: Attempt, geloest: bool) -> Attempt:
    """Hand-Schalter fuer «erledigt».

    Bewusst OHNE Aenderung an ``hint_level``/``own_attempts``: die beschreiben,
    wieviel Hilfe noetig war, und das aendert ein Haken nicht. Und bewusst
    ohne KI: das kostet nichts, geht immer und funktioniert auch dann, wenn
    Modell oder Pruefung sich uneinig sind.
    """
    attempt.solved = geloest
    attempt.status = AttemptStatus.solved if geloest else AttemptStatus.active
    db.commit()
    db.refresh(attempt)
    try:
        aggregates.recompute_week(db, attempt.user_id)
        db.commit()
    except Exception as exc:
        db.rollback()
        alert.notify("server",
                     f"Wochen-Aggregat nach Hand-Haken fehlgeschlagen: {type(exc).__name__}: {exc}",
                     key="recompute_week")
    return attempt


@router.post("/{attempt_id}/geloest", response_model=AttemptOut)
def als_geloest_markieren(attempt_id: int, user: User = Depends(require_student),
                          db: Session = Depends(get_db)):
    """Aufgabe von Hand als erledigt abhaken.

    Ohne diesen Weg blieb eine Aufgabe fuer immer offen, sobald die App sie
    nicht maschinell pruefen kann (Zeichnen, Begruenden, zwei Unbekannte) –
    das betrifft zwei Drittel aller Aufgaben. Das Kind sah «gelöst 🎉» nie,
    obwohl es fertig war.
    """
    return AttemptOut.model_validate(
        _setze_geloest(db, _load_owned(db, attempt_id, user), True))


@router.post("/{attempt_id}/offen", response_model=AttemptOut)
def wieder_offen(attempt_id: int, user: User = Depends(require_student),
                 db: Session = Depends(get_db)):
    """Haken wieder wegnehmen – ein Fehlgriff darf nicht endgueltig sein."""
    return AttemptOut.model_validate(
        _setze_geloest(db, _load_owned(db, attempt_id, user), False))


@router.post("/{attempt_id}/chat")
def chat(attempt_id: int, payload: ChatRequest, user: User = Depends(require_student), db: Session = Depends(get_db)):
    attempt = _load_owned(db, attempt_id, user)
    ex = db.get(Exercise, attempt.exercise_id)
    text = payload.text.strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            i18n.t(i18n.lang_of(user), "Leere Nachricht", "Empty message"))

    # Frequenz-Bremse (siehe CHAT_MAX_PER_MINUTE)
    minute_ago = datetime.now(timezone.utc) - timedelta(seconds=60)
    recent_msgs = db.scalar(
        select(func.count(Message.id))
        .join(Attempt, Message.attempt_id == Attempt.id)
        .where(Attempt.user_id == user.id,
               Message.role == MessageRole.student,
               Message.created_at >= minute_ago)
    ) or 0
    lang = i18n.lang_of(user)
    if recent_msgs >= CHAT_MAX_PER_MINUTE:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            i18n.t(lang,
                                   "Langsam 🙂 – eine Nachricht nach der anderen. Versuch es gleich nochmal.",
                                   "Slow down 🙂 – one message at a time. Try again in a moment."))

    verlauf = db.scalar(select(func.count(Message.id)).where(Message.attempt_id == attempt.id)) or 0
    if verlauf >= CHAT_MAX_PER_ATTEMPT:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            i18n.t(lang,
                                   "Diese Aufgabe ist lang geworden – starte sie neu oder nimm die nächste.",
                                   "This task has become long – restart it or take the next one."))

    # Guthaben-Gate VOR jeder Zustandsaenderung: sonst staende die Nachricht
    # ohne Antwort im Verlauf und die Leiter wuerde sich gratis weiterdrehen.
    if quota.blocked_unverified(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            i18n.t(lang,
                                   "Bitte bestätige zuerst deine E-Mail-Adresse – schau in dein Postfach.",
                                   "Please confirm your email address first – check your inbox."))
    if not quota.can_use_ki(db, user, ex.id):
        raise quota.sperre(db, user, lang, ex.id)

    # Angehaengtes Bild (Stift-Zeichnung/Foto aus /api/exercises/ocr) pruefen:
    # nur eigene, tatsaechlich gespeicherte Bilder duerfen an Nachrichten haengen.
    msg_image_path = None
    msg_image = None  # (bytes, mime) fuer den Tutor
    if payload.image_path:
        token = payload.image_path.rsplit("/", 1)[-1]
        img = None
        if payload.image_path.startswith("/api/exercises/images/"):
            img = db.scalar(select(UploadedImage).where(UploadedImage.token == token))
        if img is None or img.user_id != user.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bild nicht gefunden")
        msg_image_path = payload.image_path
        msg_image = _shrink_for_tutor(img.content, img.mime_type)

    # 1) deterministische Pruefung
    verification = verify(ex.math_expression, text)

    # 2) Leiter-Zustand berechnen (Backend ist die Autoritaet).
    #    Bereits geloest -> Zustand einfrieren: keine Stufen-/Versuchs-Aenderung,
    #    der Tutor beantwortet nur noch Verstaendnisfragen / gratuliert.
    already_solved = attempt.solved
    if already_solved:
        intent = "correct" if verification.status == "correct" else "post_solved"
        # Aufgabe ist geloest -> Loesung darf der Tutor jetzt erklaeren (permit_solution=True),
        # falls der Schueler nach dem ganzen Weg fragt. Stufe und Versuche
        # bleiben bewusst eingefroren (sie sind die Kennzahl «wieviel Hilfe
        # war noetig» im Eltern-Dashboard); den Widerspruch zwischen
        # «Erlaubte Stufe 1» und «Stufe 4 freigegeben» loest _regie auf.
        step = tutor.LadderStep(intent, max(attempt.hint_level, 1), attempt.own_attempts, True, True)
    else:
        intent = tutor.detect_intent(text, verification)
        # Laenge des Gespraechs als Notausgang gegen eine festgefahrene Leiter
        turns = db.scalar(
            select(func.count(Message.id)).where(Message.attempt_id == attempt.id)) or 0
        step = tutor.advance_ladder(attempt.hint_level, attempt.own_attempts, intent, turns=turns)

    # 3) Schuelernachricht speichern (mit interner Verifikation)
    student_msg = Message(
        attempt_id=attempt.id, role=MessageRole.student, text=text,
        verification=verification.to_context(), image_path=msg_image_path,
    )
    db.add(student_msg)

    # Attempt-Zustand fortschreiben. Die HILFE-STUFE bleibt hier bewusst
    # unangetastet: sie beschreibt, wieviel Hilfe der Tutor GEGEBEN hat, und
    # der Aufruf kommt erst danach. Wurde sie hier hochgesetzt, schob ein
    # KI-Ausfall das Kind eine Sprosse weiter, ohne dass je ein Hinweis kam –
    # vier misslungene Nachrichten reichten von Stufe 1 auf 4. Sie wird unten
    # im Generator gesetzt, sobald die Antwort wirklich da ist.
    # own_attempts und solved beschreiben dagegen, was das KIND getan hat –
    # die stimmen auch dann, wenn die Antwort nie ankommt.
    attempt.own_attempts = step.own_attempts
    if step.solved:
        attempt.solved = True
        attempt.status = AttemptStatus.solved
    db.commit()

    # Verlauf (nur Schueler-Rolle liest hier -> require_student) fuer den LLM-Kontext
    history = [
        {"role": m.role.value, "text": m.text}
        for m in db.scalars(select(Message).where(Message.attempt_id == attempt.id).order_by(Message.id))
    ]
    ex_text, ex_expr = ex.text, ex.math_expression
    attempt_id_local = attempt.id
    user_id_local = user.id
    grade_level = user.grade_level
    lang_local = lang

    # Aufgaben-Figur (Foto) fuer den Tutor laden – bei Geometrie steckt die
    # halbe Aufgabe im Bild. Fehlt es (alte /tmp-Pfade), laeuft der Chat ohne.
    # Nach der Loesung (post_solved, keine neue Zeichnung) wird das Bild nicht
    # mehr mitgeschickt: Verstaendnisfragen brauchen es nicht, und der Turn
    # laeuft dann uebers guenstige Modell.
    image = None
    if (already_solved and msg_image is None):
        pass
    elif ex.image_path and ex.image_path.startswith("/api/exercises/images/"):
        token = ex.image_path.rsplit("/", 1)[-1]
        img = db.scalar(select(UploadedImage).where(UploadedImage.token == token))
        if img is not None:
            image = _shrink_for_tutor(img.content, img.mime_type)
    # Aggregate nur beim Uebergang zu «geloest» neu rechnen, nicht bei jedem Post-Solved-Chat
    solved_now = step.solved and not already_solved

    # Stufe der Antwort fuer die Chat-Anzeige; nach der Loesung keine Stufe mehr
    reply_level = None if already_solved else step.allowed_stage

    exercise_id_local = ex.id
    stufe_local = quota.stufe(db, user, ex.id)
    # Darf der Tutor diese Runde selbst abhaken?
    # * Nicht, wenn die Aufgabe schon zu ist.
    # * Nicht, wenn SymPy WIDERSPRICHT – dann bleibt SymPy die Autoritaet und
    #   das Modell kann eine falsche Antwort nicht richtigreden.
    # * Nicht auf eine Bettelei hin («zeig mir die Loesung»): auf dieser Runde
    #   liefert der TUTOR die Loesung, das Kind hat nichts geloest. Genau so
    #   wurde eine Aufgabe abgehakt, sobald man den Knopf drueckte – waehrend
    #   die selbst gerechnete Loesung eine Runde davor offen blieb.
    tutor_darf_abhaken = (not already_solved
                          and verification.status != "incorrect"
                          and step.intent != "plea")

    def generate():
        parts: list[str] = []
        usage_out: dict = {}
        rest = ""            # moegliches Marker-Bruchstueck am Haeppchen-Ende
        marker_gesehen = False
        try:
            for chunk in tutor.stream_reply(history, step, verification, ex_text, ex_expr,
                                            grade_level, image, usage_out,
                                            last_image=msg_image, language=lang_local):
                raus, rest, gesehen = _marker_teilen(rest + chunk)
                marker_gesehen = marker_gesehen or gesehen
                if raus:
                    parts.append(raus)
                    yield raus
            # Uebrig gebliebenes Bruchstueck: nur ausgeben, wenn es KEIN
            # angefangener Marker ist – sonst stuende «[[GELO» im Chat.
            if rest and not GELOEST_MARKER.startswith(rest):
                parts.append(rest)
                yield rest
            # Nachrechnung der Tutor-Antwort: rein numerische Gleichungen per
            # SymPy pruefen; Fehler sichtbar korrigieren + Betreiber-Alarm.
            try:
                fehler = check_reply_math("".join(parts))
            except Exception:
                fehler = []
            if fehler:
                korr = ("\n\n" + i18n.t(lang_local,
                                        "⚠️ Korrektur – oben hat sich ein Rechenfehler eingeschlichen: ",
                                        "⚠️ Correction – there's a calculation slip above: ")
                        + "; ".join(f"${raw}$ → ${richtig}$" for raw, richtig in fehler))
                parts.append(korr)
                yield korr
                alert.notify("ki-qualitaet",
                             f"Attempt {attempt_id_local}: " + "; ".join(f"{raw} -> {richtig}" for raw, richtig in fehler),
                             key=str(attempt_id_local))
        finally:
            # Auch bei Client-Abbruch (GeneratorExit) die bisherige Tutor-Antwort
            # und ggf. die Aggregate persistieren, damit kein Turn verloren geht.
            full = _ohne_offenen_figur_block("".join(parts).strip()) or i18n.t(
                lang_local,
                "Erzähl mir, wie du an die Aufgabe rangehst.",
                "Tell me how you'd approach the task.")
            # Hat der Tutor tatsaechlich geantwortet? Bei einem KI-Ausfall
            # setzt stream_reply "fehler" – dann gab es keine Hilfe, also
            # klettert die Stufe nicht und die Meldung bekommt auch kein
            # Stufen-Etikett («👣 Teilschritt vorgemacht» ueber «technische
            # Probleme» war schlicht falsch).
            geantwortet = not usage_out.get("fehler")
            # Der Tutor hat die Aufgabe abgehakt (siehe [[GELOEST]]). Das ist
            # der einzige Weg fuer Aufgaben, die SymPy nicht pruefen kann –
            # also fuer zwei Drittel aller Aufgaben.
            vom_tutor_geloest = marker_gesehen and geantwortet and tutor_darf_abhaken
            with SessionLocal() as s:
                s.add(Message(attempt_id=attempt_id_local, role=MessageRole.tutor, text=full,
                              hint_level=reply_level if geantwortet else None))
                if geantwortet and reply_level is not None:
                    s.query(Attempt).filter(Attempt.id == attempt_id_local).update(
                        {"hint_level": reply_level})
                if vom_tutor_geloest:
                    s.query(Attempt).filter(Attempt.id == attempt_id_local).update(
                        {"solved": True, "status": AttemptStatus.solved})
                if usage_out.get("usage") is not None:
                    # Verrechnung + Erfassung im selben Commit wie die Tutor-Message,
                    # damit charged_tokens nie vom tatsaechlich Abgebuchten abweicht.
                    charged = 0
                    if stufe_local != "school":
                        charged = usage.charged_tokens(
                            usage.cost_usd(usage_out.get("model", ""), usage_out["usage"]))
                        quota.charge(s, user_id_local, charged,
                                     vom_guthaben=stufe_local == "guthaben")
                    usage.record(s, "chat", usage_out.get("model", ""), usage_out["usage"],
                                 user_id=user_id_local, exercise_id=exercise_id_local,
                                 charged=charged)
                s.commit()
            if solved_now or vom_tutor_geloest:
                # BEWUSST in einer EIGENEN Sitzung und NACH dem Commit oben:
                # scheitert recompute_week (es endet mit db.flush()), ist die
                # Sitzung vergiftet – das «except» heilt sie nicht, und der
                # anschliessende commit() riss Tutor-Antwort, Abbuchung und
                # Nutzungs-Erfassung mit weg. Lautlos, denn hier laeuft schon
                # die Antwort, der globale Fehler-Handler greift nicht mehr.
                try:
                    with SessionLocal() as s2:
                        aggregates.recompute_week(s2, user_id_local)
                        s2.commit()
                except Exception as exc:
                    import logging

                    logging.getLogger("schrittweise.attempts").exception(
                        "recompute_week fehlgeschlagen (User %s)", user_id_local)
                    alert.notify("server",
                                 f"Wochen-Aggregat fehlgeschlagen (User {user_id_local}): "
                                 f"{type(exc).__name__}: {exc}",
                                 key="recompute_week")

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")
