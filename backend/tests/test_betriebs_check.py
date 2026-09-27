"""Betriebs-Check (scripts/betriebs_check.py): jede Pruefung einzeln, ohne Netz.

Jeder Fall hier ist einer, der bis Ende September wirklich passiert ist –
der Check muss ihn als Fehler melden."""
import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

_pfad = os.path.join(os.path.dirname(__file__), "..", "scripts", "betriebs_check.py")
_spec = importlib.util.spec_from_file_location("betriebs_check", _pfad)
bc = importlib.util.module_from_spec(_spec)
sys.modules["betriebs_check"] = bc  # dataclass braucht das Modul in sys.modules
_spec.loader.exec_module(bc)

JETZT = datetime(2026, 9, 27, 6, 0, tzinfo=timezone.utc)
ALLE = list(bc.WEBHOOK_EREIGNISSE)


def test_oeffentliches_repository_ist_ein_fehler():
    assert bc.pruefe_repo({"private": False}).stufe == "fehler"
    assert bc.pruefe_repo({"private": True}).stufe == "ok"
    assert bc.pruefe_repo(None).stufe == "warnung"


def test_fehlendes_backup_passwort_ist_ein_fehler_optionales_nur_warnung():
    gesetzt = {name: True for name in bc.SECRETS}
    assert all(b.stufe == "ok" for b in bc.pruefe_secrets(gesetzt))
    gesetzt["BACKUP_PASSWORD"] = False
    gesetzt["VERCEL_AUTOMATION_BYPASS_SECRET"] = False
    stufen = {b.bereich: b.stufe for b in bc.pruefe_secrets(gesetzt)}
    assert stufen["Secret BACKUP_PASSWORD"] == "fehler"
    assert stufen["Secret VERCEL_AUTOMATION_BYPASS_SECRET"] == "warnung"


@pytest.mark.parametrize("endpunkte, stufe, stichwort", [
    ([], "fehler", "kein Endpunkt"),                                       # 25.9.: nie eingerichtet
    ([{"url": "https://schrittweise-2-0.vercel.app/api/pay/webhook", "status": "enabled",
       "enabled_events": ALLE}], "fehler", "kein Endpunkt"),              # alte Adresse
    ([{"url": bc.WEBHOOK_URL, "status": "disabled", "enabled_events": ALLE}], "fehler", "deaktiviert"),
    ([{"url": bc.WEBHOOK_URL, "status": "enabled", "enabled_events": ALLE[:4]}], "fehler", "charge.refunded"),
    ([{"url": bc.WEBHOOK_URL, "status": "enabled", "enabled_events": ALLE}], "ok", "alle 6"),
    ([{"url": bc.WEBHOOK_URL + "/", "status": "enabled", "enabled_events": ["*"]}], "ok", "alle Ereignisse"),
    (None, "warnung", "nicht prüfbar"),
])
def test_webhook(endpunkte, stufe, stichwort):
    b = bc.pruefe_webhook(endpunkte)
    assert b.stufe == stufe and stichwort in b.text


@pytest.mark.parametrize("cfg, stufe", [
    ({"site_url": "https://schrittweise-2-0.vercel.app", "uri_allow_list": ""}, "fehler"),  # bis 25.9.
    ({"site_url": "https://kniff.app", "uri_allow_list": "http://localhost:3000"}, "fehler"),
    ({"site_url": "https://kniff.app/", "uri_allow_list": "https://kniff.app/**"}, "ok"),
    (None, "warnung"),
])
def test_supabase_mail_links(cfg, stufe):
    assert bc.pruefe_supabase_auth(cfg).stufe == stufe


def test_dns():
    www, mx = bc.pruefe_dns([], [])                       # 25.9.: www fehlte, MX fehlt bis heute
    assert (www.stufe, mx.stufe) == ("fehler", "warnung")
    www, mx = bc.pruefe_dns(["cname.vercel-dns.com.", "76.76.21.21"], ["10 mx.example."])
    assert (www.stufe, mx.stufe) == ("ok", "ok")


def test_health():
    assert bc.pruefe_health(200, {"status": "ok"}).stufe == "ok"
    assert bc.pruefe_health(503, {"status": "degraded"}).stufe == "fehler"
    assert bc.pruefe_health(None, None).stufe == "fehler"


def _lauf(tage_her, ergebnis="success", status="completed"):
    return {"status": status, "conclusion": ergebnis, "html_url": "https://github.com/x",
            "created_at": (JETZT - timedelta(days=tage_her)).isoformat().replace("+00:00", "Z")}


def test_roter_deploy_ist_ein_fehler():
    # 9.9.: Lauf 116 rot, zwoelf Tage unbemerkt
    assert bc.pruefe_letzten_lauf("Deploy", [_lauf(3, "failure"), _lauf(10)], JETZT).stufe == "fehler"
    # ein laufender Deploy zaehlt nicht – der letzte abgeschlossene entscheidet
    assert bc.pruefe_letzten_lauf("Deploy", [_lauf(0, None, "in_progress"), _lauf(1)], JETZT).stufe == "ok"


def test_alte_sicherung_ist_ein_fehler():
    assert bc.pruefe_letzten_lauf("Sicherung", [_lauf(9)], JETZT, max_alter_tage=8).stufe == "fehler"
    assert bc.pruefe_letzten_lauf("Sicherung", [_lauf(6)], JETZT, max_alter_tage=8).stufe == "ok"
    assert bc.pruefe_letzten_lauf("Sicherung", [], JETZT).stufe == "fehler"
    assert bc.pruefe_letzten_lauf("Sicherung", None, JETZT).stufe == "warnung"


def test_bericht_zeigt_fehler_zuerst_und_keine_werte():
    text = bc.bericht([bc.Befund("A", "ok", "gut"), bc.Befund("B", "fehler", "schlecht | kaputt")])
    assert text.index("❌") < text.index("✅")
    assert "1 Fehler" in text and "schlecht / kaputt" in text


def test_main_ohne_netz_meldet_und_wird_rot(monkeypatch, capsys):
    """Ganzer Ablauf mit abgeschaltetem Netz: kein Absturz, klare Meldungen,
    Exit 1 (kniff.app nicht erreichbar, Secrets fehlen)."""
    def kein_netz(*a, **kw):
        raise bc.httpx.ConnectError("kein Netz im Test")
    monkeypatch.setattr(bc.httpx, "get", kein_netz)
    for name in bc.SECRETS:
        monkeypatch.delenv(f"HAT_{name}", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert bc.main() == 1
    aus = capsys.readouterr().out
    assert "::error::kniff.app: nicht erreichbar" in aus
    assert "::error::Secret BACKUP_PASSWORD" in aus
