"""OCR hinter einem Interface (OcrProvider).

Vorerst pytesseract; spaeter z.B. Mathpix – nur diese Datei tauschen. Faellt
tesseract aus (nicht installiert), degradiert es sauber: der Preview im
Frontend erlaubt ohnehin die manuelle Korrektur des erkannten Ausdrucks.
"""
from __future__ import annotations

import io
import logging
from typing import Protocol

from ..schemas import OcrResult

log = logging.getLogger("schrittweise.ocr")


class OcrUnavailable(Exception):
    """Erkennung momentan nicht möglich (API-Fehler) – Aufrufer meldet es ehrlich."""


class OcrProvider(Protocol):
    name: str

    def recognize(self, image_bytes: bytes) -> OcrResult: ...


def _guess_math_expression(text: str) -> str | None:
    """Zieht einen nachrechenbaren Mathe-Ausdruck aus erkanntem Text.

    Dieselbe Pruefung wie beim Tippen. Die fruehere eigene Suche klebte
    Zeilen und Prosa zusammen («Löse 2x+4=10» -> «se2x+4=10»)."""
    from .sympy_verifier import extract_expression

    return extract_expression(text.replace("×", "*").replace("·", "*").replace("÷", "/"))


class PytesseractOcr:
    name = "pytesseract"

    def recognize(self, image_bytes: bytes) -> OcrResult:
        try:
            import pytesseract
            from PIL import Image

            img = Image.open(io.BytesIO(image_bytes))
            text = pytesseract.image_to_string(img, config="--psm 6")
            text = text.strip()
            expr = _guess_math_expression(text)
            return OcrResult(text=text, math_expression=expr)
        except Exception:
            # tesseract fehlt oder Bild nicht lesbar -> leer, manueller Fallback im UI
            return OcrResult(text="", math_expression=None)


def _trim_and_cap(image_bytes: bytes, max_edge: int = 1400) -> bytes:
    """Weissraum wegschneiden und Abmessungen deckeln, VOR dem Vision-Aufruf.

    Bezahlt werden Bild-Abmessungen, nicht Dateigroesse – eine
    Stift-Zeichnung ist aber meist zu zwei Dritteln leeres Blatt. Der
    Zuschnitt spart darum rund 40 % der Erkennungs-Kosten, ohne die
    Auflösung der Schrift selbst anzutasten (im Gegenteil: sie belegt
    danach einen groesseren Anteil der Pixel).

    Konservativ: zugeschnitten wird nur bei klar dokumentartigen Bildern
    (heller Hintergrund, wenig Tinte). Jeder Fehler -> Original zurueck,
    die Erkennung darf daran nie scheitern.
    """
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        img.load()
        fmt = (img.format or "PNG").upper()
        gray = img.convert("L")
        w, h = gray.size

        # Hintergrund = haeufigster Randwert; Tinte = deutlich dunkler
        corners = [gray.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
        bg = max(corners)
        cropped = None
        if bg >= 200:  # heller Hintergrund (Blatt/Canvas)
            mask = gray.point(lambda v: 255 if v < bg - 40 else 0)
            ink = mask.histogram()[255]  # Anzahl Tinte-Pixel
            box = mask.getbbox()  # Bounding-Box der Tinte (Nicht-Null-Pixel)
            if box and ink and ink < 0.30 * w * h:
                bw, bh = box[2] - box[0], box[3] - box[1]
                if bw * bh < 0.70 * w * h:
                    pad = 24
                    left = max(0, box[0] - pad)
                    top = max(0, box[1] - pad)
                    right = min(w, box[2] + pad)
                    bottom = min(h, box[3] + pad)
                    # Mindestkante 200 px: schmale Ausschnitte (eine flache
                    # Rechenzeile ist der Normalfall!) werden ERWEITERT, nicht
                    # verworfen – sonst greift der Zuschnitt fast nie.
                    if right - left < 200:
                        fehlt = (200 - (right - left) + 1) // 2
                        left, right = max(0, left - fehlt), min(w, right + fehlt)
                    if bottom - top < 200:
                        fehlt = (200 - (bottom - top) + 1) // 2
                        top, bottom = max(0, top - fehlt), min(h, bottom + fehlt)
                    cropped = img.crop((left, top, right, bottom))
        out = cropped if cropped is not None else img
        if max(out.size) > max_edge:
            out = out.copy()
            out.thumbnail((max_edge, max_edge))
        if out is img:
            return image_bytes  # nichts zu tun
        buf = io.BytesIO()
        if fmt == "PNG":
            out.save(buf, "PNG", optimize=True)
        else:
            out.convert("RGB").save(buf, "JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        log.debug("Bild-Zuschnitt uebersprungen", exc_info=True)
        return image_bytes


class ClaudeVisionOcr:
    """Erkennung über Claude Vision – liest auch Handschrift (Stift-Eingabe) zuverlässig."""

    name = "claude-vision"

    def __init__(self) -> None:
        # nach recognize(): {"model": ..., "usage": ...} fuer die Kostenerfassung
        self.last_usage: dict | None = None

    def recognize(self, image_bytes: bytes) -> OcrResult:
        self.last_usage = None
        try:
            import base64

            import anthropic
            from PIL import Image

            from ..config import settings

            # Weissraum weg + Abmessungen deckeln (spart Bild-Tokens)
            image_bytes = _trim_and_cap(image_bytes)
            fmt = (Image.open(io.BytesIO(image_bytes)).format or "PNG").lower()
            if fmt in ("jpeg", "png", "webp"):
                media_type = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[fmt]
            else:
                # HEIC (iPhone) & Co.: die API kennt das Format nicht – vor dem
                # Call nach JPEG re-encodieren, damit media_type und Bytes passen.
                buf = io.BytesIO()
                Image.open(io.BytesIO(image_bytes)).convert("RGB").save(buf, "JPEG", quality=90)
                image_bytes = buf.getvalue()
                media_type = "image/jpeg"
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            # Bewusst das staerkere Modell: Handschrift-Erkennung ist die
            # Kernfunktion der App – Erkennungsqualitaet schlaegt hier Kosten.
            # Kein temperature-Parameter: Sonnet 5 lehnt ihn ab (deprecated).
            resp = client.messages.create(
                model=settings.anthropic_model_smart,
                max_tokens=1000,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": base64.standard_b64encode(image_bytes).decode(),
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "Auf dem Bild ist eine Mathe-Aufgabe oder -Notiz einer "
                                    "Schuelerin/eines Schuelers (12-19 Jahre): GEDRUCKT (Foto aus "
                                    "Buch/Arbeitsblatt), HANDSCHRIFTLICH (Foto von Papier) oder mit "
                                    "dem STIFT GEZEICHNET (Tablet). Schrift kann krakelig, schraeg "
                                    "oder mehrzeilig sein.\n"
                                    "1) Transkribiere allen FLIESSTEXT (Aufgabenstellung) und alle "
                                    "RECHNUNGEN/FORMELN vollstaendig und in der Original-Reihenfolge "
                                    "(jede Zeile der Rechnung als eigene Zeile). Formeln linear "
                                    "schreiben: Brueche als a/b, Potenzen als x^2, Mal als *, Wurzel "
                                    "als sqrt(...). Beispiel: aus zwei handschriftlichen Zeilen wird\n"
                                    "3x + 5 = 20\n3x = 15\n"
                                    "KLAMMER-PFLICHT bei Bruechen: Hat Zaehler oder Nenner MEHR als "
                                    "ein Zeichen, setze Klammern – ein gestapelter Bruch 2x ueber 2 "
                                    "wird (2x)/2, 3 ueber 2y wird 3/(2y); nur einzelne Zeichen ohne "
                                    "Klammern (a/b). Ebenso mehrgliedrige Exponenten: x^(2y). Gib NIE "
                                    "eine mehrdeutige lineare Form aus – im Zweifel Klammern setzen.\n"
                                    "ABER: Zahlen und Beschriftungen, die zu einer Figur oder einem "
                                    "Graphen gehoeren (Seitenlaengen, Winkel, Punktnamen, "
                                    "Achsenwerte), gehoeren NICHT in die Transkription – sie kommen "
                                    "NUR in die Beschreibungszeile aus 2). Keine losen Fragmente wie "
                                    "'30' oder 'x' als eigene Zeilen ausgeben.\n"
                                    "Verwechsle nicht: 1 vs 7, x vs *, 6 vs b, 2 vs z. Kannst du ein "
                                    "Zeichen NICHT sicher lesen, schreib an seiner Stelle [?] – rate "
                                    "nicht, und ergaenze nie ein Gleichheitszeichen, eine Zahl oder "
                                    "einen Operator, der nicht eindeutig dasteht. Das Kind sieht deine "
                                    "Lesart vor dem Start und korrigiert die [?]-Stellen selbst.\n"
                                    "2) Enthaelt das Bild eine FIGUR, einen GRAPHEN oder ein "
                                    "KOORDINATENSYSTEM (auch von Hand gezeichnet), haenge danach "
                                    "GENAU EINE knappe Beschreibungszeile in eckigen Klammern an, "
                                    "mit allen erkennbaren Massen, Beschriftungen und Achsenwerten. "
                                    "Beispiele: [Figur: rechtwinkliges Dreieck, Katheten a = 6 cm "
                                    "und b = 8 cm, Hypotenuse c gesucht] oder [Graph: Gerade durch "
                                    "(0|-1) mit Steigung 2 im Koordinatensystem]. Die Zeile MUSS "
                                    "exakt mit [Figur: oder [Graph: beginnen – KEINE anderen Labels "
                                    "wie [Zeichnung: oder [Skizze:. Besteht das Bild "
                                    "NUR aus einer Figur/einem Graphen (keine Aufgabenstellung, "
                                    "keine Rechnung daneben), gib NUR diese Beschreibungszeile "
                                    "zurueck.\n"
                                    "Gib NUR Transkription und ggf. die Figur-Zeile zurueck, ohne "
                                    "Kommentar oder Einleitung. Wenn wirklich nichts erkennbar ist, "
                                    "gib exakt LEER zurueck."
                                ),
                            },
                        ],
                    }
                ],
            )
            self.last_usage = {"model": settings.anthropic_model_smart, "usage": resp.usage}
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            if text.upper() == "LEER":
                text = ""
            expr = _guess_math_expression(text)
            return OcrResult(text=text, math_expression=expr)
        except Exception as exc:
            # KEIN stiller pytesseract-Fallback mehr: der kann Handschrift nicht
            # und ist auf dem Server gar nicht installiert – das ergab "Konnte
            # nichts erkennen" ohne echten Grund. Ehrlich melden statt raten.
            log.exception("Claude-Vision-Erkennung fehlgeschlagen")
            from . import alert

            alert.notify("ocr", f"{type(exc).__name__}: {exc}")
            raise OcrUnavailable()



def get_ocr_provider() -> OcrProvider:
    from ..config import settings

    if settings.anthropic_api_key:
        return ClaudeVisionOcr()
    return PytesseractOcr()
