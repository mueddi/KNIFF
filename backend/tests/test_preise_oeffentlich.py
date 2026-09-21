"""Oeffentliche Preisauskunft fuer Startseite und AGB: /api/pay/preise."""
from app.config import settings


def test_preise_ohne_anmeldung_und_ohne_geheimnisse(client):
    r = client.get("/api/pay/preise")
    assert r.status_code == 200
    d = r.json()
    assert d["abo_enabled"] is False
    assert d["plus_name"] == "Kniff Plus"
    assert d["monat_rappen"] == 990 and d["jahr_rappen"] == 8900
    assert d["trial_tasks"] == 10 and d["free_monthly_tokens"] == 50
    assert d["plus_tokens_monat"] == 600
    assert [p["key"] for p in d["pakete"]] == ["schnupper", "starter", "power"]
    assert set(d) == {"abo_enabled", "zahlung", "plus_name", "monat_rappen", "jahr_rappen", "trial_tasks",
                      "plus_tokens_monat", "pakete", "free_monthly_tokens"}


def test_preise_folgen_dem_schalter(client, monkeypatch):
    monkeypatch.setattr(settings, "abo_enabled", True)
    monkeypatch.setattr(settings, "plus_preis_monat_rappen", 1290)
    d = client.get("/api/pay/preise").json()
    assert d["abo_enabled"] is True and d["monat_rappen"] == 1290
