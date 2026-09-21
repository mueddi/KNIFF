"""Nutzer-Feedback und «Problem melden»: jede:r Eingeloggte sendet, nur der Betreiber liest.

Zwei Arten:
- ``feedback``: freier Text aus dem Feedback-Fenster.
- ``problem``: der Knopf «Problem melden» im Chat oder bei der Foto-Erkennung.
  Das Kind waehlt eine Kategorie, Text ist freiwillig. Der Server haengt den
  Zusammenhang selbst an – Aufgabe, letzte Nachrichten, Bild –, denn «hat nicht
  funktioniert» ohne Zusammenhang ist fuer den Betreiber wertlos, und ein Kind
  tippt das nie ab.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import i18n
from ..database import get_db
from ..deps import get_current_user, require_admin
from ..models import Alert, Attempt, Exercise, Feedback, Message, MessageRole, User
from ..schemas import FeedbackCreate, FeedbackOut

log = logging.getLogger("schrittweise.feedback")
router = APIRouter(prefix="/api/feedback", tags=["feedback"])

# Kategorien des Knopfs «Problem melden» (Anzeige-Text im Frontend)
PROBLEM_KATEGORIEN = {"erkennung", "antwort", "verraten", "technik", "anderes"}
KATEGORIE_LABEL = {
    "erkennung": "Foto/Zeichnung falsch erkannt",
    "antwort": "Antwort falsch oder unverstaendlich",
    "verraten": "Loesung verraten",
    "technik": "Technisches Problem",
    "anderes": "Anderes",
}
AUSZUG = 400


def _kuerze(text: str | None, n: int = AUSZUG) -> str:
    t = (text or "").strip().replace("\n", " ")
    return t if len(t) <= n else t[:n] + " …"


def _zusammenhang(db: Session, user: User, payload: FeedbackCreate) -> tuple[str, str | None]:
    """Aufgabe, letzte Schueler- und Tutor-Nachricht zu einem Versuch – nur
    zu einem eigenen. Rueckgabe: (Text fuer den Betreiber, Bildpfad)."""
    teile: list[str] = []
    bild = payload.image_path
    if payload.attempt_id is not None:
        attempt = db.get(Attempt, payload.attempt_id)
        if attempt is None or attempt.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                i18n.t(i18n.lang_of(user), "Aufgabe nicht gefunden", "Task not found"))
        ex = db.get(Exercise, attempt.exercise_id)
        if ex is not None:
            teile.append(f"AUFGABE: {_kuerze(ex.text)}")
            bild = bild or ex.image_path
        msgs = list(db.scalars(select(Message).where(Message.attempt_id == attempt.id)
                               .order_by(Message.id.desc()).limit(6)))
        schueler = next((m for m in msgs if m.role == MessageRole.student), None)
        tutor = next((m for m in msgs if m.role == MessageRole.tutor), None)
        if schueler is not None:
            teile.append(f"LETZTE NACHRICHT DES KINDES: {_kuerze(schueler.text)}")
        if tutor is not None:
            teile.append(f"LETZTE TUTOR-ANTWORT: {_kuerze(tutor.text)}")
        teile.append(f"HILFE-STUFE: {attempt.hint_level}, eigene Versuche: {attempt.own_attempts}, "
                     f"geloest: {'ja' if attempt.solved else 'nein'}")
    if payload.context:
        teile.append(f"ERKANNTER TEXT: {_kuerze(payload.context)}")
    return "\n".join(teile), bild


@router.post("", status_code=201)
def create_feedback(payload: FeedbackCreate, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    text = payload.text.strip()
    if payload.kind == "problem":
        if payload.category not in PROBLEM_KATEGORIEN:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unbekannte Kategorie.")
        context, bild = _zusammenhang(db, user, payload)
        eintrag = Feedback(user_id=user.id, text=text, page=payload.page, kind="problem",
                           category=payload.category, attempt_id=payload.attempt_id,
                           image_path=bild, context=context or None)
    else:
        if len(text) < 3:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Bitte etwas mehr schreiben.")
        eintrag = Feedback(user_id=user.id, text=text, page=payload.page)
    db.add(eintrag)
    db.commit()
    if eintrag.kind == "problem":
        # Mail an den Betreiber, damit er nicht auf die Seite warten muss.
        # Best effort – die Meldung ist gespeichert, die Mail ist Zugabe.
        try:
            from ..services.mailer import send_alert_mail

            send_alert_mail(f"Problem gemeldet: {KATEGORIE_LABEL.get(eintrag.category, eintrag.category)}",
                            f"Von Konto {user.id} auf {payload.page or '?'}\n\n{text or '(kein Text)'}\n\n"
                            f"{eintrag.context or ''}\n\nAdmin → Rueckmeldungen (alle Feedbacks) oder Stoerungen → Von Schuelern gemeldet.")
        except Exception:
            log.exception("Mail zur Problem-Meldung fehlgeschlagen")
    return {"ok": True, "id": eintrag.id}


# Browser-Meldungen, die KEINE Stoerung sind. Bisher ging jede Meldung als
# Alarm durch: 3 von 5 Alarmen der letzten 14 Tage waren die harmlose
# «ResizeObserver loop»-Warnung, die jeder Browser beim Groesse-Aendern wirft.
# Verrauschte Fehlerseiten schaut irgendwann niemand mehr an.
_HARMLOS = (
    "resizeobserver loop",
    "script error",            # Fremd-Skript ohne CORS: keine Information drin
    "non-error promise rejection captured",
)


def _harmlos(message: str) -> bool:
    low = message.lower()
    return any(m in low for m in _HARMLOS)


# Hoechstens so viele Browser-Fehler pro Konto und Stunde landen im Alarm:
# die Drossel in alert.notify greift pro Meldungstext, ein variierender Text
# koennte sie aushebeln und Datenbank wie Betreiber-Postfach fluten.
CLIENT_FEHLER_MAX_PRO_STUNDE = 5


@router.post("/app-fehler", status_code=201)
def report_client_error(payload: dict, user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """Browser-Fehler (JS-Crash) als Stoerung im Admin sichtbar machen.

    Bewusst schlank: nur Meldung + Seite, hart gekappt; gedrosselt pro
    Meldungstext (alert.notify) UND pro Konto (siehe oben).
    """
    from ..services import alert

    message = str((payload or {}).get("message") or "")[:300].strip()
    url = str((payload or {}).get("url") or "")[:300].strip()
    if not message or _harmlos(message):
        return {"ok": True}
    marke = f"[u{user.id}] "
    seit = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    bisher = db.scalar(select(func.count(Alert.id)).where(
        Alert.kind == "client", Alert.created_at >= seit, Alert.detail.like(marke + "%"))) or 0
    if bisher >= CLIENT_FEHLER_MAX_PRO_STUNDE:
        return {"ok": True}
    alert.notify("client", f"{marke}{url} – {message}", key=message[:80])
    return {"ok": True}


@router.get("", response_model=list[FeedbackOut])
def list_feedback(kind: str = Query("", max_length=20), offen: bool = False,
                  user: User = Depends(require_admin), db: Session = Depends(get_db)):
    stmt = (select(Feedback, User.display_name, User.role)
            .join(User, User.id == Feedback.user_id))
    if kind:
        stmt = stmt.where(Feedback.kind == kind)
    if offen:
        stmt = stmt.where(Feedback.resolved_at.is_(None))
    rows = db.execute(stmt.order_by(Feedback.id.desc()).limit(200)).all()
    out: list[FeedbackOut] = []
    for fb, name, role in rows:
        o = FeedbackOut.model_validate(fb)
        o.display_name = name
        o.role = role.value
        out.append(o)
    return out


@router.patch("/{feedback_id}/erledigt", response_model=FeedbackOut)
def mark_resolved(feedback_id: int, erledigt: bool = True,
                  user: User = Depends(require_admin), db: Session = Depends(get_db)):
    fb = db.get(Feedback, feedback_id)
    if fb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Meldung nicht gefunden.")
    fb.resolved_at = datetime.now(timezone.utc) if erledigt else None
    db.commit()
    db.refresh(fb)
    return FeedbackOut.model_validate(fb)
