"""Betreiber-Alarm bei kritischen Stoerungen (KI-Ausfall, Webhook-Fehler, OCR).

Zweigleisig, damit nichts verloren geht:
1. Alert-Zeile in der DB – der Admin-Bereich zeigt die letzten Stoerungen.
2. E-Mail an den Betreiber, sobald SMTP konfiguriert ist.

Gedrosselt auf 1 Meldung pro Stunde und Fehlertyp (In-Memory je Instanz –
lieber gelegentlich eine Meldung zu viel als gar keine). notify() darf NIE
einen Nutzer-Request scheitern lassen.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("schrittweise.alert")

COOLDOWN_SECONDS = 3600
_last_sent: dict[str, float] = {}

KIND_LABEL = {
    "ki": "KI-Tutor nicht erreichbar",
    "ocr": "Handschrift-Erkennung ausgefallen",
    "webhook": "Stripe-Webhook abgelehnt",
    "zahlung": "Zahlung / Abo braucht Handarbeit",
    "mail": "Mailversand fehlgeschlagen",
    "server": "Server-Fehler",
    "client": "Fehler in der App (Browser)",
    "ki-qualitaet": "KI-Rechenfehler (auto-korrigiert)",
}


def notify(kind: str, detail: str, key: str | None = None) -> None:
    """Stoerung melden: DB-Protokoll immer, Mail bei konfiguriertem SMTP.

    ``key``: verfeinert die Drosselung – verschiedene Fehler desselben
    Typs (z.B. unterschiedliche Routen/Meldungen) verschlucken sich
    dann nicht mehr gegenseitig.
    """
    try:
        now = time.time()
        throttle_key = f"{kind}:{key}" if key else kind
        if now - _last_sent.get(throttle_key, 0) < COOLDOWN_SECONDS:
            return
        _last_sent[throttle_key] = now

        title = KIND_LABEL.get(kind, kind)
        detail = (detail or "")[:500]

        # 1) DB-Protokoll (eigene Session – wir stecken evtl. mitten in einem Fehler)
        try:
            from ..database import SessionLocal
            from ..models import Alert

            with SessionLocal() as db:
                db.add(Alert(kind=kind, detail=detail))
                db.commit()
        except Exception:
            log.exception("Alert-Protokoll fehlgeschlagen (%s)", kind)

        # 2) Mail (best effort)
        try:
            from .mailer import send_alert_mail

            send_alert_mail(title, f"{title}\n\nDetails:\n{detail}\n\n"
                                   "Diese Meldung ist auf 1x pro Stunde und Fehlertyp gedrosselt.")
        except Exception:
            log.exception("Alarm-Mail fehlgeschlagen (%s)", kind)
    except Exception:
        log.exception("notify() selbst fehlgeschlagen (%s)", kind)
