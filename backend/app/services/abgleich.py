"""Zahlungs-Abgleich: hat die App jede bezahlte Stripe-Zahlung verbucht?

Am 25.9. stand fest: der Webhook war nie angekommen (0 Stripe-Ereignisse in
der Datenbank). Haette jemand gekauft, haette er bezahlt und nichts
bekommen – und niemand haette es gemerkt. Dieser Abgleich vergleicht, was
Stripe als bezahlt fuehrt, mit den Zeilen in ``payments``. Die Logik hier
ist rein (ohne Netz und Datenbank) und damit testbar; das Holen der Daten
macht ``scripts/zahlungsabgleich.py``.

Was in payments.session_id stehen muss:
- Token-Paket (Checkout, mode=payment):     die Checkout-Session-ID
- Abo-Abschluss (Checkout, mode=subscription): die ID der ersten Rechnung
  (ohne Rechnung: die Session-ID) – so verbucht es pay._abo_abgeschlossen
- jede bezahlte Abo-Rechnung:                die Rechnungs-ID
"""
from __future__ import annotations

from dataclasses import dataclass

# So lange darf der Webhook brauchen, bevor eine fehlende Buchung auffaellt.
KARENZ_SEKUNDEN = 3600


@dataclass(frozen=True)
class StripeKauf:
    kennung: str        # was in payments.session_id stehen muss
    art: str            # "paket" | "abo"
    betrag_rappen: int
    erstellt: int       # Unix-Zeit bei Stripe


@dataclass(frozen=True)
class Abweichung:
    kauf: StripeKauf
    grund: str          # "fehlt" | "betrag"
    verbucht_rappen: int | None = None


def _abo_der_rechnung(inv: dict) -> str | None:
    sid = inv.get("subscription")
    if not sid:
        sid = ((inv.get("parent") or {}).get("subscription_details") or {}).get("subscription")
    return sid if isinstance(sid, str) else None


def kaeufe_aus_stripe(sessions: list[dict], rechnungen: list[dict]) -> list[StripeKauf]:
    """Bezahlte Kaeufe aus abgeschlossenen Checkout-Sessions und bezahlten
    Abo-Rechnungen, je Kennung genau einmal (die erste Abo-Rechnung kommt
    ueber beide Wege)."""
    kaeufe: dict[str, StripeKauf] = {}
    for s in sessions:
        if s.get("status") != "complete" or s.get("payment_status") != "paid":
            continue
        if s.get("mode") == "payment":
            k = StripeKauf(s["id"], "paket", int(s.get("amount_total") or 0), int(s.get("created") or 0))
        elif s.get("mode") == "subscription":
            kennung = s["invoice"] if isinstance(s.get("invoice"), str) else s["id"]
            k = StripeKauf(kennung, "abo", int(s.get("amount_total") or 0), int(s.get("created") or 0))
        else:
            continue
        kaeufe.setdefault(k.kennung, k)
    for inv in rechnungen:
        if inv.get("status") != "paid" or not _abo_der_rechnung(inv) or not int(inv.get("amount_paid") or 0):
            continue
        k = StripeKauf(inv["id"], "abo", int(inv["amount_paid"]), int(inv.get("created") or 0))
        kaeufe.setdefault(k.kennung, k)
    return list(kaeufe.values())


def abweichungen(kaeufe: list[StripeKauf], verbucht: dict[str, int], jetzt: int,
                 karenz: int = KARENZ_SEKUNDEN) -> list[Abweichung]:
    """Was bei Stripe bezahlt ist, aber in der App fehlt oder mit anderem
    Betrag steht. ``verbucht``: payments.session_id -> amount_rappen.
    Ganz frische Kaeufe (juenger als ``karenz``) zaehlen noch nicht."""
    aus: list[Abweichung] = []
    for k in sorted(kaeufe, key=lambda k: k.erstellt):
        if k.kennung not in verbucht:
            if jetzt - k.erstellt >= karenz:
                aus.append(Abweichung(k, "fehlt"))
        elif verbucht[k.kennung] != k.betrag_rappen:
            aus.append(Abweichung(k, "betrag", verbucht[k.kennung]))
    return aus
