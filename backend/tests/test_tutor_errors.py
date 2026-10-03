"""KI-Ausfaelle: ehrliche Meldung statt stillem Mock-Fallback."""
import logging
import types

from app.config import settings
from app.services import tutor
from app.services.sympy_verifier import Verification

_STEP = tutor.LadderStep("stuck", 1, 0, False, False)
_VER = Verification("unknown", "test")


class _FailingCtx:
    """Context-Manager, der beim Betreten wirft (API nicht erreichbar)."""

    def __enter__(self):
        raise RuntimeError("api down")

    def __exit__(self, *args):
        return False


class _MidStream:
    """Stream, der nach einem Chunk abbricht."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @property
    def text_stream(self):
        def gen():
            yield "Hallo, schau mal: "
            raise RuntimeError("connection reset")

        return gen()


class _OkStream:
    """Stream, der sauber antwortet."""

    def __init__(self, text="Alles gut, hier dein Tipp."):
        self._text = text

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @property
    def text_stream(self):
        return iter([self._text])

    @property
    def current_message_snapshot(self):
        return types.SimpleNamespace(usage=None)

    def get_final_message(self):
        return types.SimpleNamespace(usage=None, stop_reason="end_turn")


def _fake_anthropic(ctx, versuche=None):
    """``ctx``: fester Context-Manager ODER eine Funktion model -> Context-Manager.

    ``versuche``: optionale Liste, in der die angefragten Modelle landen –
    damit ein Test belegen kann, dass wirklich gewechselt wurde.
    """
    class _Messages:
        def stream(self, **kwargs):
            if versuche is not None:
                versuche.append(kwargs.get("model"))
            return ctx(kwargs.get("model")) if callable(ctx) else ctx

    class _Client:
        # timeout/max_retries kommen jetzt mit – die Attrappe muss sie schlucken
        def __init__(self, api_key, **kwargs):
            self.messages = _Messages()

    return types.SimpleNamespace(Anthropic=_Client)


def _run(monkeypatch, ctx, versuche=None, usage_out=None):
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    monkeypatch.setattr(tutor, "anthropic", _fake_anthropic(ctx, versuche))
    return "".join(tutor.stream_reply([], _STEP, _VER, "3x = 9", "3*x = 9",
                                      usage_out=usage_out))


def test_vordenk_schalter_geht_als_extra_body_mit(monkeypatch):
    """Im Vercel-Log der Vorschau (7.9.): «Messages.stream() got an unexpected
    keyword argument 'thinking'». Das SDK 0.42 kennt das Feld nicht – jeder
    Sonnet-Aufruf des Tutors scheiterte seit dem 26.7. VOR der API und wich
    still auf Haiku aus. Als extra_body kommt das Feld in jeder Version an."""
    gesehen = []

    class _Messages:
        def stream(self, **kwargs):
            gesehen.append(kwargs)
            return _OkStream()

    class _Client:
        def __init__(self, api_key, **kwargs):
            self.messages = _Messages()

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    monkeypatch.setattr(tutor, "anthropic", types.SimpleNamespace(Anthropic=_Client))
    stufe4 = tutor.LadderStep("plea", 4, 2, False, True)      # geht ans starke Modell
    "".join(tutor.stream_reply([], stufe4, _VER, "Beweise: ...", None))
    assert gesehen[0]["model"] == settings.anthropic_model_smart
    assert "thinking" not in gesehen[0]
    assert gesehen[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_ausweich_meldung_nennt_den_fehler(client, monkeypatch):
    """«Modell nicht verfuegbar» sah bei Ueberlastung und bei einem
    Programmierfehler gleich aus – 44 Tage lang wich der Tutor bei jedem
    Sonnet-Aufruf aus, und die Meldung sagte «es ist nichts ausgefallen».
    Der Fehlertyp gehoert in die Meldung, damit man den Unterschied sieht."""
    from app.database import SessionLocal
    from app.models import Alert
    from app.services import alert as alert_svc

    alert_svc._last_sent.clear()
    versuche = []
    # _STEP geht ans Standardmodell; das faellt aus, das starke antwortet
    out = _run(monkeypatch,
               lambda m: _FailingCtx() if m == settings.anthropic_model_default else _OkStream(),
               versuche)
    assert "Alles gut" in out
    assert versuche == [settings.anthropic_model_default, settings.anthropic_model_smart]
    with SessionLocal() as db:
        meldung = db.query(Alert).filter(Alert.kind == "ki").order_by(Alert.id.desc()).first()
    assert meldung is not None
    assert "RuntimeError: api down" in meldung.detail
    assert "ausgewichen" in meldung.detail


def test_api_error_yields_honest_message(monkeypatch, caplog):
    with caplog.at_level(logging.ERROR, logger="schrittweise.tutor"):
        out = _run(monkeypatch, _FailingCtx())
    assert "technische Probleme" in out
    # Betreiber sieht es im Log – inkl. Modell, damit «nur Sonnet ueberlastet»
    # von «alles down» unterscheidbar ist
    assert "Anthropic-Stream mit" in caplog.text and "fehlgeschlagen" in caplog.text


def test_mid_stream_abort_gets_marker(monkeypatch):
    out = _run(monkeypatch, _MidStream())
    assert out.startswith("Hallo, schau mal: ")  # Teiltext bleibt erhalten
    assert "Verbindung ist mittendrin abgebrochen" in out  # aber klar markiert


def test_mock_only_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    out = "".join(tutor.stream_reply([], _STEP, _VER, "3x = 9", "3*x = 9"))
    assert out  # Mock antwortet weiterhin (lokale Entwicklung ohne Key)
    assert "technische Probleme" not in out


def test_ki_failure_writes_alert(client, monkeypatch):
    """KI-Ausfall landet als Stoerung im Admin-Protokoll (gedrosselt 1/h)."""
    from app.database import SessionLocal
    from app.models import Alert
    from app.services import alert as alert_svc

    alert_svc._last_sent.clear()
    _run(monkeypatch, _FailingCtx())
    with SessionLocal() as db:
        rows = db.query(Alert).all()
        assert len(rows) == 1
        assert rows[0].kind == "ki"
        assert "api down" in rows[0].detail

    # Drossel: zweiter Fehler in derselben Stunde erzeugt keine zweite Zeile
    _run(monkeypatch, _FailingCtx())
    with SessionLocal() as db:
        assert db.query(Alert).count() == 1


def test_rechenfehler_in_tutorantwort_wird_korrigiert(client, monkeypatch):
    """Falsche Zahlen-Gleichung in der Antwort -> Korrektur-Chunk im Stream,
    in der gespeicherten Message und Alarm fuer den Admin."""
    from app.database import SessionLocal
    from app.models import Alert
    from app.services import alert as alert_service, tutor
    from .test_library import register_pw

    alert_service._last_sent.clear()

    def fake_stream(*args, **kwargs):
        yield "Genau richtig! $2 \\cdot 3 = 5$"

    monkeypatch.setattr(tutor, "stream_reply", fake_stream)
    headers = register_pw(client, "korrektur@test.ch")
    ex = client.post("/api/exercises", headers=headers, json={"text": "3x + 5 = 20"}).json()
    aid = client.post(f"/api/exercises/{ex['id']}/attempts", headers=headers).json()["attempt"]["id"]

    with client.stream("POST", f"/api/attempts/{aid}/chat", headers=headers,
                       json={"text": "ich probiere"}) as r:
        reply = "".join(r.iter_text())
    assert "Korrektur" in reply and "6" in reply

    state = client.get(f"/api/attempts/{aid}", headers=headers).json()
    tutor_msgs = [m["text"] for m in state["messages"] if m["role"] == "tutor"]
    assert any("Korrektur" in t for t in tutor_msgs)

    with SessionLocal() as db:
        assert any(a.kind == "ki-qualitaet" for a in db.query(Alert).all())


def test_vordenken_wird_beim_starken_modell_abgeschaltet():
    """Sonnet 5 denkt sonst vor – und diese Tokens zaehlen gegen max_tokens.

    Real gemessen: 700 Output-Tokens verbraucht, null Zeichen Text beim
    Schueler (Nachricht 344), davor 323 Zeichen mitten in der Formel
    abgeschnitten (Nachricht 342). Haiku kennt den Schalter nicht.
    """
    from app.config import settings
    from app.services.tutor import _thinking_param

    assert _thinking_param(settings.anthropic_model_smart) == {"type": "disabled"}
    assert _thinking_param(settings.anthropic_model_default) is None


# ---- Ausfall-Schutz: Ausweich-Modell, Zeitlimit, Hilfe-Stufe ----

def test_ueberlastetes_modell_weicht_auf_das_andere_aus(monkeypatch):
    """Der haeufigste echte Fehler ist kein Totalausfall, sondern «Modell
    ueberlastet» – und der trifft immer nur EIN Modell. Dann muss das Kind
    trotzdem eine normale Antwort bekommen, nicht eine Fehlermeldung."""
    versuche = []

    def ctx_fuer(model):
        return _FailingCtx() if model == settings.anthropic_model_default else _OkStream()

    out = _run(monkeypatch, ctx_fuer, versuche)
    assert "Alles gut" in out                    # Kind bekommt eine echte Antwort
    assert "technische Probleme" not in out
    assert versuche == [settings.anthropic_model_default, settings.anthropic_model_smart]


def test_kein_wechsel_wenn_schon_text_beim_kind_ist(monkeypatch):
    """Sonst bekaeme das Kind zwei verschiedene Antworten durcheinander."""
    versuche = []
    out = _run(monkeypatch, lambda _m: _MidStream(), versuche)
    assert out.startswith("Hallo, schau mal: ")
    assert "Verbindung ist mittendrin abgebrochen" in out
    assert len(versuche) == 1, "nach begonnenem Text darf nicht gewechselt werden"


def test_kompletter_ausfall_meldet_fehler_zurueck(monkeypatch):
    """Signal an den Aufrufer: dieser Turn hat KEINE Hilfe geliefert."""
    usage_out = {}
    versuche = []
    out = _run(monkeypatch, lambda _m: _FailingCtx(), versuche, usage_out)
    assert "technische Probleme" in out
    assert usage_out.get("fehler") is True
    assert len(versuche) == 2, "beide Modelle muessen probiert worden sein"
    assert "usage" not in usage_out, "ohne Antwort darf nichts verrechnet werden"


def test_verlauf_wird_in_bloecken_gekuerzt_nicht_jeden_turn():
    """In der Vorschau belegt: ab 12 Nachrichten wurde der Verlauf jeden Turn
    neu zugeschnitten, der Praefix verschob sich, und der Verlaufs-Cache traf
    nie mehr (Lesen blieb bei 7964 Token, Schreiben 650–830 pro Turn).
    Jetzt: bis HISTORY_MAX unveraendert, dann auf HISTORY_LIMIT – der Praefix
    bleibt zwischen zwei Schnitten identisch."""
    def verlauf(n):
        return [{"role": "tutor" if i % 2 == 0 else "student", "text": f"m{i}"} for i in range(n)]

    assert tutor.HISTORY_MAX > tutor.HISTORY_LIMIT
    unveraendert = tutor._gekuerzter_verlauf(verlauf(tutor.HISTORY_MAX))
    assert [m["text"] for m in unveraendert] == [f"m{i}" for i in range(tutor.HISTORY_MAX)]

    erster_schnitt = tutor._gekuerzter_verlauf(verlauf(tutor.HISTORY_MAX + 1))
    assert erster_schnitt[0]["text"] == "m0"                 # Eroeffnung bleibt
    assert len(erster_schnitt) <= tutor.HISTORY_MAX
    # Fuenf Turns spaeter: der Anfang ist noch derselbe – nur hinten kam dazu
    spaeter = tutor._gekuerzter_verlauf(verlauf(tutor.HISTORY_MAX + 11))
    assert [m["text"] for m in spaeter[:len(erster_schnitt)]] == [m["text"] for m in erster_schnitt]
    assert len(spaeter) <= tutor.HISTORY_MAX
    # Erst beim naechsten vollen Block verschiebt sich der Anfang wieder
    zweiter_schnitt = tutor._gekuerzter_verlauf(verlauf(tutor.HISTORY_MAX + 13))
    assert zweiter_schnitt[1]["text"] != erster_schnitt[1]["text"]
    assert len(zweiter_schnitt) <= tutor.HISTORY_MAX


def test_zeitlimit_liegt_unter_dem_deckel_der_plattform():
    """Vercel bricht nach 60 s ab. Wartet der Client laenger, wird die Funktion
    von aussen abgeschossen, bevor die freundliche Meldung ueberhaupt
    ausgegeben werden kann."""
    assert tutor.CLIENT_TIMEOUT < 60
    assert tutor.AUSWEICH_DEADLINE + tutor.CLIENT_TIMEOUT < 60


def test_hilfe_stufe_klettert_nicht_ohne_gelieferten_hinweis(client, monkeypatch):
    """Fall 17: die Stufe wurde VOR dem KI-Aufruf festgeschrieben. Vier
    misslungene Nachrichten schoben ein Kind so von Stufe 1 auf 4, ohne dass je
    ein Hinweis kam – und verfaelschten die Selbstaendigkeit im Eltern-Board."""
    from app.database import SessionLocal
    from app.models import Attempt, Message, MessageRole
    from app.services import alert as alert_service
    from .test_library import register_pw

    alert_service._last_sent.clear()
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    monkeypatch.setattr(tutor, "anthropic", _fake_anthropic(lambda _m: _FailingCtx()))

    headers = register_pw(client, "ausfall@test.ch")
    ex = client.post("/api/exercises", headers=headers, json={"text": "3x = 15"}).json()
    aid = client.post(f"/api/exercises/{ex['id']}/attempts", headers=headers).json()["attempt"]["id"]

    with SessionLocal() as db:
        vorher = db.get(Attempt, aid).hint_level

    for _ in range(4):
        with client.stream("POST", f"/api/attempts/{aid}/chat", headers=headers,
                           json={"text": "ich brauche einen tipp"}) as r:
            antwort = "".join(r.iter_text())
        assert "technische Probleme" in antwort

    with SessionLocal() as db:
        a = db.get(Attempt, aid)
        assert a.hint_level == vorher, "Stufe darf ohne gelieferten Hinweis nicht steigen"
        # Die Fehlermeldung darf kein Stufen-Etikett tragen
        tutor_msgs = db.query(Message).filter(
            Message.attempt_id == aid, Message.role == MessageRole.tutor).all()
        assert tutor_msgs, "die Meldung wird trotzdem im Verlauf gespeichert"
        assert all(m.hint_level is None for m in tutor_msgs)


def test_stufe_steigt_bei_echter_antwort_weiterhin(client, monkeypatch):
    """Gegenprobe zum Test davor – die Leiter muss normal funktionieren."""
    from app.database import SessionLocal
    from app.models import Attempt
    from .test_library import register_pw

    def fake_stream(*args, **kwargs):
        yield "Was passiert, wenn du beide Seiten durch 3 teilst?"

    monkeypatch.setattr(tutor, "stream_reply", fake_stream)
    headers = register_pw(client, "normal@test.ch")
    ex = client.post("/api/exercises", headers=headers, json={"text": "3x = 15"}).json()
    aid = client.post(f"/api/exercises/{ex['id']}/attempts", headers=headers).json()["attempt"]["id"]

    with client.stream("POST", f"/api/attempts/{aid}/chat", headers=headers,
                       json={"text": "ich brauche einen tipp"}) as r:
        "".join(r.iter_text())

    with SessionLocal() as db:
        assert db.get(Attempt, aid).hint_level >= 1


def _chat_mit_antwort(client, monkeypatch, email, aufgabe, kind, antwort):
    from app.services import tutor
    from .test_library import register_pw

    monkeypatch.setattr(tutor, "stream_reply", lambda *a, **k: iter([antwort]))
    headers = register_pw(client, email)
    ex = client.post("/api/exercises", headers=headers, json={"text": aufgabe}).json()
    aid = client.post(f"/api/exercises/{ex['id']}/attempts", headers=headers).json()["attempt"]["id"]
    with client.stream("POST", f"/api/attempts/{aid}/chat", headers=headers, json={"text": kind}) as r:
        return "".join(r.iter_text())


def test_zitierte_kinderrechnung_wird_nicht_korrigiert(client, monkeypatch):
    """Produktion, Versuch 55: der Tutor zitierte die falsche Rechnung des
    Kindes, und die App haengte «⚠️ Korrektur … → 615» an – die Loesung."""
    from app.database import SessionLocal
    from app.models import Alert
    from app.services import alert as alert_service

    alert_service._last_sent.clear()
    reply = _chat_mit_antwort(client, monkeypatch, "zitat@test.ch", "Berechne 348 + 267",
                              "348 + 267 = 605",
                              "Du hast $348 + 267 = 605$ geschrieben. Schau dir die Einer nochmal an.")
    assert "Korrektur" not in reply and "615" not in reply
    with SessionLocal() as db:
        assert not any(a.kind == "ki-qualitaet" for a in db.query(Alert).all())


def test_korrektur_verraet_die_gesperrte_loesung_nicht(client, monkeypatch):
    """Ein echter Rechenfehler des Tutors, dessen Korrektur die noch gesperrte
    Loesung zeigen wuerde: nur Alarm an den Betreiber, nichts im Chat."""
    from app.database import SessionLocal
    from app.models import Alert
    from app.services import alert as alert_service

    alert_service._last_sent.clear()
    reply = _chat_mit_antwort(client, monkeypatch, "verrat@test.ch", "Berechne 348 + 267",
                              "hilfe", "Schau: $348 + 267 = 605$ – stimmt das?")
    assert "Korrektur" not in reply and "615" not in reply
    with SessionLocal() as db:
        alarme = [a for a in db.query(Alert).all() if a.kind == "ki-qualitaet"]
        assert alarme and "NICHT gezeigt" in alarme[0].detail


def test_leere_antwort_wird_ehrlich_gemeldet(client, monkeypatch):
    """Produktion 19.–26.7.: viermal kam vom Modell kein Text (Denken frass das
    Budget). Gespeichert wurde still der Ersatzsatz «Erzähl mir, wie du an die
    Aufgabe rangehst.» – als echte Antwort mit Hilfe-Stufe, abgebucht, ohne
    Alarm. Jetzt: ehrliche Meldung, Stufe bleibt, nichts abgebucht, Alarm."""
    from app.database import SessionLocal
    from app.models import Alert, Attempt
    from app.services import alert as alert_service, tutor
    from .test_library import register_pw

    alert_service._last_sent.clear()

    def leer(history, step, verification, ex_text, ex_expr, grade, image, usage_out, **kw):
        usage_out["model"] = "claude-haiku-4-5"
        usage_out["usage"] = {"input_tokens": 9000, "output_tokens": 700}
        return iter([""])

    monkeypatch.setattr(tutor, "stream_reply", leer)
    headers = register_pw(client, "leer@test.ch")
    ex = client.post("/api/exercises", headers=headers, json={"text": "Löse 3x + 5 = 20"}).json()
    aid = client.post(f"/api/exercises/{ex['id']}/attempts", headers=headers).json()["attempt"]["id"]
    vorher = client.get("/api/quota", headers=headers).json()
    with client.stream("POST", f"/api/attempts/{aid}/chat", headers=headers, json={"text": "tipp"}) as r:
        reply = "".join(r.iter_text())
    assert "technische Probleme" in reply
    assert client.get("/api/quota", headers=headers).json() == vorher   # nichts abgebucht
    with SessionLocal() as db:
        assert db.get(Attempt, aid).hint_level == 0                      # Stufe nicht geklettert
        assert any(a.kind == "ki" and "Leere" in a.detail for a in db.query(Alert).all())
    texte = [m["text"] for m in client.get(f"/api/attempts/{aid}", headers=headers).json()["messages"]]
    assert not any("Erzähl mir, wie du an die Aufgabe rangehst" in t for t in texte)
