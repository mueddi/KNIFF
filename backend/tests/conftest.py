"""Test-Setup: eigene SQLite-DB, frisch pro Test.

DATABASE_URL muss VOR dem App-Import gesetzt sein (engine entsteht beim Import).
Mit TEST_DATABASE_URL laufen die Tests gegen eine (leere, eigene!) Postgres-
Datenbank wie in der Produktion – noetig fuer tests/test_gleichzeitig.py,
denn SQLite sperrt beim Schreiben die ganze Datei und verdeckt so Fehler,
die nur Postgres (Zeilen-Sperren) zeigt. Die Tabellen werden pro Test
geloescht: NIE auf eine echte Datenbank zeigen lassen.
"""
import os

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or "sqlite:///./test_schrittweise.db"
os.environ["MAGIC_LINK_DEV_RETURN"] = "true"
os.environ["ANTHROPIC_API_KEY"] = ""  # Mock-Tutor erzwingen
# In Produktion ist die E-Mail-Bestaetigung Pflicht. Tests bestaetigen keine
# Mails – hier also aus; der gezielte Test (test_unverified_blocked_when_enforced)
# schaltet sie selbst ein und prueft die Sperre.
os.environ["REQUIRE_EMAIL_VERIFICATION"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c


def register(client: TestClient, email: str, role: str = "student", name: str = "Test") -> dict:
    """Registriert ein Konto (Passwort-Weg, wie das echte Formular) und liefert Auth-Header."""
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": "test-passwort-123", "display_name": name,
              "role": role, "terms_accepted": True},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
