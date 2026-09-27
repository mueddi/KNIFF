"""Erstattung und Streitfall: Tokens eines Pakets gehen wieder weg.

Vorher kannte der Webhook nur Kauf, Rechnung und Abo-Aenderungen – wer ein
Paket erstattet bekam oder die Zahlung bei der Bank anfocht, behielt die
Tokens, und der Betreiber erfuhr vom Streitfall nichts."""
import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import StripeEvent, TokenAdjustment, User
from app.routers import pay

from .test_abo_webhooks import _Resp, _event, _me, _post_event, stripe  # noqa: F401 (Fixture)
from .test_library import register_pw
from .test_pay import enable_payments, signed_headers

SUCHE = ("GET", "/v1/checkout/sessions?payment_intent=pi_1")


ALARME: list[str] = []


@pytest.fixture(autouse=True)
def zahlung_an(monkeypatch):
    enable_payments(monkeypatch)
    monkeypatch.setattr(settings, "abo_enabled", True)
    # Alarm direkt mitschreiben (wie test_abo_webhooks): die eigene DB-Sitzung
    # des Alarms wartet auf SQLite sonst auf die offene Webhook-Transaktion.
    ALARME.clear()
    monkeypatch.setattr(pay.alert, "notify", lambda kind, detail, key=None: ALARME.append(f"{kind}: {detail}"))


def _guthaben(email="mia@test.ch"):
    with SessionLocal() as db:
        return db.query(User).filter(User.email == email).one().token_balance


def _alarme():
    return [a for a in ALARME if a.startswith("zahlung: ")]


def _paket_gekauft(client, stripe, tokens=900):
    """Kauf ueber den echten Webhook-Weg; Stripe kennt danach die Session zur Zahlung."""
    _, antworten = stripe
    headers = register_pw(client, "mia@test.ch")
    uid = _me(client, headers)["id"]
    paket = {200: "schnupper", 900: "starter", 1900: "power"}[tokens]
    _post_event(client, "checkout.session.completed", {
        "id": "cs_paket", "mode": "payment", "payment_status": "paid", "amount_total": tokens,
        "currency": "chf", "client_reference_id": str(uid), "metadata": {"user_id": str(uid), "package": paket},
    }, event_id="evt_kauf")
    assert _guthaben() == tokens
    antworten[SUCHE] = _Resp({"data": [{"id": "cs_paket", "mode": "payment"}]})


def _charge(erstattet):
    return {"id": "ch_1", "payment_intent": "pi_1", "amount": 900, "amount_refunded": erstattet}


def test_volle_erstattung_nimmt_die_tokens_weg(client, stripe):
    _paket_gekauft(client, stripe)
    _post_event(client, "charge.refunded", _charge(900), event_id="evt_r1")
    assert _guthaben() == 0
    with SessionLocal() as db:
        buchung = db.query(TokenAdjustment).one()
        assert buchung.tokens == -900 and "ch_1" in buchung.reason and "Erstattung" in buchung.reason


def test_teil_und_folge_erstattung_buchen_nur_die_differenz(client, stripe):
    _paket_gekauft(client, stripe)
    _post_event(client, "charge.refunded", _charge(300), event_id="evt_r1")
    assert _guthaben() == 600
    _post_event(client, "charge.refunded", _charge(300), event_id="evt_r1")   # Stripe-Wiederholung
    _post_event(client, "charge.refunded", _charge(300), event_id="evt_r1b")  # gleicher Stand, neues Ereignis
    assert _guthaben() == 600
    _post_event(client, "charge.refunded", _charge(900), event_id="evt_r2")   # Rest erstattet
    assert _guthaben() == 0


def test_schon_verbrauchte_tokens_druecken_nicht_unter_null(client, stripe):
    _paket_gekauft(client, stripe)
    with SessionLocal() as db:
        db.query(User).filter(User.email == "mia@test.ch").one().token_balance = 100
        db.commit()
    _post_event(client, "charge.refunded", _charge(900), event_id="evt_r1")
    assert _guthaben() == 0


def test_streitfall_meldet_und_nimmt_tokens_weg(client, stripe):
    _paket_gekauft(client, stripe)
    _post_event(client, "charge.dispute.created", {"id": "dp_1", "charge": "ch_1", "payment_intent": "pi_1",
                                                   "amount": 900}, event_id="evt_d1")
    assert _guthaben() == 0
    assert any("angefochten" in a and "dp_1" in a for a in _alarme())
    # Wird danach auch noch erstattet, geht nichts doppelt weg
    _post_event(client, "charge.refunded", _charge(900), event_id="evt_r1")
    with SessionLocal() as db:
        assert sum(b.tokens for b in db.query(TokenAdjustment).all()) == -900


def test_erstattete_abo_zahlung_meldet_nur(client, stripe):
    _, antworten = stripe
    headers = register_pw(client, "mia@test.ch")
    with SessionLocal() as db:
        db.query(User).filter(User.email == "mia@test.ch").one().token_balance = 50
        db.commit()
    antworten[SUCHE] = _Resp({"data": [{"id": "cs_abo", "mode": "subscription"}]})
    _post_event(client, "charge.refunded", _charge(990), event_id="evt_r1")
    assert _guthaben() == 50
    assert any("Abo-Zahlung" in a for a in _alarme())
    assert headers  # Konto existiert, nichts abgezogen


def test_unbekannte_zahlung_meldet_nur(client, stripe):
    _, antworten = stripe
    register_pw(client, "mia@test.ch")
    antworten[SUCHE] = _Resp({"data": []})
    _post_event(client, "charge.refunded", _charge(900), event_id="evt_r1")
    assert any("keinem Token-Paket" in a for a in _alarme())


def test_stripe_nicht_erreichbar_laesst_das_ereignis_offen(client, stripe):
    """Kann die App nicht nachfragen, darf das Ereignis nicht als erledigt
    gelten – sonst schickt Stripe es nie wieder und die Tokens bleiben."""
    _paket_gekauft(client, stripe)
    _, antworten = stripe
    antworten[SUCHE] = _Resp({"error": "kaputt"}, status=500)
    payload = _event("charge.refunded", _charge(900), "evt_r1")
    r = client.post("/api/pay/webhook", content=payload, headers=signed_headers(payload))
    assert r.status_code >= 500
    with SessionLocal() as db:
        assert db.query(StripeEvent).filter(StripeEvent.id == "evt_r1").count() == 0
    assert _guthaben() == 900
    # Stripe versucht es spaeter nochmal - dann klappt es
    antworten[SUCHE] = _Resp({"data": [{"id": "cs_paket", "mode": "payment"}]})
    _post_event(client, "charge.refunded", _charge(900), event_id="evt_r1")
    assert _guthaben() == 0
