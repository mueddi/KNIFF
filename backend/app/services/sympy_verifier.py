"""Deterministische Mathe-Verifikation mit SymPy.

Die Pädagogik macht das LLM. Diese Funktion sagt nur: ist die Schülerantwort
korrekt / teilweise (gültiger Umformungsschritt) / falsch / nicht prüfbar –
und liefert (intern!) die Lösung, die erst auf Stufe 4 verraten werden darf.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache


class _SympyLazy:
    """SymPy erst beim ERSTEN Rechnen laden, nicht beim Start der App.

    Gemessen: der Import kostet 1.56 s – bei jedem Kaltstart der Vercel-
    Funktion, also auch fuer Anfragen, die gar nicht rechnen (Anmelden,
    Kontingent, Themenliste, Gesundheitsauskunft). Nach dem ersten Zugriff
    ersetzt sich dieser Platzhalter selbst durch das echte Modul.
    """

    def __getattr__(self, name):
        import sympy

        globals()["sp"] = sympy
        return getattr(sympy, name)


sp = _SympyLazy()


@lru_cache(maxsize=1)
def _parser():
    """parse_expr samt Transformationen – ebenfalls erst bei Bedarf."""
    from sympy.parsing.sympy_parser import (
        convert_xor,
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )

    return parse_expr, standard_transformations + (implicit_multiplication_application, convert_xor)


@dataclass
class Verification:
    status: str  # "correct" | "partial" | "incorrect" | "unknown"
    detail: str  # kurze technische Notiz (nur intern)
    solution: str | None = None  # interne Lösung, NIE ungefiltert an Schüler
    extracted: str | None = None  # was aus der Antwort erkannt wurde

    def to_context(self) -> dict:
        """Kompakter Kontext fürs LLM (ohne die Lösung, ausser Stufe 4 erlaubt)."""
        return {"status": self.status, "detail": self.detail, "extracted": self.extracted}


def _normalize(s: str) -> str:
    s = s.strip()
    s = s.replace("−", "-").replace("·", "*").replace("×", "*").replace(":", "/")
    # NUR das Dezimalkomma zwischen zwei Ziffern wird zum Punkt (Schweiz: «1,5»).
    # Frueher fiel JEDES Komma – damit wurde «3x=15, x=5» zu «3x=15. x=5» und
    # der Unsinns-Kandidat «3. x = 5» gewann vor der richtigen Antwort «x=5».
    # Ein stehen gelassenes Komma beendet die Fragment-Suche unten sauber.
    s = re.sub(r"(?<=\d),(?=\d)", ".", s)
    return s


# Woerter, die eine Zahl in der Nachricht zur NICHT-Antwort machen: «5 stimmt
# nicht» galt sonst als die Antwort «5» – und damit die Aufgabe als geloest.
_ABLEHNUNG = re.compile(r"(?:\bnicht\b|\bnöd\b|\bnoed\b|\bnid\b|\bfalsch\b|\bkein\w*\b|\bnein\b|\bnei\b)",
                        re.IGNORECASE)
# Zahlen in einer HILFE-Bitte sind keine Antwort: «1 tipp bitte» wurde als
# Antwort «1» gewertet, also falsch – Stufe hoch und ein Fake-Versuch gezaehlt.
_HILFE_WORT = re.compile(r"\b(?:tipp\w*|hinweis\w*|stufe|frage\w*|schritt\w*|hilfe|hilf)\b",
                         re.IGNORECASE)
# «minus 5» ist -5: das Vorzeichen steht als WORT da, das Zeichen fehlt.
_MINUS_WORT = re.compile(r"\bminus\s+(?=[0-9])", re.IGNORECASE)
_PLUS_WORT = re.compile(r"\bplus\s+(?=[0-9])", re.IGNORECASE)


def _chain_collapse(msg: str) -> str:
    """«x = 30/2 = 14» -> «x = 14»: bei einer Rechenkette zaehlt das ENDE.

    Kinder schreiben ihren Rechenweg in eine Zeile. Bewertet werden muss die
    LETZTE Zahl (ihre Antwort), nicht der Zwischenwert – sonst gilt
    «x = 30/2 = 14» als richtig, weil «x = 30/2» fuer sich stimmt.

    Nur bei einer ECHTEN Kette: jedes Glied muss ein reines Mathe-Fragment
    sein. Sonst wuerde «3x=15 also x=5» zu «3x = 5» zusammenfallen und eine
    richtige Antwort waere plotzlich falsch.
    """
    parts = [p.strip() for p in msg.split("=")]
    if len(parts) < 3 or any(not p for p in parts):
        return msg
    for p in parts:
        if not re.fullmatch(r"[0-9A-Za-z+\-*/^(). ]+", p):
            return msg  # Prosa/Sonderzeichen dazwischen -> keine Rechenkette
        if re.search(r"[A-Za-zÀ-ÿ]{2,}", p):
            return msg  # ein Wort dazwischen -> keine Rechenkette
    return f"{parts[0]} = {parts[-1]}"


def _insert_explicit_mult(s: str) -> str:
    """Schul-Lesart erzwingen: implizites Mal EXPLIZIT machen, BEVOR SymPy parst.

    SymPy's implicit multiplication bindet staerker als die Division –
    «3/2y» wuerde zu 3/(2·y). Schueler:innen lesen linear von links nach
    rechts: «3/2y» = (3/2)·y. Darum «2y»→«2*y», «)x»→«)*x», «y(»→«y*(»
    (einzelne Variable, Funktionsnamen wie sqrt( bleiben unberuehrt).
    """
    s = re.sub(r"(\d)\s*(?=[A-Za-z(])", r"\1*", s)
    s = re.sub(r"(\))\s*(?=[A-Za-z0-9(])", r"\1*", s)
    s = re.sub(r"(?<![A-Za-z])([A-Za-z])\s*(?=\()", r"\1*", s)
    return s


# Rechen-Bomben: «9^9^9^9» beschaeftigt SymPy praktisch endlos (nachgestellt:
# nach 8 Sekunden noch nicht zurueck, mit wachsendem Speicher) und blockiert
# damit eine Anfrage. Ein Potenzturm oder ein vierstelliger Exponent kommt in
# einer Schuelerantwort nicht vor – abweisen kostet nichts.
_POTENZ_TURM = re.compile(r"(?:\^|\*\*)\s*\(?\s*[0-9A-Za-z.]+\s*(?:\^|\*\*)")
_GROSSER_EXPONENT = re.compile(r"(?:\^|\*\*)\s*\(?\s*-?\d{4,}")


def _parse(expr: str):
    if _POTENZ_TURM.search(expr) or _GROSSER_EXPONENT.search(expr):
        raise ValueError("Ausdruck zu aufwaendig")
    parse_expr, transforms = _parser()
    out = parse_expr(_insert_explicit_mult(_normalize(expr)),
                     transformations=transforms, evaluate=True)
    if not isinstance(out, sp.Basic):
        # «3, x» liefert ein TUPEL statt eines Ausdrucks – das ist kein
        # Rechenausdruck und darf nicht weiterlaufen (sonst knallt es erst
        # spaeter bei .free_symbols).
        raise ValueError("kein einzelner Ausdruck")
    return out


def _split_equation(text: str):
    """'3x+5=20' -> (lhs, rhs) als SymPy-Ausdrücke, sonst None."""
    if "=" not in text:
        return None
    left, _, right = text.partition("=")
    try:
        return _parse(left), _parse(right)
    except Exception:
        return None


def _free_symbol(*exprs):
    syms: set = set()
    for e in exprs:
        syms |= e.free_symbols
    return next(iter(syms)) if len(syms) == 1 else (sorted(syms, key=str)[0] if syms else None)


def _solutions(lhs, rhs, sym):
    try:
        sols = sp.solve(sp.Eq(lhs, rhs), sym, dict=False)
        return [sp.nsimplify(s) if s.is_number else s for s in sols]
    except Exception:
        return []


def _extract_candidates(message: str) -> list[str]:
    """Zieht mögliche Antwort-Fragmente aus dem Schülertext.

    Erkennt 'x = 5', '= 5', ganze Gleichungen, oder eine allein stehende Zahl.
    """
    msg = _normalize(message)
    msg = _MINUS_WORT.sub("-", msg)
    msg = _PLUS_WORT.sub("+", msg)
    msg = _chain_collapse(msg)
    cands: list[str] = []
    # eigenständige Gleichung im Text zuerst (damit '3x = 15' als Umformung zaehlt)
    if "=" in msg:
        cands.append(msg)
        # Mathe-Fragment um das '=' aus Prosa ziehen ("ich denke 3x = 15" -> "3x = 15"):
        # zusammenhaengende Mathe-Zeichen links/rechts, Prosa-Woerter (>1 Buchstabe) verwerfen
        m = re.search(r"([0-9a-zA-Z+\-*/^().\s]+?)=\s*([0-9a-zA-Z+\-*/^().\s]+)", msg)
        if m:
            lhs_tokens = m.group(1).split()
            # fuehrende Prosa-Woerter (mehrbuchstabig, ohne Ziffern/Operatoren) abwerfen
            while lhs_tokens and re.fullmatch(r"[a-zA-Z]{2,}", lhs_tokens[0]):
                lhs_tokens.pop(0)
            rhs = m.group(2).split()
            rhs_tokens = []
            for t in rhs:
                if re.fullmatch(r"[a-zA-Z]{2,}", t):
                    break  # Prosa nach der Zahl ("15 oder?") kappen
                rhs_tokens.append(t)
            if lhs_tokens and rhs_tokens:
                frag = f"{' '.join(lhs_tokens)} = {' '.join(rhs_tokens)}"
                if frag != msg:
                    cands.append(frag)
    # 'x = ...' (Variable NICHT von Ziffer/Buchstabe direkt gefolgt, sonst ist es ein Koeffizient)
    for m in re.finditer(r"(?<![0-9a-zA-Z])[a-zA-Z]\s*=\s*[-+]?[0-9]+(?:\.[0-9]+)?(?:/[0-9]+)?", msg):
        cands.append(m.group(0))
    # führendes '= 5'
    m = re.search(r"^\s*=\s*([-+]?[0-9]+(?:\.[0-9]+)?)", msg)
    if m:
        cands.append(m.group(1))
    # eine einzelne Zahl – nur wenn die Nachricht kurz/antwortartig ist,
    # sonst matcht eine Zahl aus einer Prosa-Frage ("muss ich minus 5 rechnen?") faelschlich
    nums = re.findall(r"[-+]?[0-9]+(?:\.[0-9]+)?", msg)
    if (len(nums) == 1 and not cands and len(msg.split()) <= 3
            # «5 stimmt nicht» / «nicht 5» / «ist 5 falsch?» nennen die Zahl,
            # um sie ABZULEHNEN. Ohne diese Sperre galt die Aufgabe als geloest.
            and not _ABLEHNUNG.search(msg)
            # «1 tipp bitte» / «stufe 2 bitte» nennen die Zahl als Anzahl,
            # nicht als Antwort – galt sonst als falscher Rechenversuch.
            and not _HILFE_WORT.search(msg)):
        cands.append(nums[0])
    return cands


def _arithmetic_expression(text: str) -> str | None:
    """Reine Rechen-Aufgabe ohne «=» erkennen («2 + 4», «Berechne: 348 + 267»).

    Nur Ziffern/Operatoren/Klammern, mindestens ein Operator zwischen zwei
    Zahlen, und SymPy muss das Fragment zu einer ZAHL auswerten koennen.
    """
    msg = _normalize(text)
    label = re.match(r"^\s*[A-Za-zÀ-ÿ ]+:\s*(.+)$", msg)
    if label:
        msg = label.group(1)
    # Wurzel und Kreiszahl gehoeren zum Ausdruck. Frueher fielen alle
    # Buchstaben weg: aus «sqrt(6^2 + 8^2)» wurde «(6^2 + 8^2)» = 100 statt
    # 10, aus «pi * 5^2» wurde «5^2» – und die Nachrechnung haette eine
    # RICHTIGE Antwort des Kindes als falsch gestempelt. Alle anderen Woerter
    # (Prosa) bleiben draussen.
    msg = re.sub(r"\b(?!sqrt\b|pi\b)[A-Za-zÀ-ÿ]+\b", " ", msg)
    m = re.search(r"[-+]?(?:[0-9(]|sqrt\(|pi\b)[0-9+\-*/^(). ]*(?:(?:sqrt\(|pi\b)[0-9+\-*/^(). ]*)*", msg)
    if not m:
        return None
    frag = m.group(0).strip().rstrip("+-*/^(. ")
    hat_operator = re.search(r"[0-9)]\s*[+\-*/^]\s*[-+]?[0-9(]", frag)
    hat_funktion = re.search(r"sqrt\(|pi\b", frag)
    if not (hat_operator or (hat_funktion and re.search(r"[0-9]", frag))):
        return None  # einzelne Zahl ist keine Aufgabe
    try:
        value = _parse(frag)
    except Exception:
        return None
    return frag if getattr(value, "is_number", False) else None


def extract_expression(text: str) -> str | None:
    """Zieht aus einem Aufgabentext eine prüfbare Gleichung («Löse 3x = 15» -> «3x = 15»).

    Wird beim Anlegen einer Aufgabe als Fallback benutzt, wenn kein expliziter
    Mathe-Ausdruck hinterlegt wurde – sonst wäre die Aufgabe nie verifizierbar.
    """
    if not text:
        return None
    if "=" not in text:
        # Reine Rechen-Aufgaben («2 + 4») sind auch ohne «=» pruefbar.
        for ln in [l for l in text.splitlines() if l.strip()] or [text]:
            found = _arithmetic_expression(ln)
            if found:
                return found
        return None
    # «2 + 7 =» ist die normale Schreibweise auf dem Papier: das Gleichheits-
    # zeichen steht schon da, die Antwort fehlt noch. Vorher verlangte der
    # Zweig unten zwingend etwas RECHTS vom «=» – eine so geschriebene Aufgabe
    # bekam deshalb gar keinen Pruefausdruck und konnte nie «geloest» werden.
    gestutzt = text.rstrip()
    if gestutzt.endswith("="):
        return extract_expression(gestutzt[:-1])
    # Mehrzeilige Eingaben (Stift/Foto-Erkennung): erst Zeile fuer Zeile
    # versuchen, dann alles zu EINER Zeile verbunden («2 + 3\n= 2y»).
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) > 1:
        # nur Zeilen MIT «=» einzeln probieren – sonst schnappt sich der
        # Arithmetik-Zweig die erste Zeile einer zerteilten Gleichung
        for ln in lines:
            if "=" in ln:
                found = extract_expression(ln)
                if found:
                    return found
        return extract_expression(" ".join(lines))
    # Fuehrendes Prosa-Label mit Doppelpunkt abtrennen («Berechne x: 2x+4=10»),
    # damit der Doppelpunkt nicht als Division normalisiert wird.
    label = re.match(r"^\s*[A-Za-zÀ-ÿ ]+:\s*(.+)$", text)
    if label and "=" in label.group(1):
        text = label.group(1)
    msg = _normalize(text)
    if msg.count("=") > 1:
        # Mehrere Gleichungen in EINER Zeile: dann ist die erste eine Angabe,
        # nicht die Frage («a = 5, b = 3. Berechne a + b», «x + y = 10 und
        # x - y = 2»). Frueher wurde die erste als «die Aufgabe» gespeichert
        # und die richtige Antwort galt danach als falsch. Lieber keine
        # Pruefung als eine falsche.
        return None
    # Nicht-ASCII (ö, ü, é …) bricht den Match bewusst ab – Prosa fällt so heraus
    m = re.search(r"([0-9A-Za-z+\-*/^(). ]+)=\s*([0-9A-Za-z+\-*/^(). ]+)", msg)
    if not m:
        return None
    rhs_tokens: list[str] = []
    for t in m.group(2).split():
        if re.fullmatch(r"[A-Za-z]{2,}", t):
            break  # Prosa nach der rechten Seite kappen («… = 15 oder»)
        rhs_tokens.append(t)
    if not rhs_tokens:
        return None
    try:
        rhs = _parse(" ".join(rhs_tokens))
    except Exception:
        return None
    lhs_tokens = m.group(1).split()
    # Von links Prosa-Tokens abwerfen, bis eine loesbare Gleichung mit genau
    # einer einbuchstabigen Variablen uebrig bleibt («Berechne x wenn 2x+4 = 10»).
    # Es duerfen NUR reine Buchstaben-Woerter fallen – wird ein Mathe-Token
    # (Zahl, «3x», Operator) abgeworfen, waere die Rest-Gleichung eine ANDERE
    # Aufgabe («3x + 5 = 2y» darf nicht zu «+5 = 2y» verstuemmelt werden).
    while lhs_tokens:
        try:
            lhs = _parse(" ".join(lhs_tokens))
        except Exception:
            lhs = None
        if lhs is not None:
            syms = lhs.free_symbols | rhs.free_symbols
            # Prosa-Woerter zerfallen beim Parsen in lauter Einzelbuchstaben
            # («Berechne» -> B*e*r*e*c*h*n*e) und saehen sonst wie lauter
            # gueltige Variablen aus – erst weiter unten werden sie abgeworfen.
            prosa = any(re.fullmatch(r"[A-Za-zÀ-ÿ]{2,}", tok) for tok in lhs_tokens)
            # Frueher war hier len(syms) == 1 Pflicht. Damit fiel jede Aufgabe
            # mit zwei Unbekannten durch – z.B. «(2*x*5*y*8)/3 = y», die verify()
            # einwandfrei nach x aufloest. Folge: kein Pruefausdruck gespeichert,
            # der Tutor ohne jede Bodenhaftung.
            # Jetzt genuegt MINDESTENS EINE Variable – aber sie muss zu einer
            # ZAHL aufloesen. Ohne diese Bedingung landeten Prosa-Bruchstuecke
            # als «Aufgabe» in der DB («a = 5, b = 3. Berechne a + b» wurde zu
            # «a = 5. b», loesbar nach a als 5*b) und die richtige Antwort galt
            # danach als falsch – schlimmer als gar keine Pruefung.
            if not prosa and syms and all(len(str(s)) == 1 for s in syms):
                for s in sorted(syms, key=str):
                    sols = _solutions(lhs, rhs, s)
                    if sols and all(getattr(x, "is_number", False) for x in sols):
                        return f"{' '.join(lhs_tokens)} = {' '.join(rhs_tokens)}"
        if not re.fullmatch(r"[A-Za-zÀ-ÿ]+", lhs_tokens[0]):
            return None  # Mathe-Token muesste fallen -> keine saubere Gleichung
        lhs_tokens.pop(0)
    return None


def _latex_to_linear(s: str) -> str:
    """Uebliche LaTeX-Formen in lineare Schreibweise fuer die Nachrechnung."""
    s = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"(\1)/(\2)", s)
    s = (s.replace(r"\cdot", "*").replace(r"\times", "*").replace(r"\div", "/")
          .replace(r"\left", "").replace(r"\right", ""))
    s = re.sub(r"\^\{([^{}]+)\}", r"^(\1)", s)
    return s


def check_reply_math(text: str) -> list[tuple[str, str]]:
    """Rechnet rein NUMERISCHE Gleichungen in $…$-Formeln einer Tutor-Antwort nach.

    Liefert [(original_formel, richtiger_wert), …] fuer jede falsche
    Gleichung. Alles mit Variablen oder nicht Parsebares wird still
    uebersprungen – lieber ein Fehler verpasst als eine falsche Korrektur.
    """
    corrections: list[tuple[str, str]] = []
    for m in re.finditer(r"\$\$?([^$]+)\$\$?", text or ""):
        raw = m.group(1).strip()
        s = _latex_to_linear(raw)
        if "\\" in s or "=" not in s:
            continue  # unbekanntes LaTeX / keine Gleichung -> nicht pruefbar
        if "," in s or ":" in s:
            # In einer Formel heisst «1.000» Tausender und «1:30» eine Uhrzeit,
            # nicht Division. _normalize wuerde beides umdeuten und daraus
            # einen «Rechenfehler» erfinden.
            continue
        segments = [p.strip() for p in s.split("=")]
        if len(segments) < 2 or any(not p for p in segments):
            continue
        try:
            values = [_parse(p) for p in segments]
        except Exception:
            continue
        if not all(getattr(v, "is_number", False) for v in values):
            continue  # Variablen im Spiel -> keine reine Zahlen-Gleichung
        if any(v.atoms(sp.Float) for v in values):
            # Dezimalzahlen sind im Unterricht GERUNDET gemeint: «$1/3 = 0.33$»
            # ist richtig erklaert, wurde aber als Rechenfehler angestrichen
            # (und «$0.1 + 0.2 = 0.3$» wegen der Rechenungenauigkeit auch).
            continue
        if not all(bool(v.is_finite) for v in values):
            continue  # «$1/0 = 5$» -> sonst stuende «zoo» im Chat eines Kindes
        expected = values[0]  # erster Teil ist die Rechnung, dahinter das Resultat
        try:
            if any(sp.simplify(v - expected) != 0 for v in values[1:]):
                corrections.append((raw, str(sp.nsimplify(expected))))
        except Exception:
            continue
    return corrections


def verify(exercise_expr: str | None, message: str) -> Verification:
    """Prüft eine Schülerantwort gegen den Aufgaben-Ausdruck."""
    # Auch ohne pruefbare Aufgabe erkennen wir, OB eine Antwort versucht wurde –
    # sonst zaehlt die Hinweis-Leiter echte Versuche nicht (extracted -> intent 'attempt').
    _cands = _extract_candidates(message)
    _attempted = _cands[0] if _cands else None

    if not exercise_expr:
        return Verification("unknown", "kein Mathe-Ausdruck zur Aufgabe hinterlegt", extracted=_attempted)

    eq = _split_equation(exercise_expr)
    if eq is None:
        # Reine Rechen-Aufgabe («2 + 4»): Zahlenwert der Antwort vergleichen.
        try:
            expected = _parse(exercise_expr)
        except Exception:
            expected = None
        if expected is not None and getattr(expected, "is_number", False):
            sol_str = f"= {sp.nsimplify(expected)}"
            values = []
            for cand in _cands:
                ceq = _split_equation(cand)
                if ceq is not None:
                    # NUR die rechte Seite zaehlt: links steht die abgeschriebene
                    # Aufgabe, die logischerweise immer stimmt. Vorher galt
                    # «2+4 = 7» als richtig, weil die linke Seite 6 ergibt –
                    # und genau so schreiben Primarschueler ihre Antwort hin.
                    if ceq[1].is_number:
                        values.append(ceq[1])
                else:
                    try:
                        c = _parse(cand)
                        if c.is_number:
                            values.append(c)
                    except Exception:
                        pass
            if any(sp.simplify(v - expected) == 0 for v in values):
                return Verification("correct", "Zahlenwert stimmt", solution=sol_str,
                                    extracted=_attempted)
            if values:
                return Verification("incorrect", "Zahlenwert stimmt nicht", solution=sol_str,
                                    extracted=_attempted)
            return Verification("unknown", "keine Zahl in der Antwort erkannt",
                                solution=sol_str, extracted=_attempted)
        # Aufgabe ist keine Gleichung (z.B. Term mit Variablen) – nur grob prüfen
        return Verification("unknown", "Aufgabe ist keine Gleichung, keine deterministische Prüfung",
                            extracted=_attempted)

    lhs, rhs = eq
    sym = _free_symbol(lhs, rhs)
    if sym is None:
        return Verification("unknown", "keine Variable in der Aufgabe gefunden", extracted=_attempted)

    sols = _solutions(lhs, rhs, sym)
    sol_str = ", ".join(f"{sym} = {sp.nsimplify(s)}" for s in sols) if sols else None

    candidates = _cands  # oben schon berechnet – nicht zweimal analysieren
    if not candidates:
        return Verification("unknown", "keine Antwort im Text erkannt", solution=sol_str)

    wiederholung: Verification | None = None
    for cand in candidates:
        # Fall A: der/die Schüler:in nennt einen Wert für die Variable
        val_eq = _split_equation(cand)
        if val_eq is not None:
            c_lhs, c_rhs = val_eq
            # Fremd-Symbole (aus Prosa wie "ich glaube x = 5") -> kein sauberer Kandidat
            if (c_lhs.free_symbols | c_rhs.free_symbols) - {sym}:
                continue
            # Endantwort 'x = wert' – oder gespiegelt 'wert = x' («5/2 = y»)?
            value = None
            if c_lhs == sym and c_rhs.is_number:
                value = c_rhs
            elif c_rhs == sym and c_lhs.is_number:
                value = c_lhs
            if value is not None:
                for s in sols:
                    try:
                        if sp.simplify(value - s) == 0:
                            return Verification("correct", "Endwert stimmt", sol_str, cand)
                    except Exception:
                        pass
                return Verification("incorrect", "Endwert stimmt nicht", sol_str, cand)
            # Reines Wiederholen der Aufgabe (gleiche Seiten, evtl. vertauscht) ist
            # KEIN eigener Schritt – sonst liesse sich die Stufe-4-Sperre durch
            # zweimaliges Abtippen der Aufgabe aushebeln.
            try:
                same = sp.simplify(c_lhs - lhs) == 0 and sp.simplify(c_rhs - rhs) == 0
                swapped = sp.simplify(c_lhs - rhs) == 0 and sp.simplify(c_rhs - lhs) == 0
                if same or swapped:
                    # Kein eigener Schritt – aber die echte Antwort kann noch
                    # DAHINTER stehen («3x=15 also x=5», «3x = 15 | :3  x = 5»).
                    # Frueher stieg die Pruefung hier aus und verwarf sie.
                    if wiederholung is None:
                        wiederholung = Verification(
                            "unknown", "nur die Aufgabe wiederholt, kein eigener Schritt",
                            sol_str, cand)
                    continue
            except Exception:
                pass
            # Umformungsschritt: gleiche Lösungsmenge wie das Original?
            try:
                c_sols = _solutions(c_lhs, c_rhs, sym)
                if c_sols and sols and set(map(sp.simplify, c_sols)) == set(map(sp.simplify, sols)):
                    return Verification("partial", "gültiger Umformungsschritt", sol_str, cand)
            except Exception:
                pass
            return Verification("incorrect", "Umformung nicht äquivalent", sol_str, cand)

        # Fall B: nackte Zahl -> gegen Lösungen prüfen
        try:
            val = _parse(cand)
            if val.is_number:
                for s in sols:
                    if sp.simplify(val - s) == 0:
                        return Verification("correct", "Zahl stimmt", sol_str, cand)
                return Verification("incorrect", "Zahl stimmt nicht", sol_str, cand)
        except Exception:
            continue

    if wiederholung is not None:
        return wiederholung
    return Verification("unknown", "Antwort nicht eindeutig prüfbar", solution=sol_str)
