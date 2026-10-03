"""SymPy-Verifier: Endwerte, Umformungsschritte, Prosa-Robustheit."""
import pytest

from app.services.sympy_verifier import check_reply_math, extract_expression, verify


@pytest.mark.parametrize(
    "expr,answer,expected",
    [
        ("3*x + 5 = 20", "ich glaube x = 5", "correct"),
        ("3x+5=20", "x=5", "correct"),
        ("3x+5=20", "3x = 15", "partial"),          # gueltiger Umformungsschritt
        ("3x+5=20", "ich denke 3x = 15", "partial"),  # Gleichung in Prosa (Fix 6)
        ("3x+5=20", "x = 10", "incorrect"),
        ("3x+5=20", "ich weiss nicht", "unknown"),
        ("3x+5=20", "muss ich minus 5 rechnen?", "unknown"),  # Zahl in Prosa-Frage
        ("2x = 8", "4", "correct"),
        ("x^2 = 9", "x = 3", "correct"),
        ("3x+5=20", "gib mir die lösung 🙏", "unknown"),
        # gespiegelte Endantwort «wert = variable» zaehlt genauso
        ("2 + 3 = 2*y", "5/2 = y", "correct"),
        ("2 + 3 = 2*y", "5/2=y", "correct"),
        ("2 + 3 = 2*y", "3 = y", "incorrect"),
    ],
)
def test_verify(expr, answer, expected):
    assert verify(expr, answer).status == expected


# Bis 3.10. hiess es bei jeder dieser Antworten «falsch» (oder bei Fragen
# «richtig») – und der Tutor bekam das als Pruefergebnis mit.
@pytest.mark.parametrize(
    "expr,answer,expected",
    [
        # Rechnung in mehreren Zeilen oder auf einer Zeile hintereinander
        ("3x+5=20", "3x = 15\nx = 5", "correct"),
        ("3x+5=20", "3x = 15 x = 5", "correct"),
        ("3x+5=20", "3x = 15; x = 5", "correct"),
        ("3x+5=20", "3x = 15\nx = 4", "incorrect"),
        # Grossbuchstabe, Bruch, Ausrufezeichen, Komma
        ("3x+5=20", "X = 5", "correct"),
        ("2*x = 3", "x = 3/2", "correct"),
        ("6*x = 5", "= 5/6", "correct"),
        ("3x+5=20", "x = 5!", "correct"),
        ("2*x = 3", "x = 1,5", "correct"),
        # gerundete Antworten
        ("3*x = 10", "x = 3.33", "correct"),
        ("3*x = 10", "x = 3,3", "correct"),
        ("3*x = 10", "x = 3.4", "incorrect"),
        # symbolische Antwort: nicht mehr als «x = 5» gelesen
        ("(5*y)/3 = x", "x = 5y/3", "correct"),
        # Probe: 3*5+5 = 20 ist kein Wert fuer x
        ("3x+5=20", "3*5+5 = 20", "unknown"),
        # Fragen und Rechenwege sind keine Antworten
        ("3x+5=20", "warum ist x = 5?", "unknown"),
        ("3x+5=20", "x = 5 oder x = 4?", "unknown"),
        ("3x+5=20", "durch 3 teilen?", "unknown"),
        ("3x+5=20", "ich muss durch 3 teilen", "unknown"),
        # unveraendert
        ("3x+5=20", "x = 4", "incorrect"),
        ("3x+5=20", "3x = 15", "partial"),
    ],
)
def test_verify_schreibweisen_der_kinder(expr, answer, expected):
    assert verify(expr, answer).status == expected


def test_extract_expression_multiline():
    """Stift-/Foto-Eingaben sind oft mehrzeilig – die Gleichung muss trotzdem
    gefunden werden, sonst ist die Aufgabe nie als geloest erkennbar."""
    assert extract_expression("2 + 3\n= 2 * y") is not None
    assert verify(extract_expression("2 + 3\n= 2 * y"), "y = 5/2").status == "correct"
    # mehrere Zeilen mit eigener Gleichung: die erste loesbare gewinnt
    assert extract_expression("Löse nach x auf:\n3x + 5 = 20") == "3x + 5 = 20"


def test_solution_never_in_context():
    v = verify("3*x+5=20", "keine ahnung")
    assert v.solution == "x = 5"          # intern bekannt
    assert "solution" not in v.to_context()  # geht nie ungefiltert raus


def test_reine_rechenaufgabe_wird_erkannt_und_geprueft():
    """«2 + 4» ist auch ohne Gleichheitszeichen pruefbar."""
    from app.services.sympy_verifier import extract_expression, verify

    assert extract_expression("2 + 4") == "2 + 4"
    assert extract_expression("Berechne: 348 + 267") is not None
    assert extract_expression("Erkläre mir Brüche") is None
    assert extract_expression("42") is None  # einzelne Zahl ist keine Aufgabe

    assert verify("2 + 4", "= 6").status == "correct"
    assert verify("2 + 4", "6").status == "correct"
    assert verify("2 + 4", "2 + 4 = 6").status == "correct"
    v = verify("2 + 4", "7")
    assert v.status == "incorrect"
    assert v.solution == "= 6"
    assert verify("2 + 4", "keine ahnung").status == "unknown"


def test_sympy_wird_erst_beim_rechnen_geladen():
    """Kaltstart der Vercel-Funktion: der SymPy-Import kostet 1.56 s und lief
    bei JEDER Anfrage mit, auch beim Anmelden. Jetzt erst beim ersten Rechnen.
    Frischer Interpreter, damit kein anderer Test das Modul schon geladen hat."""
    import subprocess
    import sys
    from pathlib import Path

    # Eigener Arbeitsordner (backend/), unabhaengig davon, von wo aus pytest
    # gestartet wurde – der Deploy-Workflow ruft "pytest backend/tests/" vom
    # Hauptverzeichnis aus auf, ohne cwd wuerde "import app" dort scheitern.
    backend_dir = Path(__file__).resolve().parent.parent
    code = ("import sys; import app.services.sympy_verifier as v; "
            "assert 'sympy' not in sys.modules, 'SymPy schon beim Import geladen'; "
            "assert v.verify('3x + 5 = 20', 'x = 5').status == 'correct'; "
            "assert 'sympy' in sys.modules; print('ok')")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       timeout=120, cwd=backend_dir)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "ok"


def test_wurzel_und_kreiszahl_bleiben_im_pruefausdruck():
    """Beim Fuellen der Bibliothek entdeckt: aus «sqrt(6^2 + 8^2)» wurde
    «(6^2 + 8^2)» = 100 statt 10, aus «pi * 5^2» wurde «5^2». Die Nachrechnung
    haette die RICHTIGE Antwort des Kindes als falsch gestempelt."""
    from app.services.sympy_verifier import extract_expression, verify

    assert extract_expression("sqrt(6^2 + 8^2)") == "sqrt(6^2 + 8^2)"
    assert verify("sqrt(6^2 + 8^2)", "10").status == "correct"
    assert verify("sqrt(6^2 + 8^2)", "100").status == "incorrect"
    assert extract_expression("Berechne den Umfang: 2*pi*5") == "2*pi*5"
    assert extract_expression("pi * 5^2") == "pi * 5^2"
    assert extract_expression("sqrt(16)") == "sqrt(16)"
    # Prosa bleibt draussen, eine nackte Zahl ist keine Aufgabe
    assert extract_expression("Wie viel ist 3 + 4?") == "3 + 4"
    assert extract_expression("Ein Velo kostet 240 Franken") is None


def test_lineare_schreibweise_von_links_nach_rechts():
    """Schul-Lesart: «3/2y» = (3/2)·y, nicht 3/(2y); Klassiker bleibt korrekt."""
    from app.services.sympy_verifier import verify

    # (3/2)·y = 6  ->  y = 4
    assert verify("3/2y = 6", "y = 4").status == "correct"
    assert verify("3/2y = 6", "y = 9").status == "incorrect"
    # explizite Klammern unveraendert korrekt
    assert verify("(3/2)*x = 6", "x = 4").status == "correct"
    # Regression: impliziertes Mal in Koeffizienten bleibt richtig
    assert verify("3x + 5 = 20", "x = 5").status == "correct"
    assert verify("2(x + 1) = 8", "x = 3").status == "correct"


def test_check_reply_math_findet_nur_echte_zahlenfehler():
    from app.services.sympy_verifier import check_reply_math

    assert check_reply_math("Gut! $2 + 2 = 4$ stimmt.") == []
    assert check_reply_math("Nur Prosa ohne Formeln.") == []
    assert check_reply_math("$x = 5$ und $3x + 5 = 20$") == []  # Variablen -> skip
    assert check_reply_math(r"$\frac{1}{2} = 0.5$") == []

    fehler = check_reply_math(r"Genau richtig! $2 \cdot 3 = 5$")
    assert len(fehler) == 1
    raw, richtig = fehler[0]
    assert "2" in raw and richtig == "6"

    assert check_reply_math(r"$$10 - 4 = 7$$")[0][1] == "6"


def test_gleichung_mit_zwei_unbekannten_nur_wenn_sie_zu_einer_zahl_aufloest():
    """Regression: «(2*x*5*y*8)/3 = y» fiel durch, weil genau EINE Unbekannte
    verlangt wurde – obwohl verify() die Aufgabe nach x aufloest. Folge: kein
    Pruefausdruck, der Tutor ohne jede Bodenhaftung (real beobachtet).

    Die Lockerung darf aber nicht ins Gegenteil kippen: eine Gleichung, die
    nur SYMBOLISCH aufloest, hat keine eindeutige Antwort. Wird sie trotzdem
    als Aufgabe hinterlegt, misst verify() jede Schuelerantwort an einem
    Term wie «(2y-5)/3» und erklaert sie fuer falsch. Lieber keine Pruefung.
    """
    assert extract_expression("(2*x*5*y*8)/3 = y") == "(2*x*5*y*8)/3 = y"
    assert extract_expression("3x + 5 = 2y") is None  # loest nur symbolisch auf
    # Prosa wird weiterhin sauber abgetrennt und NICHT mitgespeichert
    assert extract_expression("Berechne x wenn 2x+4 = 10") == "2x+4 = 10"
    assert extract_expression("Loese die Gleichung: 5x - 3 = 12") == "5x - 3 = 12"


def test_aufgabentext_mit_mehreren_gleichungen_wird_verworfen():
    """«a = 5, b = 3. Berechne a + b» speicherte «a = 5» als DIE Aufgabe –
    die richtige Antwort 8 galt danach als falsch. Mehrere Gleichungen in
    einer Zeile heisst: die erste ist eine Angabe, nicht die Frage."""
    assert extract_expression("a = 5, b = 3. Berechne a + b") is None
    assert extract_expression("Loese das Gleichungssystem: x + y = 10 und x - y = 2") is None
    assert extract_expression("Gegeben ist y = 2x + 1. Wo schneidet sie die x-Achse?") is None
    # Eine einzelne Gleichung bleibt unberuehrt
    assert extract_expression("Loese 3x = 15") == "3x = 15"


def test_aufgabe_abschreiben_macht_falsches_ergebnis_nicht_richtig():
    """«2+4 = 7» galt als richtig, weil die LINKE Seite (die abgeschriebene
    Aufgabe) verglichen wurde. Genau so schreiben Primarschueler ihre Antwort."""
    assert verify("2 + 4", "2+4 = 7").status == "incorrect"
    assert verify("348 + 267", "348+267=515").status == "incorrect"
    # richtig hingeschrieben bleibt richtig
    assert verify("2 + 4", "2+4 = 6").status == "correct"
    assert verify("2 + 4", "6").status == "correct"
    assert verify("2 + 4", "x = 6").status == "correct"


def test_zahl_in_einer_ablehnung_ist_keine_antwort():
    """«5 stimmt nicht» setzte die Aufgabe auf GELOEST, weil nur die Zahl
    gesehen wurde und kein Wort drumherum."""
    for msg in ["5 stimmt nicht", "nicht 5", "ist 5 falsch?", "nöd 5", "nei 5"]:
        assert verify("3x = 15", msg).status == "unknown", msg
    # die blosse Zahl bleibt eine Antwort
    assert verify("3x = 15", "5").status == "correct"


def test_vorzeichen_als_wort():
    """«minus 5» wurde als +5 gewertet – das Wort stand da, das Zeichen nicht."""
    assert verify("3x = 15", "minus 5").status == "incorrect"
    assert verify("x + 5 = 3", "minus 2").status == "correct"


def test_rechenkette_wird_am_ende_bewertet():
    """«x = 30/2 = 14» galt als richtig, weil der Zwischenwert 30/2 stimmt.
    Bewertet werden muss die letzte Zahl – die Antwort des Kindes."""
    assert verify("2x = 30", "x = 30/2 = 14").status == "incorrect"
    assert verify("2x = 30", "x = 30/2 = 15").status == "correct"


def test_antwort_hinter_der_aufgabe_geht_nicht_verloren():
    """«3x=15 also x=5» und die Schweizer Schreibweise «3x = 15 | :3  x = 5»
    endeten in «nur die Aufgabe wiederholt» – die Antwort dahinter fiel weg.
    Ebenso das Komma davor: «3x=15, x=5»."""
    assert verify("3x = 15", "3x=15 also x=5").status == "correct"
    assert verify("3x = 15", "3x = 15 | :3  x = 5").status == "correct"
    assert verify("3x = 15", "3x=15, x=5").status == "correct"
    assert verify("3x = 15", "ich teile beide seiten durch 3, x = 5").status == "correct"
    # reines Abschreiben zaehlt weiterhin NICHT als eigener Schritt
    assert verify("3x = 15", "3x = 15").status == "unknown"


def test_keine_korrektur_bei_gerundeten_zahlen():
    """Unter einer voellig richtigen Tutor-Antwort stand «⚠️ Korrektur»:
    gerundete Dezimalzahlen sind im Unterricht Absicht, kein Rechenfehler."""
    assert check_reply_math(r"Ein Drittel ist $\frac{1}{3} = 0.33$") == []
    assert check_reply_math(r"Also $0.1 + 0.2 = 0.3$") == []
    assert check_reply_math(r"Das sind $1.000 + 500 = 1.500$ Franken") == []
    assert check_reply_math(r"Zeit $1:30 = 1.5$ Stunden") == []
    assert check_reply_math(r"$1/0 = 5$") == []  # sonst stuende «zoo» im Chat
    # echte Fehler in ganzen Zahlen werden weiterhin gefunden
    assert check_reply_math(r"Damit $2 + 2 = 5$") == [("2 + 2 = 5", "4")]


def test_rechenbombe_haengt_die_anfrage_nicht_auf():
    """«x = 9^9^9^9» beschaeftigte SymPy praktisch endlos und blockierte damit
    eine Anfrage (nachgestellt: nach 8 s noch nicht zurueck). Normale Potenzen
    muessen weiter geprueft werden."""
    # Nicht haengen, nicht «richtig». (Bis 3.10. hiess es «incorrect» nur, weil
    # die Suche faelschlich «x = 9» aus «x = 9^9^9^9» las – genau dieser
    # Praefix-Fehler machte auch «x = 5y/3» zu «x = 5». Jetzt: nicht pruefbar.)
    assert verify("3x = 15", "x = 9^9^9^9").status == "unknown"
    assert extract_expression("Berechne 9^9^9^9") is None
    assert verify("3x = 15", "x = 2^1000000").status == "unknown"
    # normale Potenzen bleiben pruefbar
    assert verify("x^2 = 4", "2").status == "correct"
    assert verify("2^10", "1024").status == "correct"
    assert extract_expression("Berechne 2^3 + 3^2") == "2^3 + 3^2"


# Bis 3.10. rechnete die Nummerierung mit: «Aufgabe 3: 2x+4=10» wurde als
# «3/ 2x+4 = 10» gespeichert, und die richtige Antwort x = 3 galt als falsch.
@pytest.mark.parametrize(
    "text,erwartet",
    [
        ("Aufgabe 3: 2x+4=10", "2x+4 = 10"),
        ("3. 2x + 4 = 10", "2x + 4 = 10"),
        ("3) 2x+4=10", "2x+4 = 10"),
        ("b) 2x+4=10", "2x+4 = 10"),
        ("Nr. 5: 3x+5=20", "3x+5 = 20"),
        ("2) a) 3x = 9", "3x = 9"),
        ("Aufgabe 12: Berechne 34 + 18", "34 + 18"),
        ("1) 5 + 7", "5 + 7"),
        # Dezimalzahlen vorne sind keine Nummer
        ("3.5x = 7", "3.5x = 7"),
        ("3.5 + 2", "3.5 + 2"),
        # eine blosse Angabe ist keine Aufgabe
        ("x = 3", None),
        ("x = 3\nBerechne 2x + 1", None),
        ("5 = x + 2", "5 = x + 2"),
    ],
)
def test_extract_expression_nummerierung_und_angaben(text, erwartet):
    assert extract_expression(text) == erwartet


def test_aufgabe_mit_nummer_richtige_antwort_gilt(client):
    from .conftest import register

    h = register(client, "nummer@test.ch")
    ex = client.post("/api/exercises", json={"text": "Aufgabe 3: Löse 2x + 4 = 10"}, headers=h).json()
    assert verify(ex["math_expression"], "x = 3").status == "correct"


def test_mitgeschickter_ausdruck_wird_nicht_ungeprueft_gespeichert(client):
    """Vom Foto kam ein grob geratener Ausdruck mit («se2x+4=10»), der Server
    speicherte ihn ungeprueft. Jetzt zaehlt der bestaetigte Text."""
    from .conftest import register

    h = register(client, "ausdruck@test.ch")
    ex = client.post("/api/exercises", headers=h,
                     json={"text": "Löse 2x+4=10", "math_expression": "se2x+4=10"}).json()
    assert verify(ex["math_expression"], "x = 3").status == "correct"
    # gibt der Text nichts her, gilt der Ausdruck nur, wenn er nachrechenbar ist
    ex = client.post("/api/exercises", headers=h,
                     json={"text": "(Aufgabe auf dem Foto)", "math_expression": "Dreiecka=6cm"}).json()
    assert ex["math_expression"] is None
    ex = client.post("/api/exercises", headers=h,
                     json={"text": "(Aufgabe auf dem Foto)", "math_expression": "3*x+5=20"}).json()
    assert verify(ex["math_expression"], "x = 5").status == "correct"


def test_foto_erkennung_raet_keinen_unsinn():
    from app.services.ocr import _guess_math_expression as g

    assert g("Aufgabe 3: Löse 2x+4=10") == "2x+4 = 10"
    assert g("3x + 5 = 20\n3x = 15") == "3x + 5 = 20"
    assert g("[Figur: Dreieck a = 6 cm]") is None
    assert g("a = 5, b = 3. Berechne a+b") is None
