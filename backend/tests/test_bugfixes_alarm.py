"""Browser-Fehler-Meldungen sind pro Konto gedeckelt (Alarm-Flut)."""
from app.database import SessionLocal
from app.models import Alert
from app.routers.feedback import CLIENT_FEHLER_MAX_PRO_STUNDE
from app.services import alert as alert_service

from .conftest import register


def test_app_fehler_hoechstens_fuenf_pro_konto_und_stunde(client):
    headers = register(client, "mia@test.ch")
    alert_service._last_sent.clear()
    for i in range(CLIENT_FEHLER_MAX_PRO_STUNDE + 4):
        # jedes Mal ein anderer Text, damit die Drossel pro Meldung nicht greift
        r = client.post("/api/feedback/app-fehler", headers=headers,
                        json={"message": f"TypeError: kaputt Nummer {i}", "url": "/app/lernen"})
        assert r.status_code == 201
    with SessionLocal() as db:
        rows = db.query(Alert).filter(Alert.kind == "client").all()
    assert len(rows) == CLIENT_FEHLER_MAX_PRO_STUNDE
    assert all(r.detail.startswith("[u") for r in rows)
