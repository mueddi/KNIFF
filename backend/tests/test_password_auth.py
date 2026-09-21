"""Passwort-Login: Registrierung, Anmeldung, Fehlerfälle, Rate-Limit, Passwort ändern."""
from app.routers.auth import LOGIN_FAIL_MAX
from app.security import create_access_token


def test_register_logs_in_directly(client):
    r = client.post(
        "/api/auth/register",
        json={"terms_accepted": True, "email": "mia@test.ch", "password": "drei-worte-merken", "display_name": "Mia"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert body["user"]["display_name"] == "Mia"

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200


def test_login_with_correct_password(client):
    client.post(
        "/api/auth/register",
        json={"terms_accepted": True, "email": "mia@test.ch", "password": "drei-worte-merken", "display_name": "Mia"},
    )
    r = client.post("/api/auth/login", json={"email": "mia@test.ch", "password": "drei-worte-merken"})
    assert r.status_code == 200
    assert r.json()["access_token"]


def test_login_wrong_password_or_unknown_email(client):
    client.post(
        "/api/auth/register",
        json={"terms_accepted": True, "email": "mia@test.ch", "password": "drei-worte-merken", "display_name": "Mia"},
    )
    assert client.post("/api/auth/login", json={"email": "mia@test.ch", "password": "falsch-falsch"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "ghost@test.ch", "password": "drei-worte-merken"}).status_code == 401


def test_register_duplicate_email_conflicts(client):
    client.post(
        "/api/auth/register",
        json={"terms_accepted": True, "email": "mia@test.ch", "password": "drei-worte-merken", "display_name": "Mia"},
    )
    r = client.post(
        "/api/auth/register",
        json={"terms_accepted": True, "email": "mia@test.ch", "password": "anderes-passwort1", "display_name": "Mia2"},
    )
    assert r.status_code == 409


def test_register_short_password_rejected(client):
    r = client.post(
        "/api/auth/register",
        json={"terms_accepted": True, "email": "mia@test.ch", "password": "kurz", "display_name": "Mia"},
    )
    assert r.status_code == 422


def test_login_rate_limit_blocks_after_too_many_failures(client):
    client.post(
        "/api/auth/register",
        json={"terms_accepted": True, "email": "mia@test.ch", "password": "drei-worte-merken", "display_name": "Mia"},
    )
    for _ in range(LOGIN_FAIL_MAX):
        r = client.post("/api/auth/login", json={"email": "mia@test.ch", "password": "falsch-falsch"})
        assert r.status_code == 401
    # Limit erreicht: auch das KORREKTE Passwort wird jetzt abgewiesen (429)
    r = client.post("/api/auth/login", json={"email": "mia@test.ch", "password": "drei-worte-merken"})
    assert r.status_code == 429
    # Andere E-Mail bleibt unbetroffen
    client.post(
        "/api/auth/register",
        json={"terms_accepted": True, "email": "ben@test.ch", "password": "drei-worte-merken", "display_name": "Ben"},
    )
    assert client.post("/api/auth/login", json={"email": "ben@test.ch", "password": "drei-worte-merken"}).status_code == 200


def test_login_success_resets_failure_counter(client):
    client.post(
        "/api/auth/register",
        json={"terms_accepted": True, "email": "mia@test.ch", "password": "drei-worte-merken", "display_name": "Mia"},
    )
    for _ in range(LOGIN_FAIL_MAX - 1):
        client.post("/api/auth/login", json={"email": "mia@test.ch", "password": "falsch-falsch"})
    assert client.post("/api/auth/login", json={"email": "mia@test.ch", "password": "drei-worte-merken"}).status_code == 200
    # Zaehler zurueckgesetzt: erneute Fehlversuche starten wieder bei 0
    assert client.post("/api/auth/login", json={"email": "mia@test.ch", "password": "falsch-falsch"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "mia@test.ch", "password": "drei-worte-merken"}).status_code == 200


def test_change_password_requires_current_password(client):
    r = client.post(
        "/api/auth/register",
        json={"terms_accepted": True, "email": "mia@test.ch", "password": "drei-worte-merken", "display_name": "Mia"},
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # Falsches/fehlendes aktuelles Passwort -> 403
    assert client.post("/api/auth/change-password", headers=headers,
                       json={"current_password": "falsch-falsch", "new_password": "neues-passwort-1"}).status_code == 403
    assert client.post("/api/auth/change-password", headers=headers,
                       json={"new_password": "neues-passwort-1"}).status_code == 403

    # Korrekt -> Login nur noch mit dem neuen Passwort moeglich
    ok = client.post("/api/auth/change-password", headers=headers,
                     json={"current_password": "drei-worte-merken", "new_password": "neues-passwort-1"})
    assert ok.status_code == 200, ok.text
    assert client.post("/api/auth/login", json={"email": "mia@test.ch", "password": "drei-worte-merken"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "mia@test.ch", "password": "neues-passwort-1"}).status_code == 200


def test_change_password_via_email_link_needs_no_current(client):
    """Passwort-vergessen-Flow: Login kam per Mail-Link (via=email) ->
    neues Passwort ohne altes setzbar."""
    r = client.post(
        "/api/auth/register",
        json={"terms_accepted": True, "email": "mia@test.ch", "password": "vergessenes-passwort", "display_name": "Mia"},
    )
    user_id = r.json()["user"]["id"]
    email_token = create_access_token(user_id, "student", via="email")
    headers = {"Authorization": f"Bearer {email_token}"}

    ok = client.post("/api/auth/change-password", headers=headers,
                     json={"new_password": "frisch-gesetzt-99"})
    assert ok.status_code == 200, ok.text
    assert client.post("/api/auth/login", json={"email": "mia@test.ch", "password": "frisch-gesetzt-99"}).status_code == 200


def test_passwordless_legacy_account_is_not_taken_over_by_register(client):
    # Alt-Konto aus der Magic-Link-Zeit (ohne Passwort, nie eingeloggt) –
    # direkt in der DB anlegen, den Anlage-Weg gibt es nicht mehr. Wer nur die
    # E-Mail kennt, darf es NICHT per Registrierung uebernehmen (409); der
    # Weg hinein ist «Passwort vergessen» mit Mail-Link.
    from app.database import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        db.add(User(email="alt@test.ch", display_name="Alt"))
        db.commit()
    r = client.post(
        "/api/auth/register",
        json={"terms_accepted": True, "email": "alt@test.ch", "password": "jetzt-mit-passwort", "display_name": "Alt"},
    )
    assert r.status_code == 409, r.text
    assert "Passwort vergessen" in r.json()["detail"]
    assert client.post("/api/auth/login", json={"email": "alt@test.ch", "password": "jetzt-mit-passwort"}).status_code != 200


# ---- Registrierungs-Schutz (Launch-Punkt 2 + 4) ----

def test_register_requires_terms(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "mia@test.ch", "password": "drei-worte-merken"},
    )
    assert r.status_code == 400
    assert "AGB" in r.json()["detail"]


def test_register_honeypot_blocks_bots(client):
    r = client.post(
        "/api/auth/register",
        json={"terms_accepted": True, "email": "bot@test.ch", "password": "drei-worte-merken",
              "website": "https://spam.example"},
    )
    assert r.status_code == 400


def test_register_ip_rate_limit(client):
    from app.routers.auth import REGISTER_IP_MAX_PER_DAY

    for i in range(REGISTER_IP_MAX_PER_DAY):
        r = client.post(
            "/api/auth/register",
            json={"terms_accepted": True, "email": f"kind{i}@test.ch", "password": "drei-worte-merken"},
        )
        assert r.status_code == 200, r.text
    # Naechstes Konto von derselben IP -> 429
    r = client.post(
        "/api/auth/register",
        json={"terms_accepted": True, "email": "einer-zuviel@test.ch", "password": "drei-worte-merken"},
    )
    assert r.status_code == 429


def test_register_stores_terms_timestamp(client):
    from app.database import SessionLocal
    from app.models import User

    client.post(
        "/api/auth/register",
        json={"terms_accepted": True, "email": "mia@test.ch", "password": "drei-worte-merken"},
    )
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == "mia@test.ch").one()
        assert u.terms_accepted_at is not None


def test_password_change_invalidates_old_tokens(client):
    r = client.post(
        "/api/auth/register",
        json={"terms_accepted": True, "email": "mia@test.ch", "password": "drei-worte-merken"},
    )
    old_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=old_headers).status_code == 200

    r2 = client.post("/api/auth/change-password", headers=old_headers,
                     json={"current_password": "drei-worte-merken", "new_password": "ganz-neues-passwort"})
    assert r2.status_code == 200
    new_headers = {"Authorization": f"Bearer {r2.json()['access_token']}"}

    # Altes Token (z.B. gestohlenes Tablet) ist sofort draussen, neues funktioniert
    assert client.get("/api/auth/me", headers=old_headers).status_code == 401
    assert client.get("/api/auth/me", headers=new_headers).status_code == 200


# ---- E-Mail-Bestätigung (Launch-Punkt 3) ----

def _register(client, email="mia@test.ch"):
    r = client.post(
        "/api/auth/register",
        json={"terms_accepted": True, "email": email, "password": "drei-worte-merken"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_register_starts_unverified_link_click_verifies(client):
    body = _register(client)
    assert body["user"]["email_verified"] is False

    # Link anfordern (Dev-Modus gibt den Token zurueck) und klicken
    r = client.post("/api/auth/request-link", json={"email": "mia@test.ch"})
    token = r.json()["dev_token"]
    v = client.post("/api/auth/verify", json={"token": token})
    assert v.status_code == 200
    assert v.json()["user"]["email_verified"] is True


def test_unverified_blocked_when_enforced(client, monkeypatch):
    from app.config import settings as cfg
    from app.database import SessionLocal
    from app.models import User

    body = _register(client)
    headers = {"Authorization": f"Bearer {body['access_token']}"}

    # Ohne Erzwingung offen (in Produktion ist sie AN, in der Test-Env aus)
    assert client.post("/api/exercises", headers=headers, json={"text": "x=1"}).status_code == 201

    monkeypatch.setattr(cfg, "require_email_verification", True)
    r = client.post("/api/exercises", headers=headers, json={"text": "x=2"})
    assert r.status_code == 403
    assert "bestätige" in r.json()["detail"].lower()
    # Kauf ebenfalls gesperrt (403 kommt VOR dem 503 wegen fehlender Stripe-Keys)
    assert client.post("/api/pay/checkout", headers=headers, json={"package": "schnupper"}).status_code == 403

    # Nach Bestaetigung wieder offen
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == "mia@test.ch").one()
        u.email_verified = True
        db.commit()
    assert client.post("/api/exercises", headers=headers, json={"text": "x=3"}).status_code == 201
