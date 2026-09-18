"""Probeprüfung zu einem Thema: Vorschau, Erzeugen, Abgeben, Auswertung.

Drei Regeln, die diesen Weg vom Chat unterscheiden:

* **Kein Tutor.** Während einer Prüfung gibt es keine Hinweise und keine
  Hilfe-Leiter – sonst wäre es keine Prüfung. Der Prüfungsweg fasst
  ``Attempt.hint_level``/``own_attempts`` deshalb nirgends an.
* **Der Preis steht vorher da.** ``/vorschau`` kostet nichts und nennt die
  geschätzten Kosten, damit niemand versehentlich einen grossen Teil seines
  Monatsbudgets ausgibt.
* **Korrigiert wird mit SymPy.** Erst wenn kein Prüfausdruck vorliegt, muss
  überhaupt ein Modell ran – siehe ``services/exam.py``.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import i18n
from ..database import get_db
from ..deps import require_student
from ..models import (Exam, ExamItem, ExamStatus, Exercise, Grade, Topic, User)
from ..schemas import ExamOut, ExamSubmit, ExamVorschau, ExamZiel
from ..services import exam as exam_service
from ..services import quota, usage
from ..services.sympy_verifier import verify

router = APIRouter(prefix="/api", tags=["exams"])


def _eigenes_thema(db: Session, topic_id: int, user: User) -> Topic:
    topic = db.get(Topic, topic_id)
    if topic is None or topic.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thema nicht gefunden")
    return topic


def _eigene_pruefung(db: Session, exam_id: int, user: User) -> Exam:
    ex = db.get(Exam, exam_id)
    if ex is None or ex.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prüfung nicht gefunden")
    return ex


def _aufgaben_texte(db: Session, topic: Topic) -> list[str]:
    return [e.text for e in db.scalars(
        select(Exercise).where(Exercise.topic_id == topic.id)
        .order_by(Exercise.created_at.desc()).limit(12))]


def _to_out(db: Session, ex: Exam) -> ExamOut:
    items = sorted(ex.items, key=lambda i: i.position)
    out = ExamOut.model_validate(ex)
    out.total = len(items)
    out.richtig = sum(1 for i in items if i.verdict == "correct")
    if ex.status == ExamStatus.bewertet:
        # Je Lernziel die Trefferquote. Nur «sitzt / sitzt nicht» waere
        # entmutigend: 2 von 3 richtig ist etwas anderes als 0 von 3.
        pro_ziel: dict[str, list[bool]] = {}
        for i in items:
            if i.goal:
                pro_ziel.setdefault(i.goal, []).append(i.verdict == "correct")
        out.ziele = [ExamZiel(name=z, richtig=sum(w), total=len(w))
                     for z, w in pro_ziel.items()]
    return out


@router.post("/topics/{topic_id}/pruefung/vorschau", response_model=ExamVorschau)
def vorschau(topic_id: int, user: User = Depends(require_student),
             db: Session = Depends(get_db)):
    """Kostet NICHTS. Sagt, ob eine Prüfung möglich ist und was sie kostet."""
    topic = _eigenes_thema(db, topic_id, user)
    ziele = [z for z in (topic.learning_goals or "").splitlines() if z.strip()]
    aufgaben = _aufgaben_texte(db, topic)
    stand = quota.quota_state(db, user)

    if not ziele:
        return ExamVorschau(moeglich=False,
                            grund="Trag zuerst Lernziele beim Thema ein – daraus entsteht die Prüfung.",
                            lernziele=0, vorhandene_aufgaben=len(aufgaben),
                            guthaben=stand["remaining"])
    kosten = exam_service.kosten_schaetzung()
    if not quota.can_use_ki(db, user):
        return ExamVorschau(moeglich=False,
                            grund="Dein Guthaben ist aufgebraucht.",
                            lernziele=len(ziele), vorhandene_aufgaben=len(aufgaben),
                            kosten_rappen=kosten, guthaben=stand["remaining"])
    return ExamVorschau(moeglich=True, lernziele=len(ziele),
                        vorhandene_aufgaben=len(aufgaben), kosten_rappen=kosten,
                        guthaben=stand["remaining"])


@router.post("/topics/{topic_id}/pruefung", response_model=ExamOut, status_code=201)
def pruefung_erzeugen(topic_id: int, user: User = Depends(require_student),
                      db: Session = Depends(get_db)):
    topic = _eigenes_thema(db, topic_id, user)

    # Gates VOR dem Modellaufruf – wie im Chat. Sonst entstuenden Kosten fuer
    # eine Pruefung, die gar nicht ausgeliefert werden darf.
    if quota.blocked_unverified(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Bitte bestätige zuerst deine E-Mail-Adresse – schau in dein Postfach.")
    if not quota.can_use_ki(db, user):
        raise quota.sperre(db, user, i18n.lang_of(user))
    if not [z for z in (topic.learning_goals or "").splitlines() if z.strip()]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Trag zuerst Lernziele beim Thema ein – daraus entsteht die Prüfung.")

    usage_out: dict = {}
    try:
        aufgaben = exam_service.erzeuge(
            topic.name, topic.learning_goals, _aufgaben_texte(db, topic),
            user.grade_level, usage_out=usage_out)
    except Exception as exc:
        # Nichts speichern, nichts abbuchen: eine halbe Pruefung ist wertlos.
        from ..services import alert

        alert.notify("ki", f"Probepruefung fehlgeschlagen: {type(exc).__name__}: {exc}",
                     key="pruefung")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Die Prüfung konnte gerade nicht erstellt werden. "
                            "Versuch es in einem Moment nochmal – es wurde nichts abgebucht.")

    ex = Exam(user_id=user.id, topic_id=topic.id, status=ExamStatus.offen,
              model=usage_out.get("model", ""), learning_goals=topic.learning_goals)
    db.add(ex)
    db.flush()
    for i, a in enumerate(aufgaben, start=1):
        db.add(ExamItem(exam_id=ex.id, position=i, question=a["frage"],
                        math_expression=a["math_expression"], goal=a["goal"]))

    # Verrechnung im SELBEN Commit wie die Pruefung – sonst koennte eine
    # Pruefung entstehen, die niemand bezahlt hat (oder umgekehrt).
    if usage_out.get("usage") is not None:
        charged = 0
        kstufe = quota.stufe(db, user)
        if kstufe != "school":
            charged = usage.charged_tokens(
                usage.cost_usd(usage_out.get("model", ""), usage_out["usage"]))
            quota.charge(db, user.id, charged, vom_guthaben=kstufe == "guthaben")
        usage.record(db, "pruefung", usage_out.get("model", ""), usage_out["usage"],
                     user_id=user.id, charged=charged)
    db.commit()
    db.refresh(ex)
    return _to_out(db, ex)


@router.get("/exams/{exam_id}", response_model=ExamOut)
def pruefung_lesen(exam_id: int, user: User = Depends(require_student),
                   db: Session = Depends(get_db)):
    return _to_out(db, _eigene_pruefung(db, exam_id, user))


@router.get("/topics/{topic_id}/pruefungen", response_model=list[ExamOut])
def pruefungen_des_themas(topic_id: int, user: User = Depends(require_student),
                          db: Session = Depends(get_db)):
    _eigenes_thema(db, topic_id, user)
    exams = db.scalars(select(Exam).where(Exam.topic_id == topic_id, Exam.user_id == user.id)
                       .order_by(Exam.id.desc())).all()
    return [_to_out(db, e) for e in exams]


@router.post("/exams/{exam_id}/abgeben", response_model=ExamOut)
def pruefung_abgeben(exam_id: int, payload: ExamSubmit,
                     user: User = Depends(require_student), db: Session = Depends(get_db)):
    """Korrigiert die Prüfung und trägt die geschätzte Note in den Verlauf ein.

    Die Korrektur läuft über SymPy: gratis, deterministisch und nachvollziehbar.
    Drei Fälle, und die Reihenfolge ist wichtig:

    * **Nichts geschrieben** → ``leer``, zählt als falsch. Ohne diese Regel
      bekäme eine komplett leer abgegebene Prüfung eine **6.0**, denn eine
      leere Antwort ist für SymPy schlicht «nicht erkennbar».
    * **Nicht maschinell prüfbar** (kein Prüfausdruck, z.B. «zeichne …») →
      ``unknown``, zählt als richtig: die Note darf nicht an einer Aufgabe
      hängen, welche die App gar nicht bewerten kann.
    * **Sonst** das Urteil von SymPy; bleibt es trotz Antwort ``unknown``
      (z.B. eine Bruch-Antwort), gilt es im Zweifel für das Kind.
    """
    ex = _eigene_pruefung(db, exam_id, user)
    if ex.status == ExamStatus.bewertet:
        raise HTTPException(status.HTTP_409_CONFLICT, "Diese Prüfung ist schon abgegeben.")

    nach_id = {i.id: i for i in ex.items}
    for antwort in payload.antworten:
        item = nach_id.get(antwort.id)
        if item is None:
            continue  # fremde/veraltete ID still ignorieren
        item.student_answer = (antwort.answer or "").strip()[:4000]
        item.image_path = antwort.image_path

    richtig = 0
    for item in ex.items:
        if not item.student_answer and not item.image_path:
            item.verdict = "leer"
            item.judged_by = ""
        elif item.math_expression:
            item.verdict = verify(item.math_expression, item.student_answer).status
            item.judged_by = "sympy"
        else:
            # Nicht maschinell pruefbar (zeichnen, begruenden): nicht bewerten.
            item.verdict = "unknown"
            item.judged_by = ""
        if item.verdict in ("correct", "unknown"):
            richtig += 1

    note = exam_service.note_aus_punkten(richtig, len(ex.items))
    ex.grade_value = note
    ex.status = ExamStatus.bewertet

    thema = db.get(Topic, ex.topic_id)
    db.add(Grade(user_id=user.id, topic_id=ex.topic_id, value=note,
                 taken_on=date.today(),
                 label=f"Probeprüfung {thema.name}" if thema else "Probeprüfung",
                 source="probe", exam_id=ex.id))
    db.commit()
    db.refresh(ex)
    return _to_out(db, ex)


@router.post("/exams/{exam_id}/items/{item_id}/uebernehmen", status_code=201)
def als_uebungsaufgabe(exam_id: int, item_id: int,
                       user: User = Depends(require_student), db: Session = Depends(get_db)):
    """Eine Prüfungsaufgabe als normale Übungsaufgabe ins Thema legen.

    Damit schliesst sich der Kreis: was in der Prüfung nicht sass, wird zur
    Aufgabe, die der Tutor Schritt für Schritt begleitet.
    """
    ex = _eigene_pruefung(db, exam_id, user)
    item = next((i for i in ex.items if i.id == item_id), None)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aufgabe nicht gefunden")
    aufgabe = Exercise(user_id=user.id, topic_id=ex.topic_id, text=item.question,
                       math_expression=item.math_expression or None)
    db.add(aufgabe)
    db.commit()
    db.refresh(aufgabe)
    return {"exercise_id": aufgabe.id}
