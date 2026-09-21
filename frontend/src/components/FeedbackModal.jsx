import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { useLang } from "../lib/i18n.jsx";

// Feedback-Fenster: alle Eingeloggten koennen senden (wird in der DB
// gespeichert). Lesen tut der Betreiber auf der Admin-Seite «Rueckmeldungen»
// (screens/FeedbackAdmin.jsx) – dorthin fuehrt fuer ihn ein Knopf.
export default function FeedbackModal({ onClose }) {
  const { user } = useAuth();
  const { t } = useLang();
  const loc = useLocation();
  const nav = useNavigate();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState(null);

  async function send() {
    if (text.trim().length < 3 || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/feedback", { text: text.trim(), page: loc.pathname.slice(0, 80) });
      setSent(true);
      setText("");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(20,22,30,.45)", zIndex: 60, display: "grid", placeItems: "center", padding: 14 }}>
      <div onClick={(e) => e.stopPropagation()} className="popin" style={{ background: "#fff", borderRadius: 18, width: "min(560px, 100%)", maxHeight: "86vh", display: "flex", flexDirection: "column", overflow: "hidden", boxShadow: "0 20px 60px rgba(20,22,30,.25)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 18px", borderBottom: "1px solid #eef0f3" }}>
          <div style={{ fontSize: 15, fontWeight: 800 }}>💬 Feedback</div>
          <button onClick={onClose} aria-label={t("Schliessen", "Close")} style={{ border: "none", background: "transparent", fontSize: 18, color: "#9aa0ab", cursor: "pointer" }}>✕</button>
        </div>

        <div style={{ padding: 18 }}>
          {sent ? (
            <div style={{ textAlign: "center", padding: "18px 0" }}>
              <div style={{ fontSize: 30, marginBottom: 8 }}>🙏</div>
              <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>{t("Danke für dein Feedback!", "Thanks for your feedback!")}</div>
              <div style={{ fontSize: 13, color: "#6b7280", marginBottom: 16 }}>{t("Es hilft uns, Kniff besser zu machen.", "It helps us make Kniff better.")}</div>
              <button onClick={onClose} className="btn-primary" style={{ padding: "10px 20px", borderRadius: 10, fontSize: 13, border: "none" }}>{t("Schliessen", "Close")}</button>
            </div>
          ) : (
            <>
              <div style={{ fontSize: 13, color: "#6b7280", marginBottom: 10 }}>
                {t("Was gefällt dir? Was nervt? Was fehlt? Schreib es uns – wir lesen alles.", "What do you like? What's annoying? What's missing? Tell us – we read everything.")}
              </div>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={5}
                maxLength={2000}
                placeholder={t("Dein Feedback …", "Your feedback …")}
                autoFocus
                style={{ width: "100%", border: "1px solid #d2d4dd", borderRadius: 12, padding: "11px 13px", fontSize: 14, resize: "vertical", outline: "none", marginBottom: 10 }}
              />
              {error && <div style={{ fontSize: 13, color: "#c0392b", marginBottom: 10 }}>{error}</div>}
              <button onClick={send} disabled={busy || text.trim().length < 3} className="btn-primary" style={{ width: "100%", borderRadius: 11, padding: 12, fontSize: 14, border: "none", opacity: busy || text.trim().length < 3 ? 0.6 : 1 }}>
                {busy ? t("sendet …", "sending …") : t("Feedback senden", "Send feedback")}
              </button>
            </>
          )}

          {user?.is_admin && (
            <button
              onClick={() => {
                onClose();
                nav("/app/rueckmeldungen");
              }}
              style={{ marginTop: 14, width: "100%", background: "none", border: "1px dashed #c9ccf6", borderRadius: 10, padding: "9px 12px", fontSize: 12.5, fontWeight: 600, color: "#4f46e5", cursor: "pointer" }}
            >
              📝 {t("Alle Rückmeldungen ansehen →", "View all feedback →")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
