"""Taeglicher Zahlungs-Abgleich Stripe <-> Produktions-Datenbank.

Laeuft in .github/workflows/zahlungsabgleich.yml. Holt die bezahlten
Checkout-Sessions und Abo-Rechnungen der letzten TAGE Tage bei Stripe und
prueft, ob jede davon in ``payments`` verbucht ist (Logik:
app/services/abgleich.py). Fehlt etwas: Liste ausgeben, Exit-Code 1 – der
Workflow wird rot und GitHub schickt eine Mail.

    STRIPE_ABGLEICH_KEY=rk_live_... DATABASE_URL=postgresql://... \\
        python scripts/zahlungsabgleich.py

Gibt nur Stripe-IDs und Betraege aus, keine Namen oder Mail-Adressen.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.abgleich import abweichungen, kaeufe_aus_stripe  # noqa: E402


def _alle(key: str, pfad: str, params: dict) -> list[dict]:
    """Eine Stripe-Liste vollstaendig holen (Seiten zu je 100)."""
    daten, nach = [], None
    while True:
        p = dict(params, limit=100)
        if nach:
            p["starting_after"] = nach
        r = httpx.get(f"https://api.stripe.com{pfad}", params=p, auth=(key, ""),
                      headers={"Stripe-Version": settings.stripe_api_version}, timeout=30)
        r.raise_for_status()
        seite = r.json()
        daten += seite.get("data") or []
        if not seite.get("has_more") or not daten:
            return daten
        nach = daten[-1]["id"]


def _db_url(url: str) -> str:
    for alt in ("postgres://", "postgresql://"):
        if url.startswith(alt):
            return url.replace(alt, "postgresql+psycopg://", 1)
    return url


def main() -> int:
    key = os.environ.get("STRIPE_ABGLEICH_KEY", "").strip()
    db_url = os.environ.get("DATABASE_URL", "").strip()
    tage = int(os.environ.get("TAGE", "3"))
    if not key.startswith(("sk_live_", "rk_live_")):
        print("::error::STRIPE_ABGLEICH_KEY fehlt oder ist kein Live-Schluessel (sk_live_/rk_live_).")
        return 1
    if not db_url:
        print("::error::DATABASE_URL fehlt.")
        return 1

    jetzt = int(time.time())
    seit = {"created[gte]": jetzt - tage * 86400}
    sessions = _alle(key, "/v1/checkout/sessions", dict(seit, status="complete"))
    rechnungen = _alle(key, "/v1/invoices", dict(seit, status="paid"))
    kaeufe = kaeufe_aus_stripe(sessions, rechnungen)

    with create_engine(_db_url(db_url)).connect() as conn:
        verbucht = {sid: betrag for sid, betrag in conn.execute(text("select session_id, amount_rappen from payments"))}

    fehler = abweichungen(kaeufe, verbucht, jetzt)
    zeilen = [f"## Zahlungs-Abgleich ({tage} Tage)", "",
              f"Bei Stripe bezahlt: **{len(kaeufe)}** · in der App verbucht (insgesamt): **{len(verbucht)}** · "
              f"Abweichungen: **{len(fehler)}**", ""]
    if fehler:
        zeilen += ["| Stripe-Kennung | Art | Betrag Stripe | Befund |", "|---|---|---|---|"]
        for a in fehler:
            befund = ("bezahlt, aber NICHT verbucht – Kunde hat nichts bekommen" if a.grund == "fehlt"
                      else f"verbucht mit CHF {a.verbucht_rappen / 100:.2f} statt Stripe-Betrag")
            zeilen.append(f"| `{a.kauf.kennung}` | {a.kauf.art} | CHF {a.kauf.betrag_rappen / 100:.2f} | {befund} |")
        zeilen += ["", "Was tun: im Stripe-Dashboard die Kennung suchen; fehlt die Buchung, "
                       "Webhook-Zustellungen pruefen und dem Konto von Hand gutschreiben (Admin → Nutzer)."]
    bericht = "\n".join(zeilen)
    print(bericht)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(bericht + "\n")
    for a in fehler:
        print(f"::error::Stripe {a.kauf.kennung} ({a.kauf.art}, CHF {a.kauf.betrag_rappen / 100:.2f}): {a.grund}")
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
