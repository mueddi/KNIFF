"""Admin-Bereich: KI-Kosten-Auswertung + Nutzer-/Guthaben-Verwaltung
(nur Betreiber-Konto).

Kosten: aggregiert die ApiUsage-Zeilen zu den Zahlen, die der Betreiber zum
Optimieren braucht: Ø/Min/Max-Kosten pro Aufgabe, Aufschluesselung nach
Aufruf-Typ und Modell, Gesamtkosten im Zeitfenster. Anthropic rechnet in
USD ab; die Anzeige rechnet mit ``usd_chf_rate`` in CHF/Rappen um.
Nutzer: Suche + manuelle Token-Gutschrift/-Korrektur (Support-Werkzeug),
jede Buchung protokolliert (TokenAdjustment).
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import require_admin
from ..models import ApiUsage, Plan, TokenAdjustment, User
from ..schemas import TokenAdjustRequest
from ..services import quota as quota_service

router = APIRouter(prefix="/api/admin", tags=["admin"])
log = logging.getLogger("schrittweise.admin")

KIND_LABEL = {
    "chat": "Tutor-Chat",
    "ocr": "Erkennung (Foto/Stift)",
    "suche": "KI-Suche Bibliothek",
    "variante": "Übungs-Variante",
    "generiert": "Aufgabe erstellt",
    "pruefung": "Probeprüfung",
}

# Wie viele der teuersten Aufgaben die Auswertung nennt.
TEUERSTE_AUFGABEN = 8
# Ab welchem Anteil ein einzelner Posten (Typ, Konto) einen Hinweis bekommt.
HINWEIS_ANTEIL = 0.30
# Unter dieser Cache-Quote (Anteil der Eingabe aus dem Cache) zahlt ein
# Modell den Vorlauf praktisch jedes Mal neu.
CACHE_QUOTE_SCHWACH = 0.40


def _chf(usd: float) -> float:
    return round(usd * settings.usd_chf_rate, 4)


def _rappen(usd: float) -> float:
    return round(usd * settings.usd_chf_rate * 100, 2)


def _anteile_chf(anteile_usd: dict[str, float]) -> dict[str, float]:
    return {k + "_chf": _chf(v) for k, v in anteile_usd.items()}


def _summe_anteile(ziel: dict[str, float], neu: dict[str, float]) -> None:
    for k, v in neu.items():
        ziel[k] = ziel.get(k, 0.0) + v


@router.get("/kosten")
def kosten(tage: int = Query(30, ge=1, le=365),
           user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Woher die KI-Kosten kommen – nicht nur wie hoch sie sind.

    Die Zahlen entstehen alle aus den api_usage-Zeilen im Zeitfenster. Die
    Aufschluesselung in Eingabe / Cache gelesen / Cache geschrieben /
    Ausgabe rechnet dieselbe Funktion wie die Erfassung (kosten_anteile),
    damit Summe und Bestandteile nie auseinanderlaufen.
    """
    from .. import i18n
    from ..models import Exercise
    from ..services.usage import CACHE_READ_FACTOR, CACHE_WRITE_1H_FACTOR, CACHE_WRITE_FACTOR, _rates, kosten_anteile

    lang = i18n.lang_of(user)
    since = datetime.now(timezone.utc) - timedelta(days=tage)
    im_fenster = ApiUsage.created_at >= since

    # ---- Grundlage: Summen je (Typ, Modell) – daraus folgt fast alles ----
    zeilen = db.execute(
        select(ApiUsage.kind, ApiUsage.model, func.count(),
               func.sum(ApiUsage.input_tokens), func.sum(ApiUsage.output_tokens),
               func.sum(ApiUsage.cache_read_tokens), func.sum(ApiUsage.cache_write_tokens),
               func.sum(ApiUsage.cache_write_1h_tokens), func.sum(ApiUsage.cost_usd),
               func.sum(ApiUsage.charged_tokens),
               func.sum(case((ApiUsage.charged_tokens > 0, ApiUsage.cost_usd), else_=0.0)),
               func.sum(case((ApiUsage.charged_tokens > 0, 1), else_=0)))
        .where(im_fenster)
        .group_by(ApiUsage.kind, ApiUsage.model)
    ).all()

    typen: dict[str, dict] = {}
    modelle: dict[str, dict] = {}
    anteile_gesamt: dict[str, float] = {}
    gesamt_usd = 0.0
    gesamt_aufrufe = 0
    gesamt_verrechnet = 0
    verrechnet_usd = 0.0
    verrechnete_aufrufe = 0
    cache = {"lesen": 0, "schreiben": 0, "schreiben_1h": 0, "eingabe": 0,
             "brutto_usd": 0.0, "mehrkosten_usd": 0.0}

    for kind, model, calls, in_t, out_t, cr, cw, cw1h, usd, charged, usd_verr, n_verr in zeilen:
        in_t, out_t, cr, cw, cw1h = (int(x or 0) for x in (in_t, out_t, cr, cw, cw1h))
        cw1h = min(cw1h, cw)
        usd = float(usd or 0.0)
        anteile = kosten_anteile(model or "", in_t, out_t, cr, cw - cw1h, cw1h)
        in_rate, _ = _rates(model or "")

        t = typen.setdefault(kind, {"aufrufe": 0, "input_tokens": 0, "output_tokens": 0,
                                    "cache_read_tokens": 0, "cache_write_tokens": 0,
                                    "usd": 0.0, "verrechnet": 0, "anteile": {}, "modelle": set()})
        t["aufrufe"] += calls
        t["input_tokens"] += in_t
        t["output_tokens"] += out_t
        t["cache_read_tokens"] += cr
        t["cache_write_tokens"] += cw
        t["usd"] += usd
        t["verrechnet"] += int(charged or 0)
        t["modelle"].add(model)
        _summe_anteile(t["anteile"], anteile)

        m = modelle.setdefault(model, {"aufrufe": 0, "usd": 0.0, "input_tokens": 0,
                                       "output_tokens": 0, "cache_read_tokens": 0,
                                       "cache_write_tokens": 0, "anteile": {},
                                       "netto_usd": 0.0})
        m["aufrufe"] += calls
        m["usd"] += usd
        m["input_tokens"] += in_t
        m["output_tokens"] += out_t
        m["cache_read_tokens"] += cr
        m["cache_write_tokens"] += cw
        _summe_anteile(m["anteile"], anteile)
        # Was der Cache netto bringt: gelesene Tokens haetten sonst den
        # vollen Eingabepreis gekostet (Ersparnis 0.9x) – geschriebene kosten
        # einen Aufschlag (0.25x bei 5 Minuten, 1.0x bei 1 Stunde).
        brutto = cr * in_rate * (1 - CACHE_READ_FACTOR) / 1_000_000
        mehr = ((cw - cw1h) * (CACHE_WRITE_FACTOR - 1) + cw1h * (CACHE_WRITE_1H_FACTOR - 1)) * in_rate / 1_000_000
        m["netto_usd"] += brutto - mehr
        cache["brutto_usd"] += brutto
        cache["mehrkosten_usd"] += mehr
        cache["lesen"] += cr
        cache["schreiben"] += cw
        cache["schreiben_1h"] += cw1h
        cache["eingabe"] += in_t

        _summe_anteile(anteile_gesamt, anteile)
        gesamt_usd += usd
        gesamt_aufrufe += calls
        gesamt_verrechnet += int(charged or 0)
        verrechnet_usd += float(usd_verr or 0.0)
        verrechnete_aufrufe += int(n_verr or 0)

    def quote(lesen: int, schreiben: int, eingabe: int) -> float | None:
        nenner = lesen + schreiben + eingabe
        return round(lesen / nenner, 3) if nenner else None

    nach_typ = sorted(
        [{
            "typ": kind,
            "label": KIND_LABEL.get(kind, kind),
            "aufrufe": t["aufrufe"],
            "input_tokens": t["input_tokens"],
            "output_tokens": t["output_tokens"],
            "cache_read_tokens": t["cache_read_tokens"],
            "cache_write_tokens": t["cache_write_tokens"],
            "kosten_chf": _chf(t["usd"]),
            "verrechnet_tokens": t["verrechnet"],
            "pro_aufruf_rappen": _rappen(t["usd"] / t["aufrufe"]) if t["aufrufe"] else 0.0,
            "anteil": round(t["usd"] / gesamt_usd, 3) if gesamt_usd else 0.0,
            "modelle": sorted(t["modelle"]),
            **_anteile_chf(t["anteile"]),
        } for kind, t in typen.items()],
        key=lambda r: -r["kosten_chf"])

    nach_modell = sorted(
        [{
            "modell": model,
            "aufrufe": m["aufrufe"],
            "kosten_chf": _chf(m["usd"]),
            "pro_aufruf_rappen": _rappen(m["usd"] / m["aufrufe"]) if m["aufrufe"] else 0.0,
            "input_tokens": m["input_tokens"],
            "output_tokens": m["output_tokens"],
            "cache_read_tokens": m["cache_read_tokens"],
            "cache_write_tokens": m["cache_write_tokens"],
            "cache_quote": quote(m["cache_read_tokens"], m["cache_write_tokens"], m["input_tokens"]),
            "cache_netto_chf": _chf(m["netto_usd"]),
            **_anteile_chf(m["anteile"]),
        } for model, m in modelle.items()],
        key=lambda r: -r["kosten_chf"])

    # ---- Pro Aufgabe: ALLE Aufrufe derselben Aufgabe, also auch das Foto ----
    per_exercise = (
        select(ApiUsage.exercise_id,
               func.sum(ApiUsage.cost_usd).label("usd"),
               func.sum(case((ApiUsage.kind == "chat", 1), else_=0)).label("chats"),
               func.sum(case((ApiUsage.kind == "ocr", 1), else_=0)).label("fotos"))
        .where(im_fenster, ApiUsage.exercise_id.is_not(None))
        .group_by(ApiUsage.exercise_id)
        .subquery()
    )
    avg_usd, min_usd, max_usd, anzahl, avg_chats, avg_fotos = db.execute(
        select(func.avg(per_exercise.c.usd), func.min(per_exercise.c.usd),
               func.max(per_exercise.c.usd), func.count(),
               func.avg(per_exercise.c.chats), func.avg(per_exercise.c.fotos))
    ).one()

    teuerste = []
    for ex_id, usd, chats, fotos, text, von_admin in db.execute(
        select(per_exercise.c.exercise_id, per_exercise.c.usd, per_exercise.c.chats,
               per_exercise.c.fotos, Exercise.text, User.is_admin)
        .join(Exercise, Exercise.id == per_exercise.c.exercise_id)
        .join(User, User.id == Exercise.user_id)
        .order_by(per_exercise.c.usd.desc())
        .limit(TEUERSTE_AUFGABEN)
    ):
        teuerste.append({
            "exercise_id": ex_id,
            "text": (text or "").strip().replace("\n", " ")[:80],
            "rappen": _rappen(float(usd or 0.0)),
            "chats": int(chats or 0),
            "fotos": int(fotos or 0),
            "von_admin": bool(von_admin),
        })

    # ---- Fotos, aus denen nie eine Aufgabe wurde ----
    ocr_ohne_n, ocr_ohne_usd = db.execute(
        select(func.count(), func.sum(ApiUsage.cost_usd))
        .where(im_fenster, ApiUsage.kind == "ocr", ApiUsage.exercise_id.is_(None))
    ).one()
    ocr_ohne_n = int(ocr_ohne_n or 0)
    ocr_ohne_usd = float(ocr_ohne_usd or 0.0)

    # ---- Konten mit dem groessten Anteil (Gratis-Konten eingeschlossen) ----
    konten = db.execute(
        select(ApiUsage.user_id, User.is_admin, User.plan, func.count(), func.sum(ApiUsage.cost_usd))
        .join(User, User.id == ApiUsage.user_id)
        .where(im_fenster)
        .group_by(ApiUsage.user_id, User.is_admin, User.plan)
        .order_by(func.sum(ApiUsage.cost_usd).desc())
        .limit(5)
    ).all()
    # Alles, was niemandem verrechnet wurde: Betreiber-Konto, Schul-Plan und
    # Gratis-Funktionen (KI-Suche, Probepruefung).
    gratis_usd = gesamt_usd - verrechnet_usd

    # ---- Hinweise in Klartext: was treibt die Kosten, was ist auffaellig ----
    hinweise: list[dict] = []

    def hinweis(art: str, de: str, en: str) -> None:
        hinweise.append({"art": art, "text": i18n.t(lang, de, en)})

    if nach_typ and nach_typ[0]["anteil"] >= HINWEIS_ANTEIL:
        top = nach_typ[0]
        hinweis("info",
                f"«{top['label']}» macht {round(top['anteil'] * 100)} % der Kosten aus – "
                f"Ø {top['pro_aufruf_rappen']} Rp. pro Aufruf.",
                f"\"{top['label']}\" accounts for {round(top['anteil'] * 100)}% of costs – "
                f"avg. {top['pro_aufruf_rappen']} Rp. per call.")
    if ocr_ohne_n >= 3 and gesamt_usd:
        hinweis("warn",
                f"{ocr_ohne_n} Foto-Erkennungen ({_rappen(ocr_ohne_usd)} Rp.) fuehrten zu keiner Aufgabe – "
                f"das Foto wurde bezahlt, gelernt wurde damit nichts.",
                f"{ocr_ohne_n} photo recognitions ({_rappen(ocr_ohne_usd)} Rp.) never became a task – "
                f"the photo was paid for, nothing was learned from it.")
    for user_id, ist_admin, plan, calls, usd in konten:
        anteil = float(usd or 0.0) / gesamt_usd if gesamt_usd else 0.0
        if anteil >= HINWEIS_ANTEIL:
            wer_de = "dein Betreiber-Konto" if ist_admin else f"Konto Nr. {user_id}" + (" (Schul-Plan, gratis)" if plan == Plan.school else "")
            wer_en = "your operator account" if ist_admin else f"account no. {user_id}" + (" (school plan, free)" if plan == Plan.school else "")
            hinweis("info",
                    f"{round(anteil * 100)} % der Kosten verursacht {wer_de} ({calls} Aufrufe).",
                    f"{round(anteil * 100)}% of costs come from {wer_en} ({calls} calls).")
    for m in nach_modell:
        if m["aufrufe"] >= 5 and m["cache_quote"] is not None and m["cache_quote"] < CACHE_QUOTE_SCHWACH:
            hinweis("warn",
                    f"Bei {m['modell']} kamen nur {round(m['cache_quote'] * 100)} % der Eingabe aus dem Cache – "
                    f"der Vorlauf (Prompt + Aufgabe) wird fast jedes Mal voll bezahlt. Typische Gruende: Prompt "
                    f"unter der Cache-Mindestlaenge des Modells, Cache abgelaufen, oder ein Block vor dem "
                    f"Breakpoint aendert sich jeden Turn.",
                    f"For {m['modell']} only {round(m['cache_quote'] * 100)}% of input came from the cache – "
                    f"the prefix (prompt + task) is paid in full almost every time. Typical causes: prompt below "
                    f"the model's minimum cache length, cache expired, or a block before the breakpoint changes "
                    f"every turn.")
        if m["cache_netto_chf"] < 0:
            hinweis("warn",
                    f"Bei {m['modell']} kostet der Cache mehr, als er spart ({m['cache_netto_chf']} CHF): "
                    f"es wird geschrieben, aber kaum gelesen.",
                    f"For {m['modell']} the cache costs more than it saves ({m['cache_netto_chf']} CHF): "
                    f"it is written but rarely read.")
    marge_ist = None
    if verrechnet_usd > 0:
        marge_ist = round(gesamt_verrechnet / (verrechnet_usd * settings.usd_chf_rate * 100), 2)
    if gesamt_usd and gratis_usd / gesamt_usd >= 0.5:
        hinweis("info",
                f"{round(gratis_usd / gesamt_usd * 100)} % der Kosten wurden niemandem verrechnet "
                f"(Betreiber-Konto, Schul-Plan, Gratis-Funktionen wie die KI-Suche) – dafuer kommt kein "
                f"Geld herein. Die Marge unten gilt nur fuer verrechnete Aufrufe.",
                f"{round(gratis_usd / gesamt_usd * 100)}% of costs were charged to nobody (operator "
                f"account, school plan, free features such as AI search) – no revenue offsets them. The "
                f"margin below applies to charged calls only.")

    return {
        "zeitraum_tage": tage,
        "kurs_usd_chf": settings.usd_chf_rate,
        "marge_soll": settings.billing_margin,
        "pro_aufgabe": {
            "anzahl_aufgaben": int(anzahl or 0),
            "durchschnitt_rappen": _rappen(float(avg_usd or 0.0)),
            "min_rappen": _rappen(float(min_usd or 0.0)),
            "max_rappen": _rappen(float(max_usd or 0.0)),
            "chats_pro_aufgabe": round(float(avg_chats or 0.0), 1),
            "fotos_pro_aufgabe": round(float(avg_fotos or 0.0), 2),
        },
        "teuerste_aufgaben": teuerste,
        "nach_typ": nach_typ,
        "nach_modell": nach_modell,
        "anteile": _anteile_chf(anteile_gesamt),
        "cache": {
            "lesen_tokens": cache["lesen"],
            "schreiben_tokens": cache["schreiben"],
            "schreiben_1h_tokens": cache["schreiben_1h"],
            "quote": quote(cache["lesen"], cache["schreiben"], cache["eingabe"]),
            "brutto_chf": _chf(cache["brutto_usd"]),
            "mehrkosten_chf": _chf(cache["mehrkosten_usd"]),
            "netto_chf": _chf(cache["brutto_usd"] - cache["mehrkosten_usd"]),
        },
        "fotos_ohne_aufgabe": {"aufrufe": ocr_ohne_n, "kosten_chf": _chf(ocr_ohne_usd)},
        "hinweise": hinweise,
        "gesamt": {
            "aufrufe": gesamt_aufrufe,
            "kosten_usd": round(gesamt_usd, 4),
            "kosten_chf": _chf(gesamt_usd),
            # den Nutzern verrechnete Tokens (1 Token = 1 Rp.) im Zeitraum
            "verrechnet_tokens": gesamt_verrechnet,
            # nur die Aufrufe, fuer die auch verrechnet wurde – daran misst
            # sich die Marge; Gratis-Konten verzerren sie sonst nach unten
            "verrechnete_aufrufe": verrechnete_aufrufe,
            "kosten_verrechnet_chf": _chf(verrechnet_usd),
            "kosten_gratis_chf": _chf(gesamt_usd - verrechnet_usd),
            "marge_ist": marge_ist,
            # durch Prompt-Caching NETTO vermiedene Kosten (Ersparnis beim
            # Lesen minus Aufschlag beim Schreiben)
            "cache_ersparnis_chf": _chf(cache["brutto_usd"] - cache["mehrkosten_usd"]),
        },
    }


@router.get("/nutzer")
def nutzer(q: str = Query("", max_length=100),
           user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Nutzerliste mit Guthaben und Verbrauch – Support-Ansicht."""
    stmt = select(User).order_by(User.created_at.desc()).limit(200)
    if q.strip():
        needle = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.email.ilike(needle), User.display_name.ilike(needle)))
    users = list(db.scalars(stmt))

    # Verbrauch (verrechnete Tokens) je Nutzer in einem Rutsch
    ids = [u.id for u in users]
    verbrauch = dict(db.execute(
        select(ApiUsage.user_id, func.sum(ApiUsage.charged_tokens))
        .where(ApiUsage.user_id.in_(ids))
        .group_by(ApiUsage.user_id)
    ).all()) if ids else {}

    return [
        {
            "id": u.id,
            "email": u.email,
            "display_name": u.display_name,
            "role": u.role.value,
            "plan": u.plan.value,
            "is_admin": u.is_admin,
            "email_verified": u.email_verified,
            "token_balance": u.token_balance,
            "stufe": quota_service.stufe(db, u),
            "abo_bis": u.abo_bis.isoformat() if u.abo_bis else None,
            "abo_gekuendigt": bool(u.abo_gekuendigt),
            "free_used_tokens": u.free_used_tokens or 0,
            "monthly_free_tokens": settings.free_monthly_tokens,
            "verbraucht_tokens": int(verbrauch.get(u.id) or 0),
            "erstellt": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


@router.post("/nutzer/{user_id}/tokens")
def tokens_anpassen(user_id: int, payload: TokenAdjustRequest,
                    admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Guthaben manuell korrigieren (Kulanz, Rueckerstattung, verpasster Webhook).

    Positive Werte schreiben gut, negative ziehen ab (Boden bei 0).
    Jede Buchung wird mit Grund + Admin protokolliert."""
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nutzer nicht gefunden")

    n = payload.tokens
    db.execute(
        update(User).where(User.id == user_id).values(
            token_balance=case(
                (User.token_balance + n > 0, User.token_balance + n),
                else_=0,
            )
        )
    )
    db.add(TokenAdjustment(user_id=user_id, admin_id=admin.id,
                           tokens=n, reason=payload.grund.strip()))
    db.commit()
    db.refresh(target)
    log.info("Token-Korrektur: %+d fuer User %s durch Admin %s (%s)",
             n, user_id, admin.id, payload.grund.strip())
    return {"token_balance": target.token_balance}


# Wie viele Einzelmeldungen je Gruppe die Seite mitbekommt.
MELDUNGEN_JE_GRUPPE = 5


def _utc(zeit: datetime | None) -> str | None:
    """Zeitstempel mit Zeitzone. Die Spalte ist «naiv» (ohne Zone) und traegt
    UTC; ohne das «Z» liest der Browser sie als Ortszeit und zeigt die
    Stoerung zwei Stunden zu frueh oder zu spaet an."""
    if zeit is None:
        return None
    if zeit.tzinfo is None:
        zeit = zeit.replace(tzinfo=timezone.utc)
    return zeit.isoformat()


@router.get("/stoerungen")
def stoerungen(tage: int = Query(30, ge=1, le=365),
               user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Stoerungen im Zeitfenster, gebuendelt und eingeordnet.

    Statt einer Liste roher Fehlertexte: je Art EINE Gruppe mit Titel,
    Bedeutung fuer die Nutzer, Massnahme und der Stufe «handeln / pruefen /
    keine» (services/stoerungen.py). Die Einzelmeldungen haengen dran.
    """
    from .. import i18n
    from ..models import Alert
    from ..services.alert import KIND_LABEL as ALERT_LABEL
    from ..services.stoerungen import HAEUFUNG_24H, regel_fuer, stufe_mit_haeufung

    lang = i18n.lang_of(user)
    jetzt = datetime.now(timezone.utc)
    since = (jetzt - timedelta(days=tage)).replace(tzinfo=None)
    vor_24h = (jetzt - timedelta(hours=24)).replace(tzinfo=None)

    rows = list(db.scalars(select(Alert).where(Alert.created_at >= since)
                           .order_by(Alert.id.desc())))

    gruppen: dict[str, dict] = {}
    for a in rows:
        regel = regel_fuer(a.kind, a.detail)
        g = gruppen.setdefault(regel.id, {
            "id": regel.id, "kind": a.kind, "label": ALERT_LABEL.get(a.kind, a.kind),
            "regel": regel, "anzahl": 0, "anzahl_24h": 0,
            "erster": a.created_at, "letzter": a.created_at, "meldungen": [],
        })
        g["anzahl"] += 1
        if a.created_at and a.created_at >= vor_24h:
            g["anzahl_24h"] += 1
        if a.created_at:
            g["erster"] = min(g["erster"], a.created_at)
            g["letzter"] = max(g["letzter"], a.created_at)
        if len(g["meldungen"]) < MELDUNGEN_JE_GRUPPE:
            g["meldungen"].append({"zeit": _utc(a.created_at), "detail": a.detail})

    def satz(paar: tuple[str, str]) -> str:
        return i18n.t(lang, *paar)

    ausgabe = []
    for g in gruppen.values():
        regel = g.pop("regel")
        stufe = stufe_mit_haeufung(regel, g["anzahl_24h"])
        ausgabe.append({
            **g,
            "stufe": stufe,
            "gehaeuft": g["anzahl_24h"] >= HAEUFUNG_24H,
            "titel": satz(regel.titel),
            "bedeutung": satz(regel.bedeutung),
            "massnahme": satz(regel.massnahme),
            "erster": _utc(g["erster"]),
            "letzter": _utc(g["letzter"]),
        })
    rang = {"handeln": 0, "pruefen": 1, "keine": 2}
    ausgabe.sort(key=lambda g: (rang[g["stufe"]], g["letzter"] or ""), reverse=False)
    # Innerhalb einer Stufe die juengste zuerst
    ausgabe.sort(key=lambda g: (rang[g["stufe"]], -(datetime.fromisoformat(g["letzter"]).timestamp()
                                                    if g["letzter"] else 0)))

    stand = {"handeln": 0, "pruefen": 0, "keine": 0}
    for g in ausgabe:
        stand[g["stufe"]] += 1
    return {
        "zeitraum_tage": tage,
        "stand": stand,
        "meldungen_gesamt": len(rows),
        "gruppen": ausgabe,
        "drossel_hinweis": i18n.t(
            lang,
            "Meldungen sind auf eine pro Stunde und Fehlerart gedrosselt – die Zaehler sind Untergrenzen.",
            "Messages are throttled to one per hour and error type – the counts are lower bounds."),
    }
