"""Gleichzeitigkeit: zwei Antworten im selben Augenblick, derselbe Webhook
zweimal auf einmal.

quota.charge ist mit bedingten UPDATEs gebaut (die Datenbank rechnet, nicht
Python) – genau dafuer, dass parallele Anfragen nichts verlieren und nichts
doppelt buchen. Bisher prueften das nur Tests, die alles nacheinander
schickten. Hier laufen echte Threads mit je eigener Datenbank-Sitzung, die
eine Schranke gleichzeitig losschickt. (Ueber den TestClient ginge das
nicht: der fuehrt Anfragen nacheinander aus.)

Aussagekraeftig ist das nur auf Postgres (CI-Job backend-postgres, lokal mit
TEST_DATABASE_URL): SQLite sperrt beim ersten Schreiben die ganze Datei, dort
laeuft alles ohnehin nacheinander. Gegenprobe vom 26.9.: charge naiv als
Lesen-Rechnen-Schreiben umgebaut -> auf Postgres 3 von 3 Laeufen rot, auf
SQLite gruen."""
import threading

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import Payment, User
from app.routers import pay
from app.services.quota import charge

from .test_library import register_pw

THREADS = 12


def _gleichzeitig(arbeit, n=THREADS):
    """arbeit(i) in n Threads, alle ab demselben Startschuss; Fehler der
    Threads kommen im Test an statt still zu verschwinden."""
    start = threading.Barrier(n)
    fehler = []

    def lauf(i):
        try:
            start.wait()
            arbeit(i)
        except Exception as e:  # pragma: no cover - soll gerade nicht passieren
            fehler.append(e)

    threads = [threading.Thread(target=lauf, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not fehler, fehler


def _konto(client, **felder):
    register_pw(client, "mia@test.ch")
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == "mia@test.ch").one()
        for k, v in felder.items():
            setattr(u, k, v)
        db.commit()
        return u.id


def _frisch():
    with SessionLocal() as db:
        return db.query(User).filter(User.email == "mia@test.ch").one()


@pytest.fixture(autouse=True)
def abo_modell(monkeypatch):
    monkeypatch.setattr(settings, "abo_enabled", True)


def test_paralleles_abbuchen_verliert_nichts(client):
    uid = _konto(client, token_balance=1000)

    def abbuchen(i):
        for _ in range(5):
            with SessionLocal() as db:
                charge(db, uid, 3, vom_guthaben=True)
                db.commit()

    _gleichzeitig(abbuchen)
    u = _frisch()
    verbraucht = THREADS * 5 * 3
    assert (u.token_balance, u.free_used_tokens) == (1000 - verbraucht, verbraucht)


def test_letzte_tokens_gleichzeitig_nie_unter_null(client):
    uid = _konto(client, token_balance=5)

    def abbuchen(i):
        with SessionLocal() as db:
            charge(db, uid, 3, vom_guthaben=True)
            db.commit()

    _gleichzeitig(abbuchen)
    assert _frisch().token_balance == 0


def test_derselbe_kauf_gleichzeitig_nur_einmal_gutgeschrieben(client):
    """Stripe schickt ein Ereignis gelegentlich doppelt, auch fast zeitgleich."""
    uid = _konto(client)
    session = {"id": "cs_doppelt", "mode": "payment", "payment_status": "paid", "amount_total": 900,
               "currency": "chf", "client_reference_id": str(uid),
               "metadata": {"user_id": str(uid), "package": "starter"}}

    def gutschreiben(i):
        with SessionLocal() as db:
            pay._paket_gutschrift(db, dict(session))
            db.commit()

    _gleichzeitig(gutschreiben, n=6)
    assert _frisch().token_balance == 900
    with SessionLocal() as db:
        assert db.query(Payment).filter(Payment.session_id == "cs_doppelt").count() == 1
