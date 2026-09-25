"""Sicherheits- und Absturz-Pruefung ueber ALLE Schnittstellen.

Diese Tests laufen ueber app.routes statt ueber eine Handliste. Kommt eine
neue Schnittstelle dazu, ist sie automatisch mit drin:

* Ohne Anmeldung gibt es nichts – ausser den Wegen in OEFFENTLICH. Wer eine
  neue oeffentliche Schnittstelle baut, muss sie hier bewusst eintragen.
* Schueler kommen nicht in Admin-Schnittstellen, Eltern nicht in
  Schueler-Schnittstellen und umgekehrt.
* Kein Aufruf, egal mit welchem Muell, endet in einem unbehandelten
  Absturz (500). Gezielte 502/503 (Stripe, KI nicht erreichbar) sind
  erlaubt – das sind bewusste Antworten, keine Abstuerze.
* Fremde Daten: ein zweites Konto kommt nicht an Themen, Aufgaben,
  Versuche, Pruefungen und Noten des ersten.
"""
import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import app

from .conftest import register
from .test_library import make_admin, register_pw

# Bewusst ohne Anmeldung erreichbar. Jede Aenderung hier ist eine
# Sicherheitsentscheidung.
OEFFENTLICH = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/request-link"),
    ("POST", "/api/auth/verify"),
    ("POST", "/api/auth/verify-supabase"),
    ("GET", "/api/exercises/images/{token}"),   # <img src> sendet keinen Header; 128-Bit-Token
    ("GET", "/api/pay/preise"),                 # Startseite/AGB, keine Geheimnisse
    ("POST", "/api/pay/webhook"),               # Stripe; geschuetzt durch Signatur
}


def _abhaengigkeiten(dep) -> set[str]:
    namen = set()
    for d in dep.dependencies:
        if d.call is not None:
            namen.add(getattr(d.call, "__name__", ""))
        namen |= _abhaengigkeiten(d)
    return namen


def _routen():
    for r in app.routes:
        if isinstance(r, APIRoute):
            for m in sorted(r.methods):
                yield m, r.path, _abhaengigkeiten(r.dependant)


ROUTEN = list(_routen())


def _pfad(path: str, wert: str = "999999") -> str:
    return re.sub(r"\{[^}]+\}", wert, path)


def _rufe(client: TestClient, methode: str, pfad: str, headers=None, json=None):
    return client.request(methode, pfad, headers=headers or {}, json=json)


def test_liste_ist_vollstaendig():
    """Jeder oeffentliche Eintrag gibt es wirklich – sonst ist die Liste veraltet."""
    vorhanden = {(m, p) for m, p, _ in ROUTEN}
    assert OEFFENTLICH <= vorhanden, OEFFENTLICH - vorhanden
    assert len(ROUTEN) >= 60  # Schutz gegen einen leeren Durchlauf


@pytest.mark.parametrize("methode,pfad,deps", ROUTEN, ids=[f"{m} {p}" for m, p, _ in ROUTEN])
def test_ohne_anmeldung_kein_zugriff(client, methode, pfad, deps):
    if (methode, pfad) in OEFFENTLICH:
        assert "get_current_user" not in deps, f"{methode} {pfad} steht in OEFFENTLICH, verlangt aber Anmeldung"
        return
    assert "get_current_user" in deps, (
        f"{methode} {pfad} verlangt keine Anmeldung. Absicht? Dann in OEFFENTLICH eintragen.")
    r = _rufe(client, methode, _pfad(pfad), json={})
    assert r.status_code == 401, f"{methode} {pfad} ohne Anmeldung: {r.status_code} {r.text[:200]}"


def test_admin_bereich_nur_fuer_admins(client):
    schueler = register(client, "kind@test.ch")
    admin_routen = [(m, p) for m, p, d in ROUTEN if "require_admin" in d]
    assert len(admin_routen) >= 15
    for m, p in admin_routen:
        r = _rufe(client, m, _pfad(p), headers=schueler, json={})
        assert r.status_code == 403, f"Schueler erreicht {m} {p}: {r.status_code}"
    # Alles unter /api/admin muss require_admin haben – auch kuenftige Routen
    for m, p, d in ROUTEN:
        if p.startswith("/api/admin"):
            assert "require_admin" in d, f"{m} {p} liegt im Admin-Bereich ohne require_admin"


def test_rollen_trennung(client):
    schueler = register(client, "kind@test.ch")
    eltern = register(client, "mami@test.ch", role="parent")
    for m, p, d in ROUTEN:
        if "require_student" in d:
            r = _rufe(client, m, _pfad(p), headers=eltern, json={})
            assert r.status_code == 403, f"Eltern-Konto erreicht Schueler-Route {m} {p}: {r.status_code}"
        if "require_parent" in d:
            r = _rufe(client, m, _pfad(p), headers=schueler, json={})
            assert r.status_code == 403, f"Schueler erreicht Eltern-Route {m} {p}: {r.status_code}"


# Muell, wie ihn ein kaputter Browser, ein Bot oder ein neugieriges Kind schickt
MUELL = [
    {},
    {"text": None, "name": 12, "email": [], "topic_id": "abc", "intervall": {"x": 1}},
    {"text": "x" * 20000, "name": "x" * 5000, "email": "a" * 400 + "@x.ch", "paket": "gibtsnicht"},
    {"text": "'; DROP TABLE users; --", "name": "<script>alert(1)</script>", "student_id": -1},
    [1, 2, 3],
    "nur ein String",
]
PFAD_WERTE = ["999999", "0", "-1", "abc"]


@pytest.mark.parametrize("wer", ["schueler", "admin", "eltern", "anonym"])
def test_muell_fuehrt_nie_zu_einem_absturz(client, wer):
    headers = {}
    if wer == "schueler":
        headers = register(client, "kind@test.ch")
    elif wer == "eltern":
        headers = register(client, "mami@test.ch", role="parent")
    elif wer == "admin":
        headers = register_pw(client, "chef@test.ch")
        make_admin("chef@test.ch")
    abstuerze = []
    with TestClient(app, raise_server_exceptions=False) as c:
        for m, p, _ in ROUTEN:
            if (m, p) == ("POST", "/api/auth/delete-account"):
                continue  # wuerde das Testkonto fuer die restlichen Aufrufe loeschen
            for wert in PFAD_WERTE if "{" in p else ["-"]:
                for body in MUELL:
                    r = c.request(m, _pfad(p, wert), headers=headers, json=body)
                    if r.status_code == 500 or (r.status_code >= 500 and r.status_code not in (502, 503)):
                        abstuerze.append(f"{m} {_pfad(p, wert)} body={str(body)[:40]} -> {r.status_code}")
    assert not abstuerze, "Abstuerze:\n" + "\n".join(abstuerze[:30])


def test_fremde_daten_bleiben_fremd(client):
    """Zweites Konto probiert die IDs des ersten auf jeder Schueler-Route."""
    a = register(client, "a@test.ch")
    b = register(client, "b@test.ch")
    topic = client.post("/api/topics", headers=a, json={"name": "Brüche", "learning_goals": "Kürzen"}).json()
    ex = client.post("/api/exercises", headers=a, json={"text": "3x+5=20", "topic_id": topic["id"]}).json()
    att = client.post(f"/api/exercises/{ex['id']}/attempts", headers=a).json()["attempt"]
    ids = {"topic_id": topic["id"], "exercise_id": ex["id"], "attempt_id": att["id"]}

    lecks = []
    geprueft = 0
    for m, p, d in ROUTEN:
        if "require_student" not in d or not any("{" + k + "}" in p for k in ids):
            continue
        pfad = p
        for k, v in ids.items():
            pfad = pfad.replace("{" + k + "}", str(v))
        if "{" in pfad:
            continue
        r = client.request(m, pfad, headers=b, json={})
        geprueft += 1
        if r.status_code < 400:
            lecks.append(f"{m} {pfad} -> {r.status_code}")
    assert geprueft >= 10, f"nur {geprueft} Routen geprueft – Test greift nicht mehr"
    assert not lecks, "Konto B kommt an Daten von Konto A:\n" + "\n".join(lecks)
    # Und A selbst kommt weiterhin dran
    assert client.get(f"/api/attempts/{att['id']}", headers=a).status_code == 200
