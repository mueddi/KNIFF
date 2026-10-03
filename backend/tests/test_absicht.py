"""Was meint das Kind? Antwort-Saetze, Zahlwoerter, Rechenvorhaben, Bitten.

Alle Faelle hier liefen bis 3.10. falsch: entweder wurde eine richtige
Antwort nicht erkannt (nichts abgehakt), ein Vorhaben als falsche Antwort
gezaehlt (Hilfe-Stufe hoch, Fehlversuch), oder ein Hilferuf bekam die
Regie «Kein Hilferuf … keine ungefragte Hilfe».
"""
import pytest

from app.services import tutor
from app.services.sympy_verifier import Verification, verify

AUFGABE = "3x+5=20"


@pytest.mark.parametrize(
    "antwort,erwartet",
    [
        ("die Lösung ist 5", "correct"),
        ("das Ergebnis ist 5.", "correct"),
        ("die Lösung ist 4", "incorrect"),
        ("ich habe 5 rausbekommen", "correct"),
        ("i han 5 usegfunde", "correct"),
        ("ich komme auf 5", "correct"),
        ("the answer is 5", "correct"),
        ("ich habe 15 durch 3 gerechnet und komme auf 5", "correct"),
        # Zahlwoerter als Antwort
        ("fünf", "correct"),
        ("x ist fünf", "correct"),
        ("x = fünf", "correct"),
        # ... aber nicht in anderen Saetzen
        ("noch eins", "unknown"),
        ("zwei tipps bitte", "unknown"),
        ("die Lösung ist nicht 5", "unknown"),
        ("ich habe 3 tipps bekommen", "unknown"),
        # «minus 5» zu «3x + 5 = 20» ist ein Vorhaben, keine falsche Antwort −5
        ("minus 5", "unknown"),
        ("minus 5?", "unknown"),
        ("x = minus 5", "incorrect"),
    ],
)
def test_antwort_saetze(antwort, erwartet):
    assert verify(AUFGABE, antwort).status == erwartet


def test_minus_ist_antwort_wenn_die_zahl_nicht_in_der_aufgabe_steht():
    assert verify("3x = 15", "minus 5").status == "incorrect"
    assert verify("x + 5 = 0", "minus 5").status == "correct"


@pytest.mark.parametrize(
    "nachricht,absicht",
    [
        # Bitten um die Loesung
        ("kannst du es für mich lösen", "plea"),
        ("mach du es", "plea"),
        ("rechne du es vor", "plea"),
        ("sag mir einfach was x ist", "plea"),
        ("just tell me the answer", "plea"),
        ("what is the answer", "plea"),
        # ... aber den WEG lernen wollen ist Hilfe, kein Betteln
        ("kannst du mir zeigen wie ich das lösen kann", "stuck"),
        ("zeig mir wie man es löst", "stuck"),
        ("machst du mir ein beispiel?", "talk"),
        # Hilferufe
        ("zeig mir wie es geht", "stuck"),
        ("was muss ich machen", "stuck"),
        ("help", "stuck"),
        ("I dont know", "stuck"),
        ("idk", "stuck"),
        # Nicht verstanden
        ("ich check gar nix", "simpler"),
        ("hä?", "simpler"),
        ("???", "simpler"),
        ("i dont understand", "simpler"),
        # Rechenvorhaben ist ein eigener Schritt
        ("minus 5", "step"),
        # «fertig» mit nachweislich falscher Antwort ist ein Versuch
        ("x = 4, fertig", "attempt"),
        ("ich bin fertig", "fertig"),
        # unveraendert
        ("ok", "talk"),
        ("sag mir die lösung", "plea"),
        ("die Lösung ist 5", "correct"),
    ],
)
def test_absicht(nachricht, absicht):
    assert tutor.detect_intent(nachricht, verify(AUFGABE, nachricht)) == absicht


def test_regie_laedt_bei_falscher_antwort_nicht_zum_abhaken_ein():
    """«Nachrechnung: stimmt nicht» und direkt darunter «hat er das Ergebnis
    hingeschrieben? Dann [[GELOEST]]» – der Server haette es ohnehin
    verworfen, das Modell bekam aber zwei gegensaetzliche Ansagen."""
    falsch = Verification("incorrect", "Endwert stimmt nicht", "x = 5", "x = 4")
    regie = tutor._regie(tutor.LadderStep("attempt", 2, 1, False, False), falsch, AUFGABE, AUFGABE)
    assert "[[GELOEST]]" not in regie
    unklar = Verification("unknown", "", None, None)
    regie = tutor._regie(tutor.LadderStep("talk", 1, 0, False, False), unklar, AUFGABE, None)
    assert "[[GELOEST]]" in regie  # ohne Pruefung entscheidet weiterhin der Tutor
