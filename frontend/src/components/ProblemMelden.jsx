import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../lib/api.js";
import { useLang } from "../lib/i18n.jsx";

// «Problem melden»: ein Knopf, zwei Klicks. Das Kind waehlt, was schiefging;
// Aufgabe, letzte Nachrichten und Bild haengt der Server selbst an – das
// muss niemand abtippen. Landet beim Betreiber unter Stoerungen.
export function ProblemButton({ attemptId, imagePath, context, klein = false, style = {} }) {
  const { t } = useLang();
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="btn-ghost"
        title={t("Etwas ist schiefgelaufen? Sag es uns.", "Something went wrong? Tell us.")}
        style={{ fontSize: klein ? 11 : 12, padding: klein ? "5px 10px" : "8px 14px", borderRadius: 999, whiteSpace: "nowrap", ...style }}
      >
        ⚑ {t("Problem melden", "Report a problem")}
      </button>
      {open && <ProblemDialog attemptId={attemptId} imagePath={imagePath} context={context} onClose={() => setOpen(false)} />}
    </>
  );
}

export default function ProblemDialog({ attemptId, imagePath, context, onClose }) {
  const { t } = useLang();
  const loc = useLocation();
  const [category, setCategory] = useState(imagePath && !attemptId ? "erkennung" : "");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState(null);

  // Escape schliesst das Fenster – wie jedes andere Fenster der App.
  useEffect(() => {
    const zu = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", zu);
    return () => window.removeEventListener("keydown", zu);
  }, [onClose]);

  const KATEGORIEN = [
    ["erkennung", t("Foto oder Zeichnung wurde falsch gelesen", "Photo or drawing was read wrongly")],
    ["antwort", t("Die Antwort ist falsch oder ich verstehe sie nicht", "The answer is wrong or I don't understand it")],
    ["verraten", t("Kniff hat die Lösung einfach verraten", "Kniff just gave away the solution")],
    ["technik", t("Etwas funktioniert nicht (Fehler, hängt, lädt nicht)", "Something doesn't work (error, stuck, not loading)")],
    ["anderes", t("Etwas anderes", "Something else")],
  ];

  async function send() {
    if (!category || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/feedback", {
        kind: "problem",
        category,
        text: text.trim(),
        page: loc.pathname.slice(0, 80),
        attempt_id: attemptId ?? null,
        image_path: imagePath ?? null,
        context: context ? String(context).slice(0, 2000) : null,
      });
      setSent(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(20,22,30,.45)", zIndex: 70, display: "grid", placeItems: "center", padding: 14 }}>
      <div onClick={(e) => e.stopPropagation()} className="popin" style={{ background: "#fff", borderRadius: 18, width: "min(520px, 100%)", maxHeight: "86vh", overflowY: "auto", boxShadow: "0 20px 60px rgba(20,22,30,.25)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 18px", borderBottom: "1px solid #eef0f3" }}>
          <div style={{ fontSize: 15, fontWeight: 800 }}>⚑ {t("Problem melden", "Report a problem")}</div>
          <button onClick={onClose} aria-label={t("Schliessen", "Close")} style={{ border: "none", background: "transparent", fontSize: 18, color: "#9aa0ab", cursor: "pointer", width: 40, height: 40 }}>✕</button>
        </div>
        <div style={{ padding: 18 }}>
          {sent ? (
            <div style={{ textAlign: "center", padding: "12px 0" }}>
              <div style={{ fontSize: 30, marginBottom: 8 }}>🙏</div>
              <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>{t("Danke, ist angekommen.", "Thanks, received.")}</div>
              <div style={{ fontSize: 13, color: "#6b7280", marginBottom: 16 }}>
                {t("Wir schauen es uns an. Du kannst einfach weitermachen.", "We'll look into it. You can just carry on.")}
              </div>
              <button onClick={onClose} className="btn-primary" style={{ padding: "10px 20px", borderRadius: 10, fontSize: 13, border: "none" }}>{t("Weiter", "Continue")}</button>
            </div>
          ) : (
            <>
              <div style={{ fontSize: 13, color: "#6b7280", marginBottom: 10 }}>
                {t("Was ist passiert? Die Aufgabe und die letzten Nachrichten schicken wir automatisch mit.", "What happened? We send the task and the last messages along automatically.")}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 12 }}>
                {KATEGORIEN.map(([k, label]) => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setCategory(k)}
                    style={{ textAlign: "left", fontSize: 13, fontWeight: 600, borderRadius: 12, padding: "10px 12px", cursor: "pointer", background: category === k ? "#eef0fe" : "#fbfbfd", color: category === k ? "#4f46e5" : "#1a1c22", border: `1px solid ${category === k ? "#c9ccf6" : "#e7e8ee"}` }}
                  >
                    {category === k ? "● " : "○ "}{label}
                  </button>
                ))}
              </div>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={3}
                maxLength={2000}
                placeholder={t("Magst du noch etwas dazu sagen? (freiwillig)", "Anything else you want to add? (optional)")}
                style={{ width: "100%", border: "1px solid #d2d4dd", borderRadius: 12, padding: "10px 12px", fontSize: 13, resize: "vertical", outline: "none", marginBottom: 10, boxSizing: "border-box" }}
              />
              {error && <div style={{ fontSize: 13, color: "#c0392b", marginBottom: 10 }}>{error}</div>}
              <button onClick={send} disabled={busy || !category} className="btn-primary" style={{ width: "100%", borderRadius: 11, padding: 12, fontSize: 14, border: "none", opacity: busy || !category ? 0.6 : 1 }}>
                {busy ? t("sendet …", "sending …") : t("Melden", "Send")}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
