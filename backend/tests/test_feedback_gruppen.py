"""Aehnliche Rueckmeldungen buendeln (services/feedback_gruppen.py) – ohne Datenbank."""
from types import SimpleNamespace

from app.services.feedback_gruppen import Gruppe, aehnlich, gruppiere, normalisiere

_id = [0]


def zeile(text: str, kind: str = "feedback", category: str | None = None):
    _id[0] += 1
    return SimpleNamespace(id=_id[0], text=text, kind=kind, category=category)


def test_normalisiere_faltet_umlaute_und_wirft_fuellwoerter_weg():
    assert normalisiere("Lösung") == normalisiere("Loesung") == frozenset({"loesung"})
    assert normalisiere("Die Aufgabe 12 ist nicht so gut!") == frozenset({"aufgabe", "gut"})
    assert normalisiere("") == frozenset()
    assert normalisiere(None) == frozenset()


def test_aehnlich_braucht_die_haelfte_der_woerter():
    assert aehnlich(frozenset({"a", "b", "c"}), frozenset({"a", "b", "d"}))     # 2/4 = 0.5
    assert not aehnlich(frozenset({"a", "b", "c"}), frozenset({"a", "d", "e"}))  # 1/5
    assert aehnlich(frozenset(), frozenset())          # beide ohne Text: gleich
    assert not aehnlich(frozenset(), frozenset({"a"}))  # einer leer, einer nicht


def test_umformulierung_landet_in_einer_gruppe():
    g = gruppiere([zeile("Bitte mehr Geometrie-Aufgaben."),
                   zeile("Mehr Geometrie Aufgaben bitte!")])
    assert len(g) == 1 and g[0].anzahl == 2


def test_unverwandte_texte_bleiben_getrennt():
    g = gruppiere([zeile("Der Stift funktioniert super."),
                   zeile("Bitte mehr Geometrie-Aufgaben.")])
    assert len(g) == 2


def test_leere_problem_meldungen_gleicher_kategorie_sind_eine_gruppe():
    g = gruppiere([zeile("", "problem", "erkennung"),
                   zeile("", "problem", "erkennung"),
                   zeile("", "problem", "technik")])
    assert [(x.schluessel, x.anzahl) for x in g] == [("problem|erkennung", 2), ("problem|technik", 1)]


def test_zahlen_und_fuellwoerter_zaehlen_nicht():
    g = gruppiere([zeile("Aufgabe 12 ist falsch"),
                   zeile("die Aufgabe 13 war falsch")])
    assert len(g) == 1


def test_art_und_kategorie_werden_nie_vermischt():
    g = gruppiere([zeile("Die Erkennung ist toll"),
                   zeile("Die Erkennung ist toll", "problem", "antwort")])
    assert len(g) == 2


def test_groesste_gruppe_zuerst_und_neuester_text_als_repraesentant():
    rows = [zeile("Stift super"), zeile("Mehr Geometrie"), zeile("Mehr Geometrie bitte"),
            zeile("Geometrie mehr")]
    g = gruppiere(rows)
    assert [x.anzahl for x in g] == [3, 1]
    assert g[0].eintraege[0].text == "Geometrie mehr"       # neuester zuerst
    assert isinstance(g[0], Gruppe)
