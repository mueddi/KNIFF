"""Stoerungen einordnen: Was ist passiert, was heisst es, muss jemand handeln?

Die Alert-Zeilen (services/alert.py) sind rohe Fehlertexte. Fuer den
Betreiber zaehlt eine andere Frage: Ist das ein voruebergehender Aussetzer,
den die App selbst abgefangen hat – oder ein Fehler, der bei jedem Aufruf
wiederkommt, bis jemand etwas aendert? Genau das entscheidet ``einordnen``,
regelbasiert und damit testbar.

Drei Stufen:
- ``handeln``:  kommt wieder, bis jemand etwas aendert (Code, Konfiguration,
                Schluessel, Geld) – oder es fehlt Nutzern etwas Wesentliches.
- ``pruefen``:  einmal hinschauen; kann harmlos sein, muss aber nicht.
- ``keine``:    voruebergehend und abgefangen; nur zur Kenntnis.

Haeufung hebt die Stufe: was dreimal in 24 Stunden passiert, ist kein
Aussetzer mehr. Die Meldungen sind pro Stunde und Fehlertyp gedrosselt –
die Zaehler sind also Untergrenzen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Ab so vielen Meldungen derselben Art in 24 Stunden steigt die Stufe.
HAEUFUNG_24H = 3

STUFEN = ("keine", "pruefen", "handeln")


@dataclass(frozen=True)
class Regel:
    id: str
    kind: str
    muster: str | None          # Regex auf den Fehlertext; None = jeder Text
    stufe: str
    titel: tuple[str, str]      # (de, en)
    bedeutung: tuple[str, str]
    massnahme: tuple[str, str]


# Reihenfolge ist Absicht: die erste passende Regel gilt. Spezifisches vor
# Allgemeinem, innerhalb einer Art zuerst die Fehler, die sicher wiederkommen.
REGELN: list[Regel] = [
    Regel("ki-code", "ki",
          r"TypeError|AttributeError|KeyError|NameError|ValueError|ImportError",
          "handeln",
          ("KI-Aufruf scheitert an einem Programmierfehler",
           "AI call fails on a programming error"),
          ("Der Aufruf scheitert im eigenen Code, bevor die Anfrage bei Anthropic ankommt. "
           "Das passiert bei JEDEM Aufruf dieser Art wieder, nicht nur einmal. Solange der "
           "Tutor ausweichen kann, bekommt der Schueler eine Antwort vom anderen Modell – "
           "aber nie vom eigentlich gewaehlten.",
           "The call fails in our own code before the request reaches Anthropic. It will "
           "happen on EVERY call of this kind, not just once. As long as the tutor can fall "
           "back, students get an answer from the other model – never from the intended one."),
          ("Fehlertext in den Vercel-Laufzeitprotokollen nachschlagen und den Code "
           "korrigieren. Bis dahin laeuft die App eingeschraenkt weiter.",
           "Look up the error text in the Vercel runtime logs and fix the code. Until then "
           "the app keeps running with reduced capability.")),
    Regel("ki-abgelehnt", "ki",
          r"BadRequest|invalid_request|Error code: 400|Authentication|Error code: 401|"
          r"Permission|Error code: 403|NotFound|Error code: 404|deprecated",
          "handeln",
          ("Anthropic lehnt die Anfrage ab", "Anthropic rejects the request"),
          ("Die API weist die Anfrage zurueck: falscher Parameter, unbekannter Modellname "
           "oder ein ungueltiger Schluessel. Das aendert sich nicht von selbst – jeder "
           "weitere Aufruf derselben Art scheitert genauso.",
           "The API rejects the request: wrong parameter, unknown model name or an invalid "
           "key. This does not fix itself – every further call of this kind fails the same way."),
          ("Meldungstext lesen: bei «deprecated» oder «invalid» den Parameter im Code "
           "anpassen, bei 401/403 den ANTHROPIC_API_KEY in Vercel pruefen.",
           "Read the message: for \"deprecated\" or \"invalid\" adjust the parameter in the "
           "code; for 401/403 check ANTHROPIC_API_KEY in Vercel.")),
    Regel("ki-ueberlastet", "ki",
          r"RateLimit|Error code: 429|Overloaded|overloaded|Error code: 529|InternalServer|Error code: 5\d\d",
          "keine",
          ("Anthropic ueberlastet – automatisch ausgewichen",
           "Anthropic overloaded – fell back automatically"),
          ("Das gewaehlte Modell war kurz ueberlastet oder gestoert. Die App hat auf das "
           "andere Modell gewechselt; der Schueler hat eine normale Antwort bekommen. Das "
           "geht von selbst vorbei.",
           "The chosen model was briefly overloaded or disrupted. The app switched to the "
           "other model; the student got a normal answer. This passes by itself."),
          ("Nichts – ausser es haeuft sich. Dann status.claude.com pruefen.",
           "Nothing – unless it piles up. Then check status.claude.com.")),
    Regel("ki-verbindung", "ki",
          r"Timeout|timed out|APIConnection|ConnectionError|ReadError|RemoteProtocolError",
          "keine",
          ("Verbindung zu Anthropic abgebrochen", "Connection to Anthropic dropped"),
          ("Die Anfrage ist ins Leere gelaufen oder die Antwort kam nicht rechtzeitig. "
           "Meist ein Netz-Aussetzer; die App hat ausgewichen oder dem Schueler ehrlich "
           "gesagt, dass er es nochmal versuchen soll.",
           "The request timed out or the answer did not arrive in time. Usually a network "
           "hiccup; the app fell back or honestly told the student to try again."),
          ("Nichts, solange es vereinzelt bleibt.", "Nothing, as long as it stays isolated.")),
    Regel("ki-pruefung", "ki", r"Probepruefung", "pruefen",
          ("Probepruefung konnte nicht erstellt werden", "Practice test could not be created"),
          ("Der Schueler hat auf «Pruefung starten» geklickt und eine Fehlermeldung "
           "bekommen. Es wurde nichts abgebucht.",
           "The student clicked \"start test\" and got an error. Nothing was charged."),
          ("Meldungstext lesen. Kommt es mehrfach vor, liegt es nicht am Netz.",
           "Read the message. If it recurs, it is not the network.")),
    Regel("ki-zeichnung", "ki", r"Zeichnung", "pruefen",
          ("Zeichnung konnte nicht gelesen werden", "Drawing could not be read"),
          ("Der Tutor hat eine Stift-Zeichnung nicht in Text verwandeln koennen und "
           "ohne sie geantwortet.",
           "The tutor could not turn a pen drawing into text and answered without it."),
          ("Bei Haeufung: Fehlertext in den Vercel-Protokollen nachschlagen.",
           "If it recurs: look up the error text in the Vercel logs.")),
    Regel("ki-ausweich", "ki", r"ausgewichen", "pruefen",
          ("Modell hat nicht geantwortet – ausgewichen",
           "Model did not answer – fell back"),
          ("Das gewaehlte Modell hat nicht geantwortet, das andere ist eingesprungen. Der "
           "Schueler hat eine Antwort bekommen. Ob das harmlos war, sagt der Fehlertext.",
           "The chosen model did not answer; the other one stepped in. The student got an "
           "answer. Whether this was harmless is told by the error text."),
          ("Fehlertext lesen: «overloaded»/529 ist harmlos, ein Python-Fehlername ist es nicht.",
           "Read the error text: \"overloaded\"/529 is harmless, a Python error name is not.")),
    Regel("ki-ausfall", "ki", None, "pruefen",
          ("KI hat nicht geantwortet", "AI did not answer"),
          ("Beide Modelle haben nicht geantwortet. Der Schueler hat die Meldung «technische "
           "Probleme, versuch es gleich nochmal» gesehen; seine Hilfe-Stufe ist nicht "
           "gestiegen und es wurde nichts abgebucht.",
           "Both models failed to answer. The student saw \"technical problems, try again in "
           "a moment\"; their hint level did not rise and nothing was charged."),
          ("Einmal: nichts. Mehrmals in kurzer Zeit: status.claude.com und die "
           "Vercel-Protokolle pruefen.",
           "Once: nothing. Several times in a short period: check status.claude.com and the "
           "Vercel logs.")),
    Regel("qualitaet-abgeschnitten", "ki-qualitaet", r"Token-Limit", "keine",
          ("Antwort am Token-Limit abgeschnitten", "Answer cut off at the token limit"),
          ("Der Tutor hat laenger geschrieben, als erlaubt war; der Schueler sah einen "
           "abgebrochenen Satz und musste nachfragen.",
           "The tutor wrote longer than allowed; the student saw a truncated sentence and "
           "had to ask again."),
          ("Bei Haeufung MAX_TOKENS im Tutor erhoehen oder den Prompt zur Laenge schaerfen.",
           "If it recurs, raise MAX_TOKENS in the tutor or tighten the prompt on length.")),
    Regel("qualitaet-rechenfehler", "ki-qualitaet", None, "keine",
          ("Rechenfehler des Tutors, automatisch korrigiert",
           "Tutor arithmetic slip, corrected automatically"),
          ("Die Nachrechnung hat in einer Tutor-Antwort einen Rechenfehler gefunden und "
           "die Korrektur direkt darunter angezeigt.",
           "The verifier found an arithmetic error in a tutor answer and showed the "
           "correction right below it."),
          ("Nichts. Das Sicherheitsnetz hat gegriffen.", "Nothing. The safety net worked.")),
    Regel("kosten-cache", "kosten", None, "pruefen",
          ("Prompt-Caching greift nicht", "Prompt caching is not taking effect"),
          ("Ein Tutor-Aufruf lief ohne Cache: der ganze Vorlauf wurde voll bezahlt. "
           "Fuer den Schueler unsichtbar, fuer die Kosten nicht.",
           "A tutor call ran without cache: the whole prefix was paid in full. Invisible to "
           "the student, not to the costs."),
          ("Auf der Kostenseite die Cache-Quote pro Modell anschauen. Bleibt sie tief, "
           "ist der Prompt unter der Mindestlaenge oder ein Block aendert sich jeden Turn.",
           "Check the cache hit rate per model on the costs page. If it stays low, the "
           "prompt is below the minimum length or a block changes every turn.")),
    Regel("ocr-abgelehnt", "ocr", r"BadRequest|Error code: 4\d\d|deprecated|Authentication",
          "handeln",
          ("Foto-Erkennung wird von Anthropic abgelehnt", "Photo recognition rejected by Anthropic"),
          ("Jedes Foto scheitert mit derselben Meldung, bis der Parameter oder Schluessel "
           "korrigiert ist. Schueler sehen «Erkennung nicht erreichbar».",
           "Every photo fails with the same message until the parameter or key is fixed. "
           "Students see \"recognition unavailable\"."),
          ("Meldungstext lesen und den Erkennungs-Aufruf im Code anpassen.",
           "Read the message and adjust the recognition call in the code.")),
    Regel("ocr-ausfall", "ocr", None, "pruefen",
          ("Foto-Erkennung ausgefallen", "Photo recognition failed"),
          ("Ein Foto konnte nicht gelesen werden; der Schueler wurde gebeten, es nochmal "
           "zu versuchen.",
           "A photo could not be read; the student was asked to try again."),
          ("Einmal: nichts. Mehrmals: Fehlertext pruefen.", "Once: nothing. Repeatedly: check the error text.")),
    Regel("webhook", "webhook", None, "handeln",
          ("Stripe-Zahlung ohne Gutschrift", "Stripe payment without credit"),
          ("Stripe hat eine Zahlung gemeldet, die App konnte sie aber nicht verbuchen – "
           "oder ein fremder Aufruf hat die Signaturpruefung nicht bestanden. Im ersten "
           "Fall hat jemand bezahlt und nichts bekommen.",
           "Stripe reported a payment the app could not book – or a foreign call failed the "
           "signature check. In the first case someone paid and got nothing."),
          ("Im Stripe-Dashboard die Sitzung suchen und dem Nutzer die Tokens von Hand "
           "gutschreiben (Admin → Nutzer). Bei «Signatur»: STRIPE_WEBHOOK_SECRET pruefen.",
           "Find the session in the Stripe dashboard and credit the user by hand (Admin → "
           "Users). For \"signature\": check STRIPE_WEBHOOK_SECRET.")),
    Regel("zahlung", "zahlung", None, "handeln",
          ("Zahlung oder Abo braucht Handarbeit", "Payment or subscription needs manual work"),
          ("Bei Stripe ist etwas passiert, das die App nicht allein erledigen konnte – zum "
           "Beispiel liess sich ein Abo vor einer Kontoloeschung nicht beenden (das Konto "
           "blieb deshalb bestehen), oder eine Zahlung wurde erstattet oder angefochten.",
           "Something happened at Stripe that the app could not finish on its own – e.g. a "
           "subscription could not be ended before an account deletion (so the account was "
           "kept), or a payment was refunded or disputed."),
          ("Meldungstext lesen und im Stripe-Dashboard das genannte Abo bzw. die Zahlung "
           "nachsehen; wenn noetig dort von Hand beenden oder erstatten.",
           "Read the message and look up the named subscription or payment in the Stripe "
           "dashboard; end or refund it there by hand if needed.")),
    Regel("mail", "mail", None, "handeln",
          ("Mail nicht verschickt", "Mail not sent"),
          ("Eine Bestaetigungs- oder Login-Mail ist nicht rausgegangen. Wer sich gerade "
           "registriert hat, kommt nicht in die App.",
           "A confirmation or login mail did not go out. Whoever just registered cannot get "
           "into the app."),
          ("Meldungstext lesen: bei Supabase-Fehlern die Auth-Logs in Supabase, bei "
           "SMTP-Fehlern Brevo (IP-Freigabe, Kontingent) pruefen.",
           "Read the message: for Supabase errors check the auth logs in Supabase, for SMTP "
           "errors check Brevo (IP authorisation, quota).")),
    Regel("server", "server", None, "handeln",
          ("Unerwarteter Server-Fehler", "Unexpected server error"),
          ("Eine Anfrage ist mit einem Fehler abgebrochen, den der Code nicht vorgesehen "
           "hat. Der Nutzer sah «Unerwarteter Fehler».",
           "A request aborted with an error the code did not anticipate. The user saw "
           "\"unexpected error\"."),
          ("Route und Fehlertext in der Meldung; Einzelheiten in den Vercel-Protokollen.",
           "Route and error text are in the message; details in the Vercel logs.")),
    Regel("client-harmlos", "client", r"ResizeObserver", "keine",
          ("Browser-Meldung ohne Folgen", "Browser notice without consequences"),
          ("Eine bekannte, harmlose Meldung des Browsers beim Umbrechen der Seite. "
           "Nutzer merken nichts.",
           "A known, harmless browser notice while re-laying out the page. Users notice nothing."),
          ("Nichts.", "Nothing.")),
    Regel("client", "client", None, "pruefen",
          ("Fehler in der App im Browser", "Error in the app in the browser"),
          ("Im Browser eines Nutzers ist ein Skriptfehler aufgetreten. Ob er etwas "
           "blockiert hat, sagt der Text.",
           "A script error occurred in a user's browser. Whether it blocked anything is "
           "told by the text."),
          ("Seite und Fehlertext lesen; bei Haeufung nachstellen.",
           "Read page and error text; reproduce if it recurs.")),
]


def regel_fuer(kind: str, detail: str) -> Regel:
    text = detail or ""
    for regel in REGELN:
        if regel.kind != kind:
            continue
        if regel.muster is None or re.search(regel.muster, text):
            return regel
    return Regel("unbekannt", kind, None, "pruefen",
                 (f"Stoerung «{kind}»", f"Incident \"{kind}\""),
                 ("Eine Meldung, fuer die es noch keine Einordnung gibt.",
                  "A message without a classification yet."),
                 ("Fehlertext lesen.", "Read the error text."))


def _hoeher(stufe: str) -> str:
    i = STUFEN.index(stufe)
    return STUFEN[min(i + 1, len(STUFEN) - 1)]


def stufe_mit_haeufung(regel: Regel, anzahl_24h: int) -> str:
    """Grundstufe der Regel, eine Stufe hoeher bei Haeufung in 24 Stunden."""
    if anzahl_24h >= HAEUFUNG_24H:
        return _hoeher(regel.stufe)
    return regel.stufe
