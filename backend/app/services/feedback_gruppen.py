"""Aehnliche Rueckmeldungen buendeln – die Antwort auf «kamen gleiche Feedbacks?».

Ohne Bibliothek, ohne Modell: zwei Texte gelten als gleich, wenn mindestens
die Haelfte ihrer bedeutungstragenden Woerter uebereinstimmt (Jaccard auf
Wortmengen). Vorher wird normalisiert – Kleinschreibung, Umlaute gefaltet
(«Lösung» = «Loesung»), Zahlen weg («Aufgabe 12» = «Aufgabe 13»), Fuellwoerter
weg. Das ist dem Betreiber erklaerbar und fuer ein paar tausend Zeilen schnell.

Art (feedback/problem) und Kategorie werden nie vermischt: eine Problem-
Meldung «Erkennung» und ein freies Feedback «die Erkennung ist toll» sind
zwei verschiedene Dinge, auch wenn die Woerter aehnlich sind. Problem-
Meldungen ohne Text fallen je Kategorie in EINE Gruppe – genau das will man
sehen («7× Foto falsch erkannt, ohne Kommentar»).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Deckel fuer den Endpunkt: der Vergleich ist quadratisch in der Zahl der
# Gruppen; 2000 Zeilen bleiben deutlich unter einer Sekunde.
MAX_ZEILEN = 2000
# Anteil gemeinsamer Woerter, ab dem zwei Texte als gleich gelten.
SCHWELLE = 0.5
MIN_TOKEN_LAENGE = 3

STOPWOERTER = frozenset("""
aber alle als also auch auf aus bei bin bis bitte bzw dann das dass dem den der des
die dies diese dieser dieses doch dort durch ein eine einem einen einer eines er
es etwas fuer gar gibt habe haben hat hatte hier ich ihr ihre ihren ihrer ihn ihm
immer ist ja jetzt kann kein keine koennen mal man mehr mein meine mich mir mit
nach nicht noch nur oder schon sehr sein seine sich sie sind soll sollte und uns
unser vom von vor war wenn werden wieder wird wir wo wurde zum zur
the and are but for from had has have her here his how its just not our she that
the their them then there these they this those very was were what when where
which who why will with would you your
""".split())

_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def normalisiere(text: str | None) -> frozenset[str]:
    """Bedeutungstragende Woerter eines Textes als Menge."""
    low = (text or "").lower().translate(_UMLAUTE)
    low = re.sub(r"[^a-z0-9]+", " ", low)
    return frozenset(
        w for w in low.split()
        if len(w) >= MIN_TOKEN_LAENGE and not w.isdigit() and w not in STOPWOERTER
    )


def aehnlich(a: frozenset[str], b: frozenset[str]) -> bool:
    """Gleiche Wortmenge (auch beide leer) oder Jaccard-Anteil >= SCHWELLE."""
    if a == b:
        return True
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= SCHWELLE


@dataclass
class Gruppe:
    schluessel: str                 # "{kind}|{category}" – nie ueber Art/Kategorie hinweg
    tokens: frozenset[str]          # Wortmenge des Repraesentanten (neuester Eintrag)
    eintraege: list = field(default_factory=list)   # neueste zuerst

    @property
    def anzahl(self) -> int:
        return len(self.eintraege)


def _schluessel(row) -> str:
    return f"{row.kind}|{row.category or ''}"


def gruppiere(rows: list) -> list[Gruppe]:
    """Greedy, neueste zuerst: jeder Eintrag geht in die erste Gruppe gleicher
    Art/Kategorie mit aehnlichem Text, sonst in eine neue. Verglichen wird nur
    mit dem Repraesentanten (dem neuesten Text der Gruppe) – kein Abdriften
    ueber Zwischenglieder. Rueckgabe: groesste Gruppe zuerst, bei Gleichstand
    die mit dem juengsten Eintrag."""
    sortiert = sorted(rows, key=lambda r: r.id, reverse=True)
    gruppen: list[Gruppe] = []
    for row in sortiert:
        key = _schluessel(row)
        tokens = normalisiere(row.text)
        for g in gruppen:
            if g.schluessel == key and aehnlich(g.tokens, tokens):
                g.eintraege.append(row)
                break
        else:
            gruppen.append(Gruppe(schluessel=key, tokens=tokens, eintraege=[row]))
    gruppen.sort(key=lambda g: (-g.anzahl, -g.eintraege[0].id))
    return gruppen
