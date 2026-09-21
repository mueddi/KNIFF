"""Belegte Fehler vom 19.9.: Loeschen mit Noten/Pruefungen, null im PATCH,
unsaubere Eingaben, die vorher zu 500 fuehrten."""
from app.database import SessionLocal
from app.models import Exam, ExamItem, Grade, Topic, User

from .conftest import register
from .test_exams import _mit_ki, _thema_mit_zielen


def _pruefung(client, headers, monkeypatch):
    tid = _thema_mit_zielen(client, headers)
    _mit_ki(monkeypatch)
    r = client.post(f"/api/topics/{tid}/pruefung", headers=headers)
    assert r.status_code == 201, r.text
    return tid, r.json()["id"]


def _note(client, headers, tid):
    r = client.post("/api/grades", headers=headers,
                    json={"value": 5.0, "taken_on": "2026-09-01", "label": "Test", "topic_id": tid})
    assert r.status_code in (200, 201), r.text


def test_konto_loeschen_mit_note_und_pruefung(client, monkeypatch):
    """Brach in der Produktion (Postgres) mit einer Fremdschluessel-Verletzung:
    Noten und Pruefungen wurden nicht mitgeloescht. SQLite prueft das jetzt auch."""
    headers = register(client, "mia@test.ch")
    tid, exam_id = _pruefung(client, headers, monkeypatch)
    _note(client, headers, tid)
    with SessionLocal() as db:
        assert db.query(Grade).count() == 1 and db.query(ExamItem).count() > 0

    r = client.post("/api/auth/delete-account", headers=headers, json={"password": "test-passwort-123"})
    assert r.status_code == 204, r.text
    with SessionLocal() as db:
        assert db.query(User).filter(User.email == "mia@test.ch").count() == 0
        assert db.query(Grade).count() == 0
        assert db.query(Exam).count() == 0
        assert db.query(ExamItem).count() == 0
        assert db.query(Topic).count() == 0


def test_thema_loeschen_mit_pruefung(client, monkeypatch):
    headers = register(client, "mia@test.ch")
    tid, exam_id = _pruefung(client, headers, monkeypatch)
    # Pruefung abgeben -> Note mit exam_id
    with SessionLocal() as db:
        items = db.query(ExamItem).filter(ExamItem.exam_id == exam_id).all()
        antworten = [{"id": i.id, "answer": "5"} for i in items]
    assert client.post(f"/api/exams/{exam_id}/abgeben", headers=headers,
                       json={"antworten": antworten}).status_code == 200
    # Mit Note haengt ein 409 davor; ?trotzdem=true loescht Thema und Pruefung,
    # die Note bleibt (ohne Thema, ohne Pruefung).
    assert client.delete(f"/api/topics/{tid}", headers=headers).status_code == 409
    assert client.delete(f"/api/topics/{tid}?trotzdem=true", headers=headers).status_code == 204
    with SessionLocal() as db:
        assert db.query(Exam).count() == 0 and db.query(ExamItem).count() == 0
        note = db.query(Grade).one()
        assert note.topic_id is None and note.exam_id is None


def test_thema_patch_mit_null_leert_keine_pflichtspalte(client):
    headers = register(client, "mia@test.ch")
    tid = client.post("/api/topics", headers=headers, json={"name": "Algebra"}).json()["id"]
    r = client.patch(f"/api/topics/{tid}", headers=headers, json={"name": None, "color": None})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Algebra"


def test_generieren_mit_unsinniger_themen_id_gibt_422(client):
    headers = register(client, "mia@test.ch")
    r = client.post("/api/exercises/generieren", headers=headers, json={"topic_id": "abc"})
    assert r.status_code == 422


def test_pruefungs_abgabe_mit_ueberlangem_bildpfad_gibt_422(client, monkeypatch):
    headers = register(client, "mia@test.ch")
    tid, exam_id = _pruefung(client, headers, monkeypatch)
    with SessionLocal() as db:
        item_id = db.query(ExamItem).filter(ExamItem.exam_id == exam_id).first().id
    r = client.post(f"/api/exams/{exam_id}/abgeben", headers=headers,
                    json={"antworten": [{"id": item_id, "answer": "5", "image_path": "/x" * 200}]})
    assert r.status_code == 422
