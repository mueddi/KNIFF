"""Eltern-Verknuepfung per Einladungscode + Eltern-Dashboard.

Privacy by Design: Eltern-Endpoints lesen ausschliesslich Aggregate
(progress_aggregates) und Anzeige-Daten. Es gibt hier KEINEN Codepfad, der
messages (Transkripte) liest – die Trennung ist strukturell.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from datetime import datetime, timezone

from ..database import get_db
from ..deps import require_parent, require_student
from ..models import ParentLink, Role, User
from ..schemas import ParentChildSummary, ParentLinkOut, ParentRedeem
from ..security import new_invite_code
from ..services import aggregates, quota

router = APIRouter(prefix="/api/parents", tags=["parents"])


def _summary_respecting_share(db: Session, student: User) -> dict:
    """Aggregate nur, wenn der Schueler die Freigabe erteilt hat – sonst genullt.

    Zentral, damit JEDER Eltern-Pfad (redeem wie children) die Freigabe achtet.
    """
    summary = aggregates.build_summary(db, student)
    # Abo-Stand des Kindes: Eltern zahlen, also duerfen sie ihn sehen.
    summary["student_id"] = student.id
    summary["plus"] = quota.quota_state(db, student)
    if not summary["shared"]:
        summary.update({"autonomy_rate": 0, "solved_count": 0, "active_days": 0,
                        "dranbleiben_delta": 0, "top_struggles": [], "daily_activity": [0] * 7,
                        "history": []})
    return summary


# ---------- Schueler-Seite ----------
@router.get("/invite", response_model=ParentLinkOut)
def get_or_create_invite(user: User = Depends(require_student), db: Session = Depends(get_db)):
    """Liefert (oder erzeugt) den Einladungscode, den der Schueler seinen Eltern gibt."""
    link = db.scalar(
        select(ParentLink).where(ParentLink.student_id == user.id, ParentLink.status == "pending")
    )
    if link is None:
        code = new_invite_code()
        while db.scalar(select(ParentLink).where(ParentLink.invite_code == code)):
            code = new_invite_code()
        link = ParentLink(invite_code=code, student_id=user.id, status="pending")
        db.add(link)
        db.commit()
        db.refresh(link)
    return ParentLinkOut(invite_code=link.invite_code, status=link.status)


@router.get("/preview", response_model=ParentChildSummary)
def preview(user: User = Depends(require_student), db: Session = Depends(get_db)):
    """Vorschau fuer den Schueler: genau das, was Eltern spaeter sehen."""
    return ParentChildSummary(**aggregates.build_summary(db, user))


# ---------- Eltern-Seite ----------
@router.post("/redeem", response_model=ParentChildSummary)
def redeem(payload: ParentRedeem, user: User = Depends(require_parent), db: Session = Depends(get_db)):
    code = payload.invite_code.strip().upper()
    link = db.scalar(select(ParentLink).where(ParentLink.invite_code == code))
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Code nicht gefunden.")
    if link.student_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Das ist dein eigener Code.")

    if link.status == "linked":
        # idempotent fuer denselben Parent; fremde Parents duerfen den Code nicht uebernehmen
        if link.parent_id != user.id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Code wurde bereits verwendet – lass dir einen neuen geben.",
            )
    else:
        # bereits anderweitig mit diesem Kind verknuepft? Dann Code nicht verbrauchen.
        existing = db.scalar(
            select(ParentLink).where(
                ParentLink.parent_id == user.id, ParentLink.student_id == link.student_id,
                ParentLink.status == "linked",
            )
        )
        if existing is None:
            link.parent_id = user.id
            link.status = "linked"
            link.linked_at = datetime.now(timezone.utc)
            db.commit()

    student = db.get(User, link.student_id)
    return ParentChildSummary(**_summary_respecting_share(db, student))


@router.get("/children", response_model=list[ParentChildSummary])
def children(user: User = Depends(require_parent), db: Session = Depends(get_db)):
    links = db.scalars(
        select(ParentLink).where(ParentLink.parent_id == user.id, ParentLink.status == "linked")
    ).all()
    out: list[ParentChildSummary] = []
    for link in links:
        student = db.get(User, link.student_id)
        if student is None:
            continue
        out.append(ParentChildSummary(**_summary_respecting_share(db, student)))
    return out

