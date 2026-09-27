"""Neuer Abo-Monat, viele Anfragen zugleich: der Topf wird genau einmal auf
die Monatsmenge gesetzt, und keine Abbuchung geht verloren.

Echte Threads mit eigener DB-Sitzung und gemeinsamem Startschuss.
Aussagekraeftig nur auf Postgres (CI-Job backend-postgres bzw.
TEST_DATABASE_URL, siehe tests/test_gleichzeitig.py) – SQLite sperrt die
ganze Datei. Gegenprobe vom 26.9. auf Postgres: Bedingung «nur wenn neuer
Monat» beim Auffuellen entfernt -> rot."""
import threading
from datetime import datetime, timedelta

from app.config import settings
from app.database import SessionLocal
from app.models import User
from app.services.quota import charge

from .test_library import register_pw

THREADS = 12


def test_neuer_abo_monat_gleichzeitig_nur_einmal_aufgefuellt(client, monkeypatch):
    monkeypatch.setattr(settings, "abo_enabled", True)
    register_pw(client, "mia@test.ch")
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == "mia@test.ch").one()
        u.token_balance, u.abo_tokens, u.abo_periode = 50, 7, "2000-01-01T00:00"
        u.abo_bis, u.abo_intervall = datetime.utcnow() + timedelta(days=20), "monat"
        db.commit()
        uid = u.id
    start, fehler = threading.Barrier(THREADS), []

    def lauf():
        try:
            start.wait()
            for _ in range(3):
                with SessionLocal() as db:
                    charge(db, uid, 4, vom_guthaben=True)
                    db.commit()
        except Exception as e:  # pragma: no cover
            fehler.append(e)

    threads = [threading.Thread(target=lauf) for _ in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not fehler, fehler
    with SessionLocal() as db:
        u = db.get(User, uid)
        assert (u.abo_tokens, u.token_balance) == (settings.plus_tokens_monat - THREADS * 3 * 4, 50)
