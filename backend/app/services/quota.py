"""Kontingent-Logik: wer darf gerade eine KI-Leistung ausloesen, und wer zahlt?

Mit Kniff Plus (settings.abo_enabled) gilt die Reihenfolge

    school    Betreiber- und Schul-Konten: nie eine Abbuchung
    plus      Abo aktiv (abo_bis liegt in der Zukunft); stille Fair-Use-Grenze
              pro Monat (plus_monatslimit_tokens)
    trial     die ersten trial_tasks AUFGABEN sind gratis - einmalig, nicht
              monatlich; weitere Runden und Wiederholungen dieser Aufgaben
              bleiben frei
    guthaben  altes Token-Guthaben (Einmal-Pakete) wird weiter abgebucht
    gesperrt  nichts davon

Ohne den Schalter verhaelt sich alles wie bisher: 50 Gratis-Tokens im Monat
(stufe "gratis"), danach das Guthaben. 1 Token = 1 Rappen verrechnete
KI-Leistung; abgebucht wird nach echten Kosten mal Sicherheitsmarge
(services/usage.charged_tokens). Der Monatszaehler free_used_tokens/free_month
zaehlt mit Plus den GESAMTEN Verbrauch (Fair-Use), nicht nur den Gratis-Anteil.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from .. import i18n
from ..config import settings
from ..models import Attempt, Plan, User
from .timezone import LOCAL_TZ


def current_month() -> str:
    """Monats-Marke nach lokaler Zeit (Europe/Zurich), z.B. "2026-07"."""
    return datetime.now(LOCAL_TZ).strftime("%Y-%m")


def _utcnow_naiv() -> datetime:
    # Die Datenbank speichert naive UTC-Zeiten (models._now) - gleich vergleichen.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def is_unlimited(user: User) -> bool:
    # Betreiber-Konto (Admin) und Schul-Plan zahlen nie: unbegrenzte Aufgaben.
    return user.is_admin or user.plan == Plan.school


def plus_aktiv(user: User) -> bool:
    return user.abo_bis is not None and user.abo_bis > _utcnow_naiv()


def _effective_free_used(user: User) -> int:
    """Monatsverbrauch in Tokens (rein lesend, ohne Rollover-Write)."""
    if user.free_month != current_month():
        return 0
    return user.free_used_tokens or 0


def _probe_aufgaben(db: Session, user_id: int) -> list[int]:
    """IDs der Aufgaben, die dieses Konto je begonnen hat - in der Reihenfolge
    des ersten Versuchs. Die ersten trial_tasks davon sind die Probe."""
    erster = func.min(Attempt.id).label("erster")
    rows = db.execute(
        select(Attempt.exercise_id, erster)
        .where(Attempt.user_id == user_id)
        .group_by(Attempt.exercise_id)
        .order_by(erster)
    ).all()
    return [r[0] for r in rows]


def trial_used(db: Session, user: User) -> int:
    return min(len(_probe_aufgaben(db, user.id)), settings.trial_tasks)


def trial_deckt(db: Session, user: User, exercise_id: int | None = None) -> bool:
    """Ist diese Leistung durch die Probe gedeckt?

    exercise_id=None heisst «eine neue Aufgabe beginnt» (Foto, Eingabe,
    Variante, Pruefung). Eine schon begonnene Aufgabe bleibt gedeckt, wenn
    sie zu den ersten trial_tasks gehoert - egal wie viele Runden."""
    ids = _probe_aufgaben(db, user.id)
    if exercise_id is not None and exercise_id in ids:
        return ids.index(exercise_id) < settings.trial_tasks
    return len(ids) < settings.trial_tasks


def stufe(db: Session, user: User, exercise_id: int | None = None) -> str:
    if is_unlimited(user):
        return "school"
    if settings.abo_enabled:
        if plus_aktiv(user):
            return "plus"
        if trial_deckt(db, user, exercise_id):
            return "trial"
    elif _effective_free_used(user) < settings.free_monthly_tokens:
        return "gratis"
    if user.token_balance > 0:
        return "guthaben"
    return "gesperrt"


def can_use_ki(db: Session, user: User, exercise_id: int | None = None) -> bool:
    """Darf dieses Konto gerade eine KI-Leistung ausloesen? (rein lesend)"""
    s = stufe(db, user, exercise_id)
    if s == "plus":
        return _effective_free_used(user) < settings.plus_monatslimit_tokens
    return s != "gesperrt"


def sperr_grund(db: Session, user: User, exercise_id: int | None = None) -> str:
    """Warum ist es gerade gesperrt? "fairuse" | "trial" | "guthaben" """
    if stufe(db, user, exercise_id) == "plus":
        return "fairuse"
    if settings.abo_enabled:
        return "trial"
    return "guthaben"


def sperre(db: Session, user: User, lang: str, exercise_id: int | None = None) -> HTTPException:
    """Die 402-Antwort mit passendem Text; der Grund steht im Header
    X-Kniff-Grund, damit die Oberflaeche die richtige Karte zeigt."""
    grund = sperr_grund(db, user, exercise_id)
    if grund == "fairuse":
        text = i18n.t(lang,
                      "Wow – du hast diesen Monat riesig viel geübt! Ab dem 1. geht es weiter.",
                      "Wow – you practised a huge amount this month! It continues on the 1st.")
    elif grund == "trial":
        text = i18n.t(lang,
                      f"Deine {settings.trial_tasks} Probe-Aufgaben sind aufgebraucht. Mit {settings.plus_name} übst du weiter – so viel du willst.",
                      f"Your {settings.trial_tasks} free tasks are used up. With {settings.plus_name} you can keep practising – as much as you like.")
    else:
        text = i18n.t(lang,
                      "Dein Guthaben ist aufgebraucht. Lad Tokens oder warte auf den nächsten Monat.",
                      "Your balance is used up. Top up tokens or wait for next month.")
    return HTTPException(status.HTTP_402_PAYMENT_REQUIRED, text, headers={"X-Kniff-Grund": grund})


def quota_state(db: Session, user: User) -> dict:
    free_total = settings.free_monthly_tokens
    free_used = _effective_free_used(user)
    free_left = max(free_total - free_used, 0)
    s = stufe(db, user)
    t_used = trial_used(db, user)
    t_left = max(settings.trial_tasks - t_used, 0)
    if s == "school":
        remaining, percent = 10**9, 0
    elif s == "plus":
        remaining = 10**9
        percent = min(int(round(free_used / settings.plus_monatslimit_tokens * 100)), 100)
    elif s == "trial":
        remaining = t_left
        percent = min(int(round(t_used / settings.trial_tasks * 100)), 100) if settings.trial_tasks else 100
    elif s == "gratis":
        remaining = free_left + user.token_balance
        percent = min(int(round(free_used / free_total * 100)), 100) if free_total else 100
    elif s == "guthaben":
        remaining = user.token_balance
        percent = 100 if settings.abo_enabled else min(int(round(free_used / free_total * 100)), 100) if free_total else 100
    else:
        remaining, percent = 0, 100
    return {
        "plan": user.plan.value,
        "monthly_free_tokens": free_total,
        "free_used_tokens": free_used,
        "free_left": free_left,
        "token_balance": user.token_balance,
        "remaining": remaining,
        "percent_used": percent,
        "unlimited": is_unlimited(user),
        "stufe": s,
        "abo_enabled": settings.abo_enabled,
        "plus_name": settings.plus_name,
        "preise": {"monat": settings.plus_preis_monat_rappen, "jahr": settings.plus_preis_jahr_rappen},
        "trial_tasks": settings.trial_tasks,
        "trial_used": t_used,
        "trial_left": t_left,
        "monat_verbraucht": free_used,
        "plus_limit": settings.plus_monatslimit_tokens,
        "abo_bis": user.abo_bis.isoformat() if user.abo_bis else None,
        "abo_gekuendigt": bool(user.abo_gekuendigt),
        "abo_intervall": user.abo_intervall,
    }


def blocked_unverified(user: User) -> bool:
    """E-Mail-Bestaetigung noetig, bevor KI/Kauf moeglich sind (falls erzwungen).

    Nur aktiv, wenn REQUIRE_EMAIL_VERIFICATION gesetzt ist – das darf erst
    passieren, wenn der Mailversand nachweislich funktioniert."""
    return (settings.require_email_verification
            and not is_unlimited(user)
            and not user.email_verified)


def charge(db: Session, user_id: int, tokens: int, vom_guthaben: bool = True) -> None:
    """Bucht ``tokens`` ab.

    Mit Kniff Plus: der Monatszaehler steigt immer (Fair-Use), das Guthaben
    wird nur bei vom_guthaben abgebucht (Stufe "guthaben"). Ohne Schalter:
    erst Gratis-Kontingent, Rest vom Guthaben.

    Alles in bedingten UPDATEs (alle Ausdruecke lesen die alten Zeilenwerte)
    – kein Doppel-Spend-Fenster bei parallelen Requests, laeuft auf SQLite
    und Postgres. Guthaben faellt nie unter 0; wer mit dem letzten Token eine
    teure Antwort ausloest, bekommt sie noch (bewusst begrenzte Kulanz).
    Kein Commit hier – der Aufrufer committet zusammen mit seinen eigenen
    Daten (Tutor-Message + ApiUsage-Zeile).
    """
    if tokens <= 0:
        return
    cur = current_month()
    # (A) Idempotenter Monats-Rollover: der Verlierer paralleler Rollovers
    # trifft schlicht keine Zeile mehr.
    db.execute(
        update(User)
        .where(User.id == user_id)
        .where((User.free_month.is_(None)) | (User.free_month != cur))
        .values(free_used_tokens=0, free_month=cur)
    )
    guthaben_neu = case(
        (User.token_balance - tokens > 0, User.token_balance - tokens),
        else_=0,
    )
    if settings.abo_enabled:
        db.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                free_used_tokens=User.free_used_tokens + tokens,
                token_balance=guthaben_neu if vom_guthaben else User.token_balance,
            )
        )
        return
    # (B) Atomarer Split: Gratis-Anteil zuerst, Rest vom Guthaben (Boden 0).
    free_total = settings.free_monthly_tokens
    free_left = free_total - User.free_used_tokens
    free_part = case(
        (free_left >= tokens, tokens),
        (free_left > 0, free_left),
        else_=0,
    )
    rest = tokens - free_part
    db.execute(
        update(User)
        .where(User.id == user_id)
        .values(
            free_used_tokens=User.free_used_tokens + free_part,
            token_balance=case(
                (User.token_balance - rest > 0, User.token_balance - rest),
                else_=0,
            ),
        )
    )
