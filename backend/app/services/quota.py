"""Kontingent-Logik: wer darf gerade eine KI-Leistung ausloesen, und wer zahlt?

Mit Kniff Plus (settings.abo_enabled) gilt die Reihenfolge

    school    Betreiber- und Schul-Konten: nie eine Abbuchung
    plus      Abo aktiv (abo_bis liegt in der Zukunft). Jeder Abo-Monat bringt
              frische plus_tokens_monat Abo-Tokens (abo_tokens); was davon
              uebrig bleibt, verfaellt mit dem Monat - auch beim Jahresabo,
              Monat fuer Monat. Abgebucht wird zuerst vom Abo, dann vom
              gekauften Guthaben (token_balance, Token-Pakete, verfaellt nie).
              Sind beide leer, ist zu - Nachschub gibt es als Paket (nur mit
              Abo) oder mit dem naechsten Abo-Monat.
    trial     die ersten trial_tasks AUFGABEN sind gratis - einmalig, nicht
              monatlich; weitere Runden und Wiederholungen dieser Aufgaben
              bleiben frei
    guthaben  Token-Guthaben ohne Abo (alte Einmal-Pakete) wird weiter abgebucht
    gesperrt  nichts davon

Ohne den Schalter verhaelt sich alles wie bisher: 50 Gratis-Tokens im Monat
(stufe "gratis"), danach das Guthaben. 1 Token = 1 Rappen verrechnete
KI-Leistung; abgebucht wird nach echten Kosten mal Sicherheitsmarge
(services/usage.charged_tokens). Der Monatszaehler free_used_tokens/free_month
zaehlt mit Plus den GESAMTEN Verbrauch (Anzeige), nicht nur den Gratis-Anteil.
"""
from __future__ import annotations

import calendar
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from .. import i18n
from ..config import settings
from ..models import Attempt, Plan, User
from .timezone import LOCAL_TZ

# Nachkauf-Pakete fuer Abonnenten. 1 Token = 1 Rappen - Paketmenge = Preis in
# Rappen. Landet im gekauften Guthaben (token_balance) und verfaellt nie.
PAKETE = {
    "schnupper": {"tokens": 200, "rappen": 200, "name": "Kniff Schnupper-Paket – 200 Tokens"},
    "starter": {"tokens": 900, "rappen": 900, "name": "Kniff Starter-Paket – 900 Tokens"},
    "power": {"tokens": 1900, "rappen": 1900, "name": "Kniff Power-Paket – 1900 Tokens"},
}


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


def _monate_zurueck(dt: datetime, k: int) -> datetime:
    """dt um k Kalendermonate zurueck; der Tag wird aufs Monatsende gekappt
    (31. Maerz -> 28. Februar), wie Stripe es bei Abrechnungstagen tut."""
    m = dt.month - 1 - k
    jahr, monat = dt.year + m // 12, m % 12 + 1
    return dt.replace(year=jahr, month=monat, day=min(dt.day, calendar.monthrange(jahr, monat)[1]))


def abo_monat(user: User) -> tuple[datetime, datetime] | None:
    """Der laufende Abo-Monat [Start, Ende) - None ohne aktives Abo.

    Rueckwaerts vom Abo-Ende in ganzen Monaten gezaehlt: beim Monatsabo ist
    das genau die bezahlte Periode, beim Jahresabo einer seiner zwoelf
    Monate. Verlaengert eine Rechnung das Abo, beginnt so von selbst der
    naechste Monat - ohne dass dafuer ein Webhook Tokens buchen muss."""
    if not plus_aktiv(user):
        return None
    jetzt = _utcnow_naiv()
    k = 1
    while _monate_zurueck(user.abo_bis, k) > jetzt and k < 400:
        k += 1
    return _monate_zurueck(user.abo_bis, k), _monate_zurueck(user.abo_bis, k - 1)


def _marke(start: datetime) -> str:
    return start.strftime("%Y-%m-%dT%H:%M")


def abo_tokens(user: User) -> int:
    """Abo-Tokens, die gerade zur Verfuegung stehen (rein lesend): in einem
    neuen Abo-Monat die volle Monatsmenge, sonst der Rest dieses Monats."""
    monat = abo_monat(user)
    if monat is None:
        return 0
    if user.abo_periode != _marke(monat[0]):
        return settings.plus_tokens_monat
    return max(user.abo_tokens or 0, 0)


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
        return abo_tokens(user) + user.token_balance > 0
    return s != "gesperrt"


def sperr_grund(db: Session, user: User, exercise_id: int | None = None) -> str:
    """Warum ist es gerade gesperrt? "plus_leer" | "trial" | "guthaben" """
    if stufe(db, user, exercise_id) == "plus":
        return "plus_leer"
    if settings.abo_enabled:
        return "trial"
    return "guthaben"


def sperre(db: Session, user: User, lang: str, exercise_id: int | None = None) -> HTTPException:
    """Die 402-Antwort mit passendem Text; der Grund steht im Header
    X-Kniff-Grund, damit die Oberflaeche die richtige Karte zeigt."""
    grund = sperr_grund(db, user, exercise_id)
    if grund == "plus_leer":
        text = i18n.t(lang,
                      "Deine Tokens sind aufgebraucht. Lad ein Token-Paket nach – oder warte auf den nächsten Abo-Monat.",
                      "Your tokens are used up. Top up a token package – or wait for your next subscription month.")
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
    abo = abo_tokens(user)
    monat_neu = abo_monat(user)
    if s == "school":
        remaining, percent = 10**9, 0
    elif s == "plus":
        # Anzeige: wie viel von einer Monatsmenge ist noch da (Abo + gekauft)?
        # Mehr als eine (nachgekauft) zaehlt als «voll».
        remaining = abo + user.token_balance
        monat = settings.plus_tokens_monat
        percent = 0 if not monat or remaining >= monat else min(int(round((1 - remaining / monat) * 100)), 100)
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
        "plus_tokens_monat": settings.plus_tokens_monat,
        "pakete": [{"key": k, "tokens": p["tokens"], "rappen": p["rappen"]} for k, p in PAKETE.items()],
        "abo_bis": user.abo_bis.isoformat() if user.abo_bis else None,
        "abo_gekuendigt": bool(user.abo_gekuendigt),
        "abo_intervall": user.abo_intervall,
        # Zwei Toepfe: Abo-Tokens verfallen am Ende des Abo-Monats, gekaufte
        # (token_balance) nie. abo_neu = wann der naechste Abo-Monat beginnt.
        "abo_tokens": abo,
        "abo_neu": monat_neu[1].isoformat() if monat_neu else None,
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

    Mit Kniff Plus: der Monatszaehler steigt immer (Anzeige), abgebucht wird
    nur bei vom_guthaben (Stufen "plus" und "guthaben"; die Probe ist
    gratis) - mit aktivem Abo zuerst von den Abo-Tokens, dann vom gekauften
    Guthaben. Ohne Schalter: erst Gratis-Kontingent, Rest vom Guthaben.

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
    if settings.abo_enabled:
        user = db.get(User, user_id)
        monat = abo_monat(user) if (user is not None and vom_guthaben) else None
        if monat is not None:
            # (A') Neuer Abo-Monat: frische Monatsmenge, der Rest verfaellt.
            # Idempotent wie (A) - nur die erste Buchung des Monats trifft.
            marke = _marke(monat[0])
            db.execute(
                update(User)
                .where(User.id == user_id)
                .where((User.abo_periode.is_(None)) | (User.abo_periode != marke))
                .values(abo_tokens=settings.plus_tokens_monat, abo_periode=marke)
            )
        # (B') Zuerst vom Abo, der Rest vom gekauften Guthaben (Boden je 0).
        abo_teil = case(
            (User.abo_tokens >= tokens, tokens),
            (User.abo_tokens > 0, User.abo_tokens),
            else_=0,
        ) if monat is not None else 0
        rest = tokens - abo_teil
        werte = {"free_used_tokens": User.free_used_tokens + tokens}
        if monat is not None:
            werte["abo_tokens"] = case((User.abo_tokens - tokens > 0, User.abo_tokens - tokens), else_=0)
        if vom_guthaben:
            werte["token_balance"] = case((User.token_balance - rest > 0, User.token_balance - rest), else_=0)
        db.execute(update(User).where(User.id == user_id).values(**werte))
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
