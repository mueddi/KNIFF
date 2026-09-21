"""Aufgaben-Bibliothek: der Betreiber pflegt Aufgaben, Schueler starten sie im Tutor.

Frueher war das ein PDF-Regal (nie befuellt: 0 Dokumente in der Produktion).
Ein Blatt zum Anschauen bringt in einer Tutor-App nichts – die Aufgabe muss
in den Chat. Deshalb sind Bibliotheks-Eintraege jetzt einzelne Aufgaben als
Text mit Pruefausdruck; «Mit Kniff loesen» legt dem Schueler eine Kopie an
und startet einen Versuch, genau wie bei einer selbst eingetippten Aufgabe.

Fuellen kann der Betreiber auf drei Wegen: einzeln, mehrere auf einmal
(Zeilen aus einer Tabelle) oder per KI-Erzeugung mit Vorschau. Die KI-Kosten
tragen das Betreiber-Konto (Typ «generiert» auf der Kostenseite).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import i18n
from ..config import settings
from ..database import get_db
from ..deps import get_current_user, require_admin, require_student
from ..models import Attempt, Exercise, LibraryExercise, LibraryTopic, User
from ..schemas import (
    AttemptStateOut,
    LibraryExerciseIn,
    LibraryExerciseOut,
    LibraryExerciseUpdate,
    LibraryGeneratedOut,
    LibraryGenerate,
    LibraryImport,
    LibraryTopicCreate,
    LibraryTopicOut,
)
from ..services import quota, usage
from ..services.sympy_verifier import extract_expression

log = logging.getLogger("schrittweise.library")
router = APIRouter(prefix="/api/library", tags=["library"])

DIFFICULTIES = {"leicht", "mittel", "schwer"}
# Dieselben Schluessel wie users.grade_level (frontend/src/lib/i18n.jsx GRADE_KEYS)
GRADES = ("mittelstufe", "oberstufe", "gymnasium")
GRADE_TEXT = {"mittelstufe": "Mittelstufe (4.-6. Klasse, 10-12 Jahre)",
              "oberstufe": "Oberstufe (Sek I, 7.-9. Klasse)",
              "gymnasium": "Gymnasium (bis Matura)"}
LISTE_MAX = 300
# Obergrenze fuer die KI-Erzeugung pro Aufruf (Vorschau, noch nicht gespeichert)
GENERIEREN_MAX_TOKENS = 1800


def klassen_schluessel(grade_level: str | None) -> str:
    """users.grade_level (auch Alt-Werte wie «Gymnasium 1./2.») -> Bibliotheks-Schluessel."""
    g = (grade_level or "").lower()
    if "gym" in g:
        return "gymnasium"
    if "mittel" in g:
        return "mittelstufe"
    return "oberstufe"


def _grades_str(grades: list[str]) -> str:
    """Klassenstufen pruefen und in fester Reihenfolge, ohne Duplikate, verbinden."""
    saubere = {g.strip().lower() for g in grades if g and g.strip()}
    if not saubere or not saubere <= set(GRADES):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Bitte gueltige Klassenstufen angeben (mittelstufe, oberstufe, gymnasium).")
    return ",".join(g for g in GRADES if g in saubere)


def _pruefe_thema(db: Session, category: str) -> str:
    name = (category or "").strip()
    exists = db.scalar(select(LibraryTopic.id).where(LibraryTopic.name == name))
    if exists is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Unbekanntes Thema – leg es zuerst unter «Themen verwalten» an.")
    return name


def _pruefe_schwierigkeit(difficulty: str) -> str:
    if difficulty not in DIFFICULTIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unbekannte Schwierigkeit.")
    return difficulty


def _ausdruck(text: str, angegeben: str | None) -> str | None:
    """Pruefausdruck: der angegebene, sonst aus dem Text gezogen; nur was
    SymPy wirklich zu einer Zahl aufloest – sonst gaelte eine richtige
    Antwort spaeter als falsch."""
    kandidat = (angegeben or "").strip()
    if kandidat:
        geprueft = extract_expression(kandidat)
        if geprueft is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"Der Pruefausdruck «{kandidat}» laesst sich nicht nachrechnen. "
                                "Leer lassen, dann beurteilt der Tutor selbst.")
        return geprueft[:255]
    gefunden = extract_expression(text)
    return gefunden[:255] if gefunden else None


def _neue_aufgabe(db: Session, payload: LibraryExerciseIn) -> LibraryExercise:
    return LibraryExercise(
        text=payload.text.strip(),
        math_expression=_ausdruck(payload.text, payload.math_expression),
        category=_pruefe_thema(db, payload.category),
        grade_levels=_grades_str(payload.grade_levels),
        difficulty=_pruefe_schwierigkeit(payload.difficulty),
        source=payload.source.strip()[:200],
    )


# ---- Themen-Verwaltung (Titel frei benennbar; nur der Betreiber schreibt) ----

@router.get("/topics", response_model=list[LibraryTopicOut])
def list_topics(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    counts = dict(db.execute(
        select(LibraryExercise.category, func.count(LibraryExercise.id))
        .group_by(LibraryExercise.category)).all())
    topics = db.scalars(select(LibraryTopic).order_by(LibraryTopic.name)).all()
    return [LibraryTopicOut(id=t.id, name=t.name, doc_count=counts.get(t.name, 0)) for t in topics]


@router.post("/topics", response_model=LibraryTopicOut, status_code=201)
def create_topic(payload: LibraryTopicCreate, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    name = payload.name.strip()[:120]
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Themen-Titel fehlt.")
    dup = db.scalar(select(LibraryTopic).where(func.lower(LibraryTopic.name) == name.lower()))
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Dieses Thema gibt es schon.")
    topic = LibraryTopic(name=name)
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return LibraryTopicOut(id=topic.id, name=topic.name, doc_count=0)


@router.patch("/topics/{topic_id}", response_model=LibraryTopicOut)
def rename_topic(topic_id: int, payload: LibraryTopicCreate,
                 user: User = Depends(require_admin), db: Session = Depends(get_db)):
    topic = db.get(LibraryTopic, topic_id)
    if topic is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thema nicht gefunden.")
    name = payload.name.strip()[:120]
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Themen-Titel fehlt.")
    dup = db.scalar(select(LibraryTopic).where(func.lower(LibraryTopic.name) == name.lower(),
                                               LibraryTopic.id != topic_id))
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Dieses Thema gibt es schon.")
    old = topic.name
    topic.name = name
    # Aufgaben ziehen mit um (category speichert den Themen-Namen)
    db.execute(update(LibraryExercise).where(LibraryExercise.category == old).values(category=name))
    db.commit()
    count = db.scalar(select(func.count(LibraryExercise.id)).where(LibraryExercise.category == name)) or 0
    return LibraryTopicOut(id=topic.id, name=topic.name, doc_count=count)


@router.delete("/topics/{topic_id}", status_code=204)
def delete_topic(topic_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    topic = db.get(LibraryTopic, topic_id)
    if topic is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thema nicht gefunden.")
    in_use = db.scalar(select(func.count(LibraryExercise.id))
                       .where(LibraryExercise.category == topic.name)) or 0
    if in_use:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Das Thema hat noch {in_use} Aufgabe(n) – verschieb oder loesch sie zuerst.")
    db.delete(topic)
    db.commit()


# ---- Aufgaben lesen (alle Eingeloggten) ----

def _stand_des_schuelers(db: Session, user: User, ids: list[int]) -> dict[int, tuple[str, int]]:
    """Je Bibliotheks-Aufgabe: («offen»|«geloest», juengster Versuch) fuer diesen Nutzer."""
    if not ids:
        return {}
    zeilen = db.execute(
        select(Exercise.library_id, Attempt.id, Attempt.solved)
        .join(Attempt, Attempt.exercise_id == Exercise.id)
        .where(Exercise.user_id == user.id, Exercise.library_id.in_(ids))
        .order_by(Attempt.id)
    ).all()
    stand: dict[int, tuple[str, int]] = {}
    geloest: set[int] = set()
    for lib_id, attempt_id, solved in zeilen:
        if solved:
            geloest.add(lib_id)
        stand[lib_id] = ("geloest" if lib_id in geloest else "offen", attempt_id)
    return stand


@router.get("", response_model=list[LibraryExerciseOut])
def list_exercises(q: str = "", grade: str = "", category: str = "", difficulty: str = "",
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(LibraryExercise)
    if category:
        stmt = stmt.where(LibraryExercise.category == category)
    if difficulty:
        stmt = stmt.where(LibraryExercise.difficulty == difficulty)
    if grade:
        stmt = stmt.where(LibraryExercise.grade_levels.like(f"%{grade.lower()}%"))
    if q.strip():
        stmt = stmt.where(LibraryExercise.text.ilike(f"%{q.strip()}%"))
    stmt = stmt.order_by(LibraryExercise.category, LibraryExercise.difficulty, LibraryExercise.id).limit(LISTE_MAX)
    aufgaben = list(db.scalars(stmt))
    stand = _stand_des_schuelers(db, user, [a.id for a in aufgaben])
    out = []
    for a in aufgaben:
        eintrag = LibraryExerciseOut.model_validate(a)
        if a.id in stand:
            eintrag.status, eintrag.attempt_id = stand[a.id]
        out.append(eintrag)
    return out


# ---- Aufgabe im Tutor starten (Schueler) ----

@router.post("/{aufgabe_id}/start", response_model=AttemptStateOut, status_code=201)
def start_exercise(aufgabe_id: int, user: User = Depends(require_student), db: Session = Depends(get_db)):
    """Kopie der Bibliotheks-Aufgabe beim Schueler anlegen (einmal) und einen
    Versuch starten – derselbe Weg wie bei einer eingetippten Aufgabe."""
    from .exercises import _start_attempt_state

    vorlage = db.get(LibraryExercise, aufgabe_id)
    if vorlage is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            i18n.t(i18n.lang_of(user), "Aufgabe nicht gefunden", "Task not found"))
    if quota.blocked_unverified(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            i18n.t(i18n.lang_of(user), "Bitte bestätige zuerst deine E-Mail-Adresse – schau in dein Postfach.",
                                   "Please confirm your email address first – check your inbox."))
    ex = db.scalar(select(Exercise).where(Exercise.user_id == user.id, Exercise.library_id == vorlage.id)
                   .order_by(Exercise.id.desc()).limit(1))
    if not quota.can_use_ki(db, user, ex.id if ex else None):
        raise quota.sperre(db, user, i18n.lang_of(user), ex.id if ex else None)
    if ex is None:
        ex = Exercise(user_id=user.id, text=vorlage.text, math_expression=vorlage.math_expression,
                      library_id=vorlage.id)
        db.add(ex)
        db.flush()
    return _start_attempt_state(db, ex, user)


# ---- Aufgaben pflegen (nur Betreiber) ----

@router.post("", response_model=LibraryExerciseOut, status_code=201)
def create_exercise(payload: LibraryExerciseIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    aufgabe = _neue_aufgabe(db, payload)
    db.add(aufgabe)
    db.commit()
    db.refresh(aufgabe)
    return aufgabe


@router.post("/import", response_model=list[LibraryExerciseOut], status_code=201)
def import_exercises(payload: LibraryImport, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Mehrere auf einmal – alles oder nichts, damit keine halbe Liste bleibt."""
    neue = []
    for i, eintrag in enumerate(payload.aufgaben, start=1):
        try:
            neue.append(_neue_aufgabe(db, eintrag))
        except HTTPException as exc:
            raise HTTPException(exc.status_code, f"Aufgabe {i}: {exc.detail}")
    db.add_all(neue)
    db.commit()
    for a in neue:
        db.refresh(a)
    return neue


@router.patch("/{aufgabe_id}", response_model=LibraryExerciseOut)
def update_exercise(aufgabe_id: int, payload: LibraryExerciseUpdate,
                    user: User = Depends(require_admin), db: Session = Depends(get_db)):
    aufgabe = db.get(LibraryExercise, aufgabe_id)
    if aufgabe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aufgabe nicht gefunden.")
    if payload.text is not None:
        aufgabe.text = payload.text.strip()
    if payload.text is not None or payload.math_expression is not None:
        # Neuer Text ohne neuen Ausdruck: Ausdruck aus dem neuen Text ziehen –
        # der alte gehoerte zur alten Aufgabe.
        aufgabe.math_expression = _ausdruck(aufgabe.text, payload.math_expression)
    if payload.category is not None:
        aufgabe.category = _pruefe_thema(db, payload.category)
    if payload.grade_levels is not None:
        aufgabe.grade_levels = _grades_str(payload.grade_levels)
    if payload.difficulty is not None:
        aufgabe.difficulty = _pruefe_schwierigkeit(payload.difficulty)
    if payload.source is not None:
        aufgabe.source = payload.source.strip()[:200]
    db.commit()
    db.refresh(aufgabe)
    return aufgabe


@router.delete("/{aufgabe_id}", status_code=204)
def delete_exercise(aufgabe_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    aufgabe = db.get(LibraryExercise, aufgabe_id)
    if aufgabe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aufgabe nicht gefunden.")
    db.delete(aufgabe)
    db.commit()


# ---- KI-Erzeugung mit Vorschau (nur Betreiber) ----

def _generier_prompt(thema: str, stufe: str, difficulty: str, lernziel: str, anzahl: int) -> str:
    return (
        "Du erstellst Uebungsaufgaben fuer eine Mathe-Lern-App fuer Schweizer "
        f"Schueler:innen. Klassenstufe: {GRADE_TEXT.get(stufe, stufe)}. "
        f"Schwierigkeit: {difficulty}. Lehrplan 21.\n\n"
        f"THEMA: {thema}\nWAS GEUEBT WERDEN SOLL: {lernziel}\n\n"
        f"Erzeuge genau {anzahl} verschiedene Aufgaben, jede eigenstaendig loesbar, "
        "mit Alltagsbezug wo es passt (Franken, Rappen, Meter). Schweizer "
        "Rechtschreibung: «ss» statt «ß». Gib NUR ein JSON-Array zurueck, ohne "
        'Text davor oder danach. Jedes Element: {"frage": "...", "ausdruck": "..."}\n'
        "- «frage»: die Aufgabenstellung, wie sie auf einem Uebungsblatt steht. "
        "Kurz und eindeutig. Keine Loesung, kein Hinweis.\n"
        "- «ausdruck»: dieselbe Aufgabe in EINER maschinell loesbaren Zeile, z.B. "
        '"3x + 5 = 20" oder "0.25 * 240". Nur eine Unbekannte, und sie muss zu '
        'einer ZAHL aufloesen. Ist das nicht moeglich (Zeichnen, Begruenden), dann "".\n'
    )


@router.post("/generieren", response_model=LibraryGeneratedOut)
def generate_exercises(payload: LibraryGenerate, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Vorschau erzeugen – gespeichert wird erst, was der Betreiber nach dem
    Durchlesen per /import uebernimmt. Kosten landen auf dem Betreiber-Konto."""
    from ..services.exam import _saeubere

    thema = _pruefe_thema(db, payload.category)
    stufe = klassen_schluessel(payload.grade_level)
    schwierigkeit = _pruefe_schwierigkeit(payload.difficulty)
    if not settings.anthropic_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Die KI ist nicht konfiguriert.")

    import anthropic

    model = settings.anthropic_model_default
    try:
        resp = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=1).messages.create(
            model=model, max_tokens=GENERIEREN_MAX_TOKENS,
            messages=[{"role": "user", "content": _generier_prompt(
                thema, stufe, schwierigkeit, payload.lernziel.strip(), payload.anzahl)}])
        roh = "".join(b.text for b in resp.content if b.type == "text")
        aufgaben = _saeubere(roh)
    except Exception as exc:
        log.exception("Bibliotheks-Erzeugung fehlgeschlagen")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            f"Die KI hat keine brauchbaren Aufgaben geliefert ({type(exc).__name__}). Nochmal versuchen.")
    kosten = usage.cost_usd(model, resp.usage)
    usage.record(db, "generiert", model, resp.usage, user_id=user.id)
    db.commit()
    return LibraryGeneratedOut(
        aufgaben=[LibraryExerciseIn(text=a["frage"], math_expression=a["math_expression"] or None,
                                    category=thema, grade_levels=[stufe], difficulty=schwierigkeit,
                                    source="KI-erzeugt")
                  for a in aufgaben[:payload.anzahl]],
        kosten_rappen=round(kosten * settings.usd_chf_rate * 100, 2),
    )
