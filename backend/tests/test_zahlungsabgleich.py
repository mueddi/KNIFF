"""Zahlungs-Abgleich Stripe <-> payments (app/services/abgleich.py und
scripts/zahlungsabgleich.py)."""
import importlib.util
import os
import time

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import Payment
from app.services.abgleich import KARENZ_SEKUNDEN, abweichungen, kaeufe_aus_stripe

from .test_abo_webhooks import _Resp, _me, _post_event, _sub_obj, _ts, stripe  # noqa: F401 (Fixture)
from .test_library import register_pw
from .test_pay import enable_payments

ALT = int(time.time()) - 2 * KARENZ_SEKUNDEN


def _paket(sid="cs_p", betrag=900, **extra):
    return dict({"id": sid, "mode": "payment", "status": "complete", "payment_status": "paid",
                 "amount_total": betrag, "created": ALT}, **extra)


def _abo_session(sid="cs_a", invoice="in_1"):
    return {"id": sid, "mode": "subscription", "status": "complete", "payment_status": "paid",
            "amount_total": 990, "invoice": invoice, "created": ALT}


def _rechnung(iid="in_1", betrag=990, neue_form=True, **extra):
    inv = {"id": iid, "status": "paid", "amount_paid": betrag, "created": ALT}
    if neue_form:
        inv["parent"] = {"subscription_details": {"subscription": "sub_1"}}
    else:
        inv["subscription"] = "sub_1"
    return dict(inv, **extra)


def test_kaeufe_aus_stripe_zaehlt_jeden_kauf_einmal():
    kaeufe = kaeufe_aus_stripe(
        [_paket(), _abo_session(), _paket("cs_offen", payment_status="unpaid"), _paket("cs_x", status="expired")],
        [_rechnung(), _rechnung("in_2", neue_form=False),
         _rechnung("in_null", betrag=0),                                   # Gratis-Rechnung
         {"id": "in_einzeln", "status": "paid", "amount_paid": 500, "created": ALT}],  # kein Abo
    )
    assert sorted((k.kennung, k.art, k.betrag_rappen) for k in kaeufe) == [
        ("cs_p", "paket", 900), ("in_1", "abo", 990), ("in_2", "abo", 990)]


def test_abweichungen():
    kaeufe = kaeufe_aus_stripe([_paket(), _paket("cs_frisch", created=int(time.time()))], [_rechnung()])
    jetzt = int(time.time())
    assert abweichungen(kaeufe, {"cs_p": 900, "in_1": 990, "cs_frisch": 900}, jetzt) == []
    fehlt = abweichungen(kaeufe, {"in_1": 990}, jetzt)
    assert [(a.kauf.kennung, a.grund) for a in fehlt] == [("cs_p", "fehlt")]  # cs_frisch: noch in der Karenz
    betrag = abweichungen(kaeufe, {"cs_p": 200, "in_1": 990}, jetzt)
    assert [(a.kauf.kennung, a.grund, a.verbucht_rappen) for a in betrag] == [("cs_p", "betrag", 200)]


def test_echte_webhook_buchungen_passen_zum_abgleich(client, stripe, monkeypatch):
    """Die Kennungen im Abgleich muessen genau die sein, die der Webhook
    schreibt – sonst meldet der Abgleich jeden Tag falschen Alarm oder, schlimmer,
    uebersieht echte Luecken. Hier laufen Paket, Abo-Abschluss und Verlaengerung
    ueber den echten Webhook, danach muss der Abgleich leer sein."""
    enable_payments(monkeypatch)
    monkeypatch.setattr(settings, "abo_enabled", True)
    _, antworten = stripe
    headers = register_pw(client, "mia@test.ch")
    uid = _me(client, headers)["id"]
    antworten[("GET", "/v1/subscriptions/sub_1")] = _Resp(_sub_obj("sub_1", uid, 30))
    paket = _paket(client_reference_id=str(uid), currency="chf", metadata={"user_id": str(uid), "package": "starter"})
    abo = dict(_abo_session(), client_reference_id=str(uid), subscription="sub_1", customer="cus_1",
               metadata={"user_id": str(uid), "intervall": "monat"})
    erste = _rechnung(lines={"data": [{"period": {"end": _ts(30)}}]})
    zweite = _rechnung("in_2", lines={"data": [{"period": {"end": _ts(60)}}]})
    _post_event(client, "checkout.session.completed", paket, event_id="e1")
    _post_event(client, "checkout.session.completed", abo, event_id="e2")
    _post_event(client, "invoice.paid", erste, event_id="e3")
    _post_event(client, "invoice.paid", zweite, event_id="e4")
    with SessionLocal() as db:
        verbucht = {p.session_id: p.amount_rappen for p in db.query(Payment).all()}
    kaeufe = kaeufe_aus_stripe([paket, abo], [erste, zweite])
    assert len(kaeufe) == 3
    assert abweichungen(kaeufe, verbucht, int(time.time())) == []


def _skript():
    pfad = os.path.join(os.path.dirname(__file__), "..", "scripts", "zahlungsabgleich.py")
    spec = importlib.util.spec_from_file_location("zahlungsabgleich", pfad)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Seite:
    def __init__(self, daten):
        self._d = daten

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": self._d, "has_more": False}


@pytest.mark.parametrize("verbucht, code", [(True, 0), (False, 1)])
def test_skript_meldet_fehlende_buchung(client, monkeypatch, capsys, verbucht, code):
    skript = _skript()
    antworten = {"/v1/checkout/sessions": [_paket()], "/v1/invoices": []}
    monkeypatch.setattr(skript.httpx, "get", lambda url, **kw: _Seite(antworten[url.replace("https://api.stripe.com", "")]))
    monkeypatch.setenv("STRIPE_ABGLEICH_KEY", "rk_live_nur_im_test")
    monkeypatch.setenv("DATABASE_URL", os.environ["DATABASE_URL"])
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    register_pw(client, "mia@test.ch")
    if verbucht:
        with SessionLocal() as db:
            from app.models import User
            uid = db.query(User).one().id
            db.add(Payment(user_id=uid, session_id="cs_p", amount_rappen=900, tokens=900))
            db.commit()
    assert skript.main() == code
    aus = capsys.readouterr().out
    assert ("NICHT verbucht" in aus) is (not verbucht)


def test_skript_verweigert_test_schluessel(monkeypatch, capsys):
    """Mit einem Test-Schluessel wuerde es das falsche Stripe-Konto vergleichen
    und jeden Tag «alles in Ordnung» melden."""
    skript = _skript()
    monkeypatch.setenv("STRIPE_ABGLEICH_KEY", "sk_test_abc")
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    assert skript.main() == 1
    assert "kein Live-Schluessel" in capsys.readouterr().out
