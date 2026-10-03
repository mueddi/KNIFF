import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api.js";
import { useLang } from "../lib/i18n.jsx";

const GROSS_KEY = "schrittweise:stift-gross";

// Zeichenfläche für Stift-/Finger-Eingabe: Striche werden als Bild an die
// OCR-Erkennung geschickt; das Ergebnis landet editierbar im Chat-Eingabefeld.
export default function DrawPad({ onResult, onClose }) {
  const { t } = useLang();
  const canvasRef = useRef(null);
  const wrapRef = useRef(null);
  const strokes = useRef([]); // Array von Strichen (je Array von Punkten) für Rückgängig
  const current = useRef(null);
  const aktiverZeiger = useRef(null); // nur dieser Zeiger zeichnet (Handballen-Schutz)
  const [hasInk, setHasInk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  // Grosses Fenster: mehr Platz zum Schreiben (und mehr Pixel fuer die
  // Erkennung). Die Wahl wird gemerkt – wer gross schreibt, will das immer.
  const [gross, setGross] = useState(() => {
    try {
      return localStorage.getItem(GROSS_KEY) === "1";
    } catch {
      return false;
    }
  });

  function toggleGross() {
    setGross((g) => {
      try {
        localStorage.setItem(GROSS_KEY, g ? "0" : "1");
      } catch { /* privater Modus o.ae. – dann halt nicht gemerkt */ }
      return !g;
    });
  }

  // Canvas an Containergrösse anpassen, Striche neu zeichnen.
  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    let letzte = { w: 0, h: 0 };
    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const { width, height } = wrap.getBoundingClientRect();
      const w = Math.round(width);
      const h = Math.round(height);
      // Nur bei echter Aenderung anfassen – sonst kann der ResizeObserver
      // sich selbst wieder auslösen («ResizeObserver loop»).
      if (!w || !h || (w === letzte.w && h === letzte.h)) return;
      // Geschriebenes MITNEHMEN, wenn die Flaeche sich aendert. Die Striche
      // liegen in Pixeln der Flaeche: dreht das Kind das Handy quer (oder
      // drueckt ⤡), schrumpfte die Hoehe – und alles darunter war unsichtbar
      // UND aus dem gesendeten Bild herausgeschnitten, ohne Rueckgaengig.
      // Gleichmaessiger Massstab, damit die Schrift nicht verzerrt.
      if (letzte.w && letzte.h && strokes.current.length) {
        const f = Math.min(w / letzte.w, h / letzte.h);
        if (f !== 1) {
          for (const stroke of strokes.current) {
            for (const p of stroke) {
              p.x *= f;
              p.y *= f;
            }
          }
        }
      }
      letzte = { w, h };
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      redraw();
    };
    resize();
    // ResizeObserver statt window-resize: erfasst auch das Vergroessern per
    // Knopf, nicht nur eine Aenderung der Browserfenster-Groesse.
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);
    return () => ro.disconnect();
  }, []);

  function ctx2d() {
    return canvasRef.current.getContext("2d");
  }

  function redraw() {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = ctx2d();
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "#1a1c22";
    ctx.lineWidth = 3.2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (const stroke of strokes.current) {
      if (stroke.length < 2) {
        // Punkt (z.B. Dezimalpunkt) sichtbar machen
        ctx.beginPath();
        ctx.arc(stroke[0].x, stroke[0].y, 1.4, 0, Math.PI * 2);
        ctx.fillStyle = "#1a1c22";
        ctx.fill();
        continue;
      }
      ctx.beginPath();
      ctx.moveTo(stroke[0].x, stroke[0].y);
      for (const p of stroke.slice(1)) ctx.lineTo(p.x, p.y);
      ctx.stroke();
    }
  }

  function pos(e) {
    const rect = canvasRef.current.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function down(e) {
    // Nur EIN Zeiger zeichnet. Ohne das zog die aufliegende Handflaeche (oder
    // ein zweiter Finger) einen langen Strich quer durchs Bild, der zwischen
    // Hand und Stift hin- und hersprang – und genau so an die Erkennung ging.
    if (aktiverZeiger.current !== null) return;
    e.preventDefault();
    aktiverZeiger.current = e.pointerId;
    canvasRef.current.setPointerCapture?.(e.pointerId);
    current.current = [pos(e)];
  }
  function move(e) {
    if (!current.current || e.pointerId !== aktiverZeiger.current) return;
    e.preventDefault();
    current.current.push(pos(e));
    // Strich live zeichnen (voller Redraw erst beim Absetzen)
    const ctx = ctx2d();
    const pts = current.current;
    const a = pts[pts.length - 2] || pts[pts.length - 1];
    const b = pts[pts.length - 1];
    ctx.strokeStyle = "#1a1c22";
    ctx.lineWidth = 3.2;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }
  function up(e) {
    // Der abgesetzte Finger muss der zeichnende sein – sonst beendet die
    // Handflaeche den Strich des Stifts.
    if (e && e.pointerId !== aktiverZeiger.current) return;
    aktiverZeiger.current = null;
    if (!current.current) return;
    strokes.current.push(current.current);
    current.current = null;
    setHasInk(true);
    redraw();
  }

  function undo() {
    strokes.current.pop();
    setHasInk(strokes.current.length > 0);
    redraw();
  }
  function clearAll() {
    strokes.current = [];
    setHasInk(false);
    redraw();
  }

  // Export in hoher Aufloesung: die Striche auf einen Offscreen-Canvas mit
  // mind. 2x-Massstab neu zeichnen – mehr Pixel = deutlich bessere Erkennung
  // (der sichtbare Canvas hat nur Bildschirmaufloesung).
  function exportBlob() {
    const { width, height } = wrapRef.current.getBoundingClientRect();
    // Mindestens 2x fuer die Erkennung, aber die lange Kante bei 2600 px
    // deckeln: beim grossen Fenster waere das Bild sonst unnoetig schwer
    // (der Server verkleinert fuer die Erkennung ohnehin auf max. 1400 px).
    const deckel = 2600 / Math.max(width, height, 1);
    const scale = Math.max(Math.min(Math.max(window.devicePixelRatio || 1, 2), deckel), 1);
    const out = document.createElement("canvas");
    out.width = Math.round(width * scale);
    out.height = Math.round(height * scale);
    const ctx = out.getContext("2d");
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, width, height);
    ctx.strokeStyle = "#1a1c22";
    ctx.lineWidth = 3.2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (const stroke of strokes.current) {
      if (stroke.length < 2) {
        ctx.beginPath();
        ctx.arc(stroke[0].x, stroke[0].y, 1.4, 0, Math.PI * 2);
        ctx.fillStyle = "#1a1c22";
        ctx.fill();
        continue;
      }
      ctx.beginPath();
      ctx.moveTo(stroke[0].x, stroke[0].y);
      for (const p of stroke.slice(1)) ctx.lineTo(p.x, p.y);
      ctx.stroke();
    }
    return new Promise((resolve) => out.toBlob(resolve, "image/png"));
  }

  async function recognize() {
    if (!hasInk || busy) return;
    setBusy(true);
    setError(null);
    try {
      const blob = await exportBlob();
      const fd = new FormData();
      fd.append("file", blob, "stift-eingabe.png");
      const res = await api.upload("/api/exercises/ocr", fd);
      // Vollen erkannten Text nehmen – math_expression ist nur ein per Regex
      // herausgezogenes Fragment (mit «=») und verstuemmelt mehrzeilige Rechnungen.
      const text = (res.text || res.math_expression || "").trim();
      if (!text && !res.image_path) {
        setError(t("Konnte nichts erkennen – schreib etwas grösser und deutlicher.", "Couldn't recognize anything – write a bit bigger and clearer."));
        return;
      }
      // Zeichnung haengt als Bild an der Nachricht – auch ohne erkannten Text
      onResult({ text, imagePath: res.image_path || null });
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const btn = {
    border: "1px solid #d2d4dd",
    background: "#fff",
    borderRadius: 10,
    padding: "9px 14px",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(20,22,30,.45)", zIndex: 60, display: "grid", placeItems: "center", padding: 14 }} onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff", borderRadius: 18, display: "flex", flexDirection: "column",
          overflow: "hidden", boxShadow: "0 20px 60px rgba(20,22,30,.25)",
          width: gross ? "min(1180px, 100%)" : "min(680px, 100%)",
          // Gross: Fenster fuellt den Bildschirm, die Flaeche waechst mit (unten flex:1)
          height: gross ? "calc(100vh - 28px)" : undefined,
          maxHeight: "calc(100vh - 28px)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, padding: "14px 18px", borderBottom: "1px solid #eef0f3" }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 800 }}>✍️ {t("Mit dem Stift schreiben", "Write with a pen")}</div>
            <div style={{ fontSize: 12, color: "#9aa0ab" }}>{t("Schreib oder zeichne – ich lese es, und deine Zeichnung hängt als Bild an der Nachricht.", "Write or draw – I'll read it, and your drawing is attached to the message as an image.")}</div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 4, flexShrink: 0 }}>
            <button
              onClick={toggleGross}
              title={gross ? t("Kleiner", "Smaller") : t("Grösser", "Bigger")}
              aria-label={gross ? t("Fenster verkleinern", "Shrink window") : t("Fenster vergrössern", "Enlarge window")}
              style={{ border: "1px solid #e7e8ee", background: "#fff", borderRadius: 9, minWidth: 40, minHeight: 40, padding: "6px 10px", fontSize: 14, color: "#6b7280", cursor: "pointer", lineHeight: 1 }}
            >
              {gross ? "⤡" : "⤢"}
            </button>
            <button onClick={onClose} aria-label={t("Schliessen", "Close")} style={{ border: "none", background: "transparent", fontSize: 18, color: "#9aa0ab", cursor: "pointer", width: 40, height: 40 }}>✕</button>
          </div>
        </div>

        <div
          ref={wrapRef}
          style={{
            background: "#fff", touchAction: "none", cursor: "crosshair",
            borderBottom: "1px solid #eef0f3",
            backgroundImage: "repeating-linear-gradient(#fff, #fff 34px, #f0f1f6 35px)",
            // Gross: den ganzen freien Platz nehmen; sonst feste Hoehe wie bisher
            ...(gross ? { flex: 1, minHeight: 0 } : { height: "min(46vh, 340px)" }),
          }}
        >
          <canvas
            ref={canvasRef}
            onPointerDown={down}
            onPointerMove={move}
            onPointerUp={up}
            onPointerCancel={up}
            style={{ display: "block", touchAction: "none" }}
          />
        </div>

        {error && (
          <div style={{ margin: "10px 18px 0", fontSize: 13, background: "#fdecec", color: "#c0392b", border: "1px solid #f5cccc", borderRadius: 10, padding: "8px 12px" }}>{error}</div>
        )}

        <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8, padding: "12px 14px" }}>
          <button onClick={undo} disabled={!hasInk} style={{ ...btn, opacity: hasInk ? 1 : 0.5 }}>↩ {t("Rückgängig", "Undo")}</button>
          <button onClick={clearAll} disabled={!hasInk} style={{ ...btn, opacity: hasInk ? 1 : 0.5 }}>🗑 {t("Löschen", "Clear")}</button>
          <button
            onClick={recognize}
            disabled={!hasInk || busy}
            className="btn-primary"
            style={{ marginLeft: "auto", borderRadius: 10, padding: "10px 18px", fontSize: 13, opacity: !hasInk || busy ? 0.6 : 1 }}
          >
            {busy ? t("wird gelesen …", "reading …") : t("✓ Übernehmen", "✓ Use it")}
          </button>
        </div>
      </div>
    </div>
  );
}
