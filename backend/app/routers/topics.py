"""Themen-CRUD (manuelle Container) + grober Fortschritt pro Thema."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_student
from ..models import Attempt, Exam, ExamItem, Exercise, Grade, Topic, User
from ..schemas import ExerciseListItem, TopicCreate, TopicOut, TopicUpdate

router = APIRouter(prefix="/api/topics", tags=["topics"])


def _progress(pct: int, has_exercises: bool) -> str:
    if not has_exercises:
        return "Neu"
    if pct >= 90:
        return "Sitzt"
    if pct >= 45:
        return "Wird besser"
    return "Noch üben"


def _to_out(db: Session, topic: Topic) -> TopicOut:
    ex_count = db.scalar(select(func.count(Exercise.id)).where(Exercise.topic_id == topic.id)) or 0
    # geloeste Aufgaben = Aufgaben mit mind. einem geloesten Attempt
    solved = db.scalar(
        select(func.count(func.distinct(Attempt.exercise_id)))
        .select_from(Attempt).join(Exercise, Attempt.exercise_id == Exercise.id)
        .where(Exercise.topic_id == topic.id, Attempt.solved.is_(True))
    ) or 0
    pct = int(round(solved / ex_count * 100)) if ex_count else 0
    out = TopicOut.model_validate(topic)
    out.exercise_count = ex_count
    out.solved_count = solved
    out.progress_pct = pct
    out.progress_label = _progress(pct, ex_count > 0)
    # Noten des Themas: der Schnitt ist die Zahl, nach der Eltern zuerst schauen
    noten = list(db.scalars(select(Grade.value).where(Grade.topic_id == topic.id)))
    out.grade_count = len(noten)
    out.grade_avg = round(sum(noten) / len(noten), 2) if noten else None
    return out


@router.get("", response_model=list[TopicOut])
def list_topics(archiviert: bool = Query(default=False),
                user: User = Depends(require_student), db: Session = Depends(get_db)):
    """Standardmaessig nur AKTIVE Themen.

    Archivierte gehoeren nicht in die Seitenleiste und nicht ins Raster – sonst
    waere Archivieren wirkungslos. Mit ``?archiviert=true`` kommt das Archiv.
    """
    q = select(Topic).where(Topic.user_id == user.id)
    q = q.where(Topic.archived_at.is_not(None) if archiviert else Topic.archived_at.is_(None))
    topics = db.scalars(q.order_by(Topic.created_at)).all()
    return [_to_out(db, t) for t in topics]


@router.post("", response_model=TopicOut, status_code=201)
def create_topic(payload: TopicCreate, user: User = Depends(require_student), db: Session = Depends(get_db)):
    topic = Topic(user_id=user.id, name=payload.name.strip(), category=payload.category, color=payload.color)
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return _to_out(db, topic)


@router.patch("/{topic_id}", response_model=TopicOut)
def update_topic(topic_id: int, payload: TopicUpdate, user: User = Depends(require_student), db: Session = Depends(get_db)):
    topic = db.get(Topic, topic_id)
    if topic is None or topic.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thema nicht gefunden")
    # exclude_none: ein mitgeschicktes null darf keine NOT-NULL-Spalte leeren
    # (sonst IntegrityError -> 500), genau wie beim Profil in auth.py.
    for field, value in payload.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(topic, field, value)
    db.commit()
    db.refresh(topic)
    return _to_out(db, topic)


@router.get("/{topic_id}/exercises", response_model=list[ExerciseListItem])
def topic_exercises(topic_id: int, user: User = Depends(require_student), db: Session = Depends(get_db)):
    topic = db.get(Topic, topic_id)
    if topic is None or topic.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thema nicht gefunden")
    exercises = db.scalars(
        select(Exercise).where(Exercise.topic_id == topic.id).order_by(Exercise.created_at.desc())
    ).all()
    items: list[ExerciseListItem] = []
    for ex in exercises:
        last = db.scalar(
            select(Attempt).where(Attempt.exercise_id == ex.id).order_by(Attempt.id.desc()).limit(1)
        )
        # «geloest», sobald IRGENDein Attempt geloest wurde – konsistent mit dem
        # Themen-Zaehler (_to_out zaehlt Aufgaben mit mind. einem geloesten Attempt).
        ever_solved = db.scalar(
            select(func.count(Attempt.id)).where(Attempt.exercise_id == ex.id, Attempt.solved.is_(True))
        ) or 0
        item = ExerciseListItem.model_validate(ex)
        item.latest_attempt_id = last.id if last else None
        item.solved = ever_solved > 0
        items.append(item)
    return items


def _eigenes(db: Session, topic_id: int, user: User) -> Topic:
    topic = db.get(Topic, topic_id)
    if topic is None or topic.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thema nicht gefunden")
    return topic


@router.post("/{topic_id}/archivieren", response_model=TopicOut)
def archive_topic(topic_id: int, user: User = Depends(require_student),
                  db: Session = Depends(get_db)):
    """Thema aus dem Weg raeumen, ohne etwas zu verlieren.

    Der Normalfall fuer ein abgeschlossenes Thema: Aufgaben, Verlauf und
    besonders die NOTEN bleiben unangetastet und jederzeit einsehbar.
    """
    topic = _eigenes(db, topic_id, user)
    if topic.archived_at is None:
        topic.archived_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(topic)
    return _to_out(db, topic)


@router.post("/{topic_id}/wiederherstellen", response_model=TopicOut)
def unarchive_topic(topic_id: int, user: User = Depends(require_student),
                    db: Session = Depends(get_db)):
    topic = _eigenes(db, topic_id, user)
    topic.archived_at = None
    db.commit()
    db.refresh(topic)
    return _to_out(db, topic)


@router.delete("/{topic_id}", status_code=204)
def delete_topic(topic_id: int, trotzdem: bool = Query(default=False),
                 user: User = Depends(require_student), db: Session = Depends(get_db)):
    """Thema wirklich loeschen.

    Haengen Noten daran, wird zuerst abgelehnt (409) und auf Archivieren
    verwiesen: eine Notenhistorie ist nicht wiederherstellbar, ein Klick aus
    Versehen soll sie nicht vernichten. Mit ``?trotzdem=true`` loescht es
    wirklich – die Noten bleiben aber erhalten und verlieren nur das Thema.
    """
    topic = _eigenes(db, topic_id, user)
    noten = db.scalars(select(Grade).where(Grade.topic_id == topic.id)).all()
    if noten and not trotzdem:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"An diesem Thema hängen {len(noten)} Noten. Archiviere es besser – "
            "dann bleibt der Verlauf erhalten.")
    # Aufgaben nicht loeschen, nur Zuordnung entfernen
    for ex in db.scalars(select(Exercise).where(Exercise.topic_id == topic.id)):
        ex.topic_id = None
    # Noten ebenfalls NICHT loeschen: die Note gehoert dem Kind, nicht dem Thema
    for note in noten:
        note.topic_id = None
    # Probepruefungen haengen fest am Thema (NOT NULL) – sie gehen mit; ihre
    # Note ist oben schon vom Thema geloest und bleibt im Verlauf.
    exam_ids = select(Exam.id).where(Exam.topic_id == topic.id)
    db.execute(update(Grade).where(Grade.exam_id.in_(exam_ids)).values(exam_id=None))
    db.execute(delete(ExamItem).where(ExamItem.exam_id.in_(exam_ids)))
    db.execute(delete(Exam).where(Exam.topic_id == topic.id))
    db.delete(topic)
    db.commit()
