import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api.js";
import { useShell } from "./AppShell.jsx";
import DrawPad from "./DrawPad.jsx";
import { ProblemButton } from "./ProblemMelden.jsx";
import MathText from "../lib/MathText.jsx";
import { useLang } from "../lib/i18n.jsx";


// Neue Aufgabe: Foto-Upload mit OCR-Preview (Phase 3) + manuelle Eingabe.
export default function NewTaskModal({ onClose, presetTopicId }) {
  const nav = useNavigate();
  const shell = useShell();
  const { t } = useLang();
  const fileRef = useRef(null);   // Dateiauswahl (ohne capture)
  const cameraRef = useRef(null); // Kamera (capture=environment)
  const [text, setText] = useState("");
  const [expr, setExpr] = useState("");
  const [topicId, setTopicId] = useState(presetTopicId ? String(presetTopicId) : "");
  const [imagePath, setImagePath] = useState(null);
  const [fileName, setFileName] = useState(null);
  const [ocrBusy, setOcrBusy] = useState(false);
  const [ocrNote, setOcrNote] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [quotaOut, setQuotaOut] = useState(false); // 402: Kontingent aufgebraucht
  const [drag, setDrag] = useState(false);
  const [drawOpen, setDrawOpen] = useState(false);
  const [lastFile, setLastFile] = useState(null); // fuer «Nochmal versuchen» nach 503
  const [ocrText, setOcrText] = useState("");   // erkannter Text – still im Hintergrund
  const [ocrOpen, setOcrOpen] = useState(false); // Korrektur-Bereich aufgeklappt?

  // Waehrend des Anlegens nicht schliessen – sonst navigiert start() ins Leere
  // und verbraucht trotzdem Kontingent.
  const safeClose = () => { if (!busy) onClose(); };

  async function handleFile(file) {
    if (!file || !file.type.startsWith("image/")) return;
    setOcrBusy(true);
    setError(null);
    setFileName(file.name);
    setLastFile(file);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api.upload("/api/exercises/ocr", fd);
      setImagePath(res.image_path);
      // Das Foto BLEIBT die Aufgabe – der erkannte Text wandert nur still in
      // den Korrektur-Bereich (fuer die Mathe-Pruefung im Hintergrund).
      if (res.math_expression) setExpr(res.math_expression);
      if (res.text) {
        setOcrText(res.text);
        setOcrNote(t("✓ gelesen – prüf unten, ob es stimmt.", "✓ read – check below whether it's right."));
      } else {
        setOcrText("");
        setOcrNote(t("Ich konnte nichts lesen. Tipp die Aufgabe unten kurz ab – oder mach ein schärferes Foto.", "I couldn't read anything. Type the task below – or take a sharper photo."));
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setOcrBusy(false);
    }
  }

  // «Keine Aufgabe zur Hand»: KI erzeugt eine passende Aufgabe und startet sie
  async function generate() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const st = await api.post("/api/exercises/generieren", { topic_id: topicId ? Number(topicId) : null });
      shell.reloadQuota?.();
      shell.reloadTopics?.();
      onClose();
      nav(`/app/lernen/${st.attempt.id}`);
    } catch (err) {
      if (err.status === 402) setQuotaOut(err.grund || true);
      else setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function start() {
    if (!text.trim() && !imagePath) {
      setError(t("Schreib zuerst die Aufgabe auf (oder lad ein Foto hoch).", "Write down the task first (or upload a photo)."));
      return;
    }
    // Ein Foto ohne lesbaren Text startete frueher trotzdem – der Tutor bekam
    // dann Gekritzel als Aufgabe (real passiert: «Fg=»). Jetzt muss das Kind
    // abtippen, was die Erkennung nicht lesen konnte.
    if (imagePath && !ocrText.trim() && !text.trim()) {
      setError(t("Ich konnte auf dem Bild nichts lesen. Tipp die Aufgabe bitte kurz ab.", "I couldn't read anything on the image. Please type the task briefly."));
      return;
    }
    if (ocrText.includes("[?]")) {
      setError(t("Bei [?] war ich mir nicht sicher – ersetze die Stellen bitte durch das, was wirklich dasteht.", "I wasn't sure at [?] – please replace those spots with what is really there."));
      setOcrOpen(true);
      return;
    }
    const finalText = imagePath
      ? [text.trim(), ocrText.trim()].filter(Boolean).join("\n") || "(Aufgabe auf dem Foto)"
      : text.trim();
    setBusy(true);
    setError(null);
    try {
      const ex = await api.post("/api/exercises", {
        text: finalText,
        math_expression: expr.trim() || null,
        topic_id: topicId ? Number(topicId) : null,
        image_path: imagePath,
      });
      const attempt = await api.post(`/api/exercises/${ex.id}/attempts`, {});
      shell.reloadQuota?.();
      shell.reloadTopics?.();
      onClose();
      nav(`/app/lernen/${attempt.attempt.id}`);
    } catch (err) {
      if (err.status === 402) setQuotaOut(err.grund || true); // Sackgasse -> Kauf-Weg zeigen
      else setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div onClick={safeClose} style={{ position: "absolute", inset: 0, background: "rgba(20,20,40,.42)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 20 }}>
      <div onClick={(e) => e.stopPropagation()} className="popin" style={{ width: 560, maxWidth: "92vw", maxHeight: "90vh", overflowY: "auto", background: "#fff", borderRadius: 20, boxShadow: "0 30px 70px rgba(20,20,50,.35)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "18px 22px", borderBottom: "1px solid #eef0f3", position: "sticky", top: 0, background: "#fff" }}>
          <div style={{ fontSize: 17, fontWeight: 700 }}>{t("Neue Aufgabe", "New task")}</div>
          <span onClick={safeClose} style={{ width: 30, height: 30, borderRadius: "50%", background: "#f1f2f6", color: "#6b7280", display: "grid", placeItems: "center", fontSize: 15, cursor: "pointer" }}>✕</span>
        </div>
        <div style={{ padding: 22 }}>
          {/* Drag & Drop / Kamera */}
          <div
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); handleFile(e.dataTransfer.files?.[0]); }}
            style={{ border: `2px dashed ${drag ? "#6366f1" : "#c3c7f0"}`, background: drag ? "#eef0fe" : "#f7f8ff", borderRadius: 16, padding: 26, textAlign: "center", marginBottom: 16 }}
          >
            <div style={{ width: 54, height: 54, borderRadius: 16, background: "#eef0fe", color: "#4f46e5", fontSize: 24, display: "grid", placeItems: "center", margin: "0 auto 14px" }}>📷</div>
            <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 5 }}>{t("Foto hierher ziehen oder auswählen", "Drag a photo here or choose one")}</div>
            <div style={{ fontSize: 13, color: "#6b7280", marginBottom: 16 }}>{t("Auch krumm fotografiert oder handgeschrieben – wir erkennen es.", "Even crooked photos or handwriting – we'll recognize it.")}</div>
            <div style={{ display: "inline-flex", gap: 10, flexWrap: "wrap", justifyContent: "center" }}>
              <button onClick={() => fileRef.current?.click()} className="btn-primary" style={{ fontSize: 13, borderRadius: 10, padding: "10px 16px", border: "none" }}>{t("Datei wählen", "Choose file")}</button>
              <button onClick={() => cameraRef.current?.click()} className="btn-ghost" style={{ fontSize: 13, borderRadius: 10, padding: "10px 16px" }}>📸 {t("Kamera", "Camera")}</button>
              <button onClick={() => setDrawOpen(true)} className="btn-ghost" style={{ fontSize: 13, borderRadius: 10, padding: "10px 16px" }}>✍️ {t("Mit Stift schreiben", "Write with a pen")}</button>
            </div>
            {/* getrennte Inputs: capture erzwingt auf Mobile die Kamera – darf nur am Kamera-Button haengen */}
            <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }} onChange={(e) => { handleFile(e.target.files?.[0]); e.target.value = ""; }} />
            <input ref={cameraRef} type="file" accept="image/*" capture="environment" style={{ display: "none" }} onChange={(e) => { handleFile(e.target.files?.[0]); e.target.value = ""; }} />
          </div>

          {/* OCR-Preview */}
          {(fileName || ocrBusy) && (
            <div style={{ display: "flex", alignItems: "center", gap: 14, background: "#f6f7fb", border: "1px solid #eef0f3", borderRadius: 14, padding: "12px 14px", marginBottom: 16 }}>
              <div style={{ flex: "0 0 96px", height: 72, borderRadius: 10, background: "#fff", border: "1px solid #e7e8ee", display: "grid", placeItems: "center", fontFamily: "Georgia,serif", fontStyle: "italic", fontSize: 15, overflow: "hidden" }}>
                {imagePath ? <img src={`${api.base}${imagePath}`} alt={t("Dein Foto", "Your photo")} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : "…"}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{fileName || t("wird erkannt …", "recognizing …")}</div>
                <div style={{ fontSize: 12, color: ocrNote?.startsWith("✓") ? "#1a7f3c" : "#9aa0ab", lineHeight: 1.45 }}>{ocrBusy ? t("erkenne …", "recognizing …") : ocrNote}</div>
                {!ocrBusy && imagePath && (
                  // Falsch gelesen? Bild und erkannter Text gehen mit der
                  // Meldung mit – so sieht der Betreiber, was die Erkennung
                  // wirklich bekommen hat.
                  <div style={{ marginTop: 6 }}>
                    <ProblemButton klein attemptId={null} imagePath={imagePath} context={ocrText || "(nichts erkannt)"} />
                  </div>
                )}
                {!ocrBusy && !imagePath && lastFile && (
                  <button onClick={() => handleFile(lastFile)} style={{ marginTop: 6, border: "1px solid #c9ccf6", background: "#fff", color: "#4f46e5", borderRadius: 999, padding: "4px 12px", fontSize: 12, fontWeight: 700, cursor: "pointer" }}>
                    {t("↻ Nochmal versuchen", "↻ Try again")}
                  </button>
                )}
              </div>
              {imagePath && !ocrBusy && (
                <button
                  onClick={() => { setImagePath(null); setFileName(null); setLastFile(null); setOcrNote(null); setOcrText(""); setOcrOpen(false); setExpr(""); }}
                  title={t("Foto entfernen", "Remove photo")}
                  style={{ flex: "0 0 auto", width: 28, height: 28, borderRadius: "50%", border: "none", background: "#e7e8ee", color: "#6b7280", fontSize: 13, cursor: "pointer" }}
                >
                  ✕
                </button>
              )}
            </div>
          )}

          {imagePath && ocrText && !ocrBusy && (
            // «So habe ich es gelesen – stimmt das?» Die Lesart steht GROSS und
            // als Formel da, bevor der Chat beginnt. Frueher lag sie zugeklappt
            // in einem grauen Kasten, und Fehl-Erkennungen fielen erst im
            // Gespraech auf – wenn der Tutor schon damit rechnete.
            <div style={{ background: ocrText.includes("[?]") ? "#fdf8ec" : "#f8f8ff", border: `1px solid ${ocrText.includes("[?]") ? "#f0dcae" : "#e0e2fb"}`, borderRadius: 14, padding: "12px 14px", marginBottom: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: ".06em", color: "#4f46e5", marginBottom: 6 }}>
                {t("SO HABE ICH ES GELESEN – STIMMT DAS?", "THIS IS HOW I READ IT – IS IT RIGHT?")}
              </div>
              <div style={{ fontSize: 15, lineHeight: 1.55, marginBottom: 8 }}><MathText text={ocrText} /></div>
              {ocrText.includes("[?]") && (
                <div style={{ fontSize: 12.5, color: "#8a5a00", marginBottom: 8 }}>
                  {t("Bei [?] war ich mir nicht sicher. Bitte ersetze diese Stellen durch das, was wirklich dasteht.", "I wasn't sure at [?]. Please replace those spots with what is really there.")}
                </div>
              )}
              <button onClick={() => setOcrOpen(!ocrOpen)} style={{ border: "none", background: "transparent", color: "#4f46e5", fontSize: 12.5, fontWeight: 700, cursor: "pointer", padding: 0 }}>
                {ocrOpen ? t("▴ Korrektur schliessen", "▴ Close correction") : t("✎ Stimmt nicht ganz – korrigieren", "✎ Not quite – correct it")}
              </button>
              {ocrOpen && (
                <textarea
                  value={ocrText}
                  onChange={(e) => { setOcrText(e.target.value); setExpr(""); }}
                  rows={3}
                  autoFocus
                  style={{ width: "100%", marginTop: 8, border: "1px solid #c9ccf6", borderRadius: 10, padding: "9px 11px", fontSize: 13.5, resize: "vertical", outline: "none", background: "#fff", boxSizing: "border-box" }}
                />
              )}
            </div>
          )}

          <label style={{ fontSize: 12, fontWeight: 600, color: "#6b7280", display: "block", marginBottom: 6 }}>
            {imagePath ? t("Eigene Anmerkung (optional)", "Your note (optional)") : t("Deine Aufgabe", "Your task")}
          </label>
          {/* expr (Erkennungs-Ausdruck vom Foto) bleibt erhalten; nur wenn der
              TEXT die Aufgabe ist (kein Foto) oder der erkannte Text korrigiert
              wird, wird er verworfen – sonst wuerde ein veralteter Ausdruck
              gegen neuen Text geprueft. */}
          <textarea
            value={text}
            onChange={(e) => { setText(e.target.value); if (!imagePath) setExpr(""); }}
            placeholder={imagePath ? t("z.B. nur Teilaufgabe b) lösen", "e.g. only solve part b)") : t("z.B. Löse nach x auf: 3x + 5 = 20", "e.g. Solve for x: 3x + 5 = 20")}
            rows={2}
            style={{ width: "100%", border: "1px solid #d2d4dd", borderRadius: 12, padding: "11px 13px", fontSize: 14, resize: "vertical", outline: "none", marginBottom: 12 }}
          />

          {!imagePath && (
            <button
              type="button"
              onClick={generate}
              disabled={busy}
              style={{ border: "none", background: "transparent", color: "#4f46e5", fontSize: 12.5, fontWeight: 600, cursor: "pointer", padding: 0, marginBottom: 12, opacity: busy ? 0.6 : 1 }}
            >
              {busy ? t("✨ erstelle Aufgabe …", "✨ creating a task …") : t("✨ Keine Aufgabe zur Hand? Ich erstelle dir eine.", "✨ No task at hand? I'll create one for you.")}
            </button>
          )}
          <label style={{ fontSize: 12, fontWeight: 600, color: "#6b7280", display: "block", marginBottom: 6 }}>{t("Thema (optional)", "Topic (optional)")}</label>
          <select value={topicId} onChange={(e) => setTopicId(e.target.value)} style={{ width: "100%", border: "1px solid #d2d4dd", borderRadius: 12, padding: "11px 13px", fontSize: 14, outline: "none", marginBottom: 14, background: "#fff" }}>
            <option value="">{t("– kein Thema –", "– no topic –")}</option>
            {(shell.topics || []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>

          {error && <div style={{ fontSize: 13, color: "#c0392b", marginBottom: 12 }}>{error}</div>}

          {quotaOut && (() => {
            const grund = typeof quotaOut === "string" ? quotaOut : (shell.quota?.abo_enabled ? "trial" : "guthaben");
            const plusName = shell.quota?.plus_name || "Kniff Plus";
            const titel = grund === "fairuse" ? t("Wow – riesig viel geübt diesen Monat 🎉", "Wow – a huge amount of practice this month 🎉")
              : grund === "trial" ? t("Deine Gratis-Aufgaben sind aufgebraucht 🙌", "Your free tasks are used up 🙌")
                : t("Dein Guthaben ist aufgebraucht 🙌", "Your balance is used up 🙌");
            const text = grund === "fairuse" ? t("Ab dem 1. geht es weiter. Bis dahin: Pause verdient.", "It continues on the 1st. Until then: you've earned a break.")
              : grund === "trial" ? t(`Mit ${plusName} übst du weiter – so viel du willst, jederzeit kündbar.`, `With ${plusName} you keep practising – as much as you like, cancel anytime.`)
                : t("Du hast diesen Monat fleissig geübt! Mit einem Token-Paket geht es sofort weiter – oder du wartest auf den nächsten Monat (dann gibt es wieder 50 Gratis-Tokens).", "You've practiced a lot this month! With a token package you can continue right away – or wait for next month (another 50 free tokens).");
            return (
              <div style={{ background: "#fdf3e6", border: "1px solid #f2ddb8", borderRadius: 14, padding: "14px 16px", marginBottom: 14 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: "#a05c12", marginBottom: 4 }}>{titel}</div>
                <div style={{ fontSize: 12.5, color: "#6b7280", lineHeight: 1.55, marginBottom: grund === "fairuse" ? 0 : 12 }}>{text}</div>
                {grund !== "fairuse" && (
                  <button
                    onClick={() => { onClose(); nav("/app/preise"); }}
                    className="btn-primary"
                    style={{ fontSize: 13, borderRadius: 10, padding: "10px 18px", border: "none" }}
                  >
                    {grund === "trial" ? t(`${plusName} aktivieren →`, `Activate ${plusName} →`) : t("Tokens laden →", "Top up tokens →")}
                  </button>
                )}
              </div>
            );
          })()}

          <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 16, fontSize: 12, color: "#9aa0ab" }}>
            <span>🔒</span> {t("Dein Bild wird nur für die Erkennung verwendet und trainiert keine KI-Modelle.", "Your image is only used for recognition and does not train any AI models.")}
          </div>

          <button onClick={start} disabled={busy} className="btn-primary" style={{ width: "100%", borderRadius: 12, padding: 13, fontSize: 15, border: "none", opacity: busy ? 0.7 : 1 }}>
            {busy ? t("startet …", "starting …") : t("Loslegen →", "Let's go →")}
          </button>
        </div>
      </div>
      {drawOpen && (
        // stopPropagation: Klick auf den DrawPad-Hintergrund darf nur den
        // DrawPad schliessen, nicht (durchgereicht) auch dieses Modal.
        <div onClick={(e) => e.stopPropagation()}>
          <DrawPad
            onClose={() => setDrawOpen(false)}
            onResult={({ text: txt, imagePath: p }) => {
              if (p) {
                // Zeichnung wie ein Foto behandeln: das Bild ist die Aufgabe,
                // der erkannte Text wandert still in den Korrektur-Bereich.
                setImagePath(p);
                setFileName(t("Zeichnung", "Drawing"));
                setLastFile(null);
                setOcrText(txt || "");
                setOcrNote(txt ? t("✓ gelesen – prüf unten, ob es stimmt.", "✓ read – check below whether it's right.")
                               : t("Ich konnte nichts lesen. Tipp die Aufgabe unten kurz ab – oder zeichne grösser und deutlicher.", "I couldn't read anything. Type the task below – or draw bigger and clearer."));
                setExpr("");
              } else if (txt) {
                setText((prev) => (prev.trim() ? `${prev.trim()}\n${txt}` : txt));
                setExpr("");
              }
            }}
          />
        </div>
      )}
    </div>
  );
}
