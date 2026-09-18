"""Kniff Plus aus der Elternansicht: Eltern kaufen und kuendigen fuer ihr Kind."""
from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models import User

from .conftest import register
from .test_abo_webhooks import abo_an, stripe  # noqa: F401  (Fixtures)


def _verknuepfen(client):
    s = register(client, "kind@test.ch", name="Kind")
    p = register(client, "mami@test.ch", role="parent", name="Mami")
    code = client.get("/api/parents/invite", headers=s).json()["invite_code"]
    assert client.post("/api/parents/redeem", headers=p, json={"invite_code": code}).status_code == 200
    kid_id = client.get("/api/auth/me", headers=s).json()["id"]
    return s, p, kid_id


def test_eltern_sehen_stufe_und_kaufen_fuer_ihr_kind(client, stripe):
    calls, _ = stripe
    s, p, kid_id = _verknuepfen(client)
    kinder = client.get("/api/parents/children", headers=p).json()
    assert kinder[0]["student_id"] == kid_id
    assert kinder[0]["plus"]["stufe"] == "trial" and kinder[0]["plus"]["abo_enabled"] is True

    r = client.post("/api/pay/checkout", headers=p, json={"intervall": "jahr", "student_id": kid_id})
    assert r.status_code == 200, r.text
    data = calls[-1][2]
    assert data["client_reference_id"] == str(kid_id)  # das Abo haengt am Kind ...
    assert data["customer_email"] == "mami@test.ch"     # ... die Rechnung an den Eltern
    assert data["line_items[0][price_data][recurring][interval]"] == "year"
    assert "/eltern?zahlung=ok" in data["success_url"]


def test_eltern_nur_fuer_verknuepfte_kinder(client, stripe):
    s, p, kid_id = _verknuepfen(client)
    fremd = register(client, "fremd@test.ch", name="Fremd")
    fremd_id = client.get("/api/auth/me", headers=fremd).json()["id"]
    assert client.post("/api/pay/checkout", headers=p, json={"intervall": "monat", "student_id": fremd_id}).status_code == 403
    assert client.post("/api/pay/checkout", headers=p, json={"intervall": "monat"}).status_code == 400
    # Schueler koennen nicht fuer ein anderes Konto kaufen
    assert client.post("/api/pay/checkout", headers=s, json={"intervall": "monat", "student_id": fremd_id}).status_code == 403
    assert client.post("/api/pay/checkout", headers=s, json={"intervall": "monat", "student_id": kid_id}).status_code == 200


def test_eltern_kuendigen_das_abo_des_kindes(client, stripe):
    calls, _ = stripe
    s, p, kid_id = _verknuepfen(client)
    with SessionLocal() as db:
        u = db.get(User, kid_id)
        u.stripe_subscription_id, u.abo_bis = "sub_kind", datetime.utcnow() + timedelta(days=20)
        db.commit()
    r = client.post("/api/pay/abo/kuendigen", headers=p, json={"student_id": kid_id})
    assert r.status_code == 200 and r.json()["abo_gekuendigt"] is True
    assert calls[-1][1] == "/v1/subscriptions/sub_kind"
    assert client.get("/api/parents/children", headers=p).json()[0]["plus"]["abo_gekuendigt"] is True
    assert client.post("/api/pay/abo/weiter", headers=p, json={"student_id": kid_id}).json()["abo_gekuendigt"] is False
