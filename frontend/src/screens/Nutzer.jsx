import { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { useLang } from "../lib/i18n.jsx";

// Admin-Support-Werkzeug: Nutzer suchen, Guthaben einsehen und korrigieren
// (Kulanz, Rückerstattung, verpasster Stripe-Webhook).
export default function Nutzer() {
  const { t } = useLang();
  const [q, setQ] = useState("");
  const [rows, setRows] = useState([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  const load = (query = q) => {
    setLoading(true);
    api
      .get(`/api/admin/nutzer?q=${encodeURIComponent(query)}`)
      .then((d) => { setRows(d); setErr(""); })
      .catch((e) => setErr(e.message || t("Konnte die Nutzerliste nicht laden.", "Could not load the user list.")))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(""); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div style={{ flex: 1, overflowY: "auto", background: "#fbfbfd" }}>
      <div style={{ maxWidth: 980, margin: "0 auto", padding: "28px 20px 60px" }}>
        <h1 style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em", margin: "0 0 6px" }}>{t("👥 Nutzer", "👥 Users")}</h1>
        <div style={{ fontSize: 13, color: "#6b7280", marginBottom: 18 }}>
          {t("Guthaben einsehen und korrigieren – jede Buchung wird mit Grund protokolliert.", "View and adjust balances – every entry is logged with a reason.")}
        </div>

        <form
          onSubmit={(e) => { e.preventDefault(); load(); }}
          style={{ display: "flex", gap: 8, marginBottom: 18, maxWidth: 460 }}
        >
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("E-Mail oder Name suchen …", "Search email or name …")}
            style={{ flex: 1, border: "1px solid #d2d4dd", borderRadius: 11, padding: "10px 14px", fontSize: 13 }}
          />
          <button type="submit" className="btn-primary" style={{ border: "none", borderRadius: 11, padding: "10px 18px", fontSize: 13 }}>
            {t("Suchen", "Search")}
          </button>
        </form>

        {err && (
          <div style={{ background: "#fdf0ee", border: "1px solid #f2c9c0", color: "#b3492f", borderRadius: 12, padding: "12px 16px", fontSize: 13, marginBottom: 16 }}>
            {err}
          </div>
        )}
        {loading && <div style={{ fontSize: 13, color: "#9aa0ab" }}>{t("lädt …", "loading …")}</div>}
        {!loading && rows.length === 0 && !err && (
          <div style={{ fontSize: 13, color: "#9aa0ab" }}>{t("Keine Nutzer gefunden.", "No users found.")}</div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {rows.map((u) => (
            <UserCard key={u.id} u={u} onChanged={() => load()} />
          ))}
        </div>
      </div>
    </div>
  );
}

function UserCard({ u, onChanged }) {
  const { t } = useLang();
  const [open, setOpen] = useState(false);
  const [tokens, setTokens] = useState("");
  const [grund, setGrund] = useState("");
  const [note, setNote] = useState(null); // {type, text}
  const [busy, setBusy] = useState(false);

  async function book() {
    const n = parseInt(tokens, 10);
    if (!n) {
      setNote({ type: "error", text: t("Anzahl Tokens angeben (z.B. 200 oder -50).", "Enter a number of tokens (e.g. 200 or -50).") });
      return;
    }
    if (grund.trim().length < 3) {
      setNote({ type: "error", text: t("Bitte einen kurzen Grund angeben.", "Please enter a brief reason.") });
      return;
    }
    setBusy(true);
    setNote(null);
    try {
      const res = await api.post(`/api/admin/nutzer/${u.id}/tokens`, { tokens: n, grund: grund.trim() });
      setNote({ type: "ok", text: t(`Gebucht – neues Guthaben: ${res.token_balance} Tokens.`, `Booked – new balance: ${res.token_balance} tokens.`) });
      setTokens("");
      setGrund("");
      onChanged();
    } catch (e) {
      setNote({ type: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 14, padding: "14px 16px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 220px", minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis" }}>
            {u.display_name} {u.is_admin && <span style={{ fontSize: 11, color: "#4f46e5" }}>{t("· Admin", "· Admin")}</span>}
          </div>
          <div style={{ fontSize: 12, color: "#6b7280", overflow: "hidden", textOverflow: "ellipsis" }}>{u.email}</div>
          <div style={{ fontSize: 11, color: "#9aa0ab" }}>
            {u.role === "parent" ? t("Elternteil", "Parent") : t("Schüler:in", "Student")} · {u.email_verified ? t("E-Mail bestätigt", "email verified") : t("unbestätigt", "unverified")}
            {u.erstellt ? ` · ${t("seit", "since")} ${new Date(u.erstellt).toLocaleDateString("de-CH")}` : ""}
            {u.stufe ? ` · ${u.stufe}${u.abo_bis ? ` ${t("bis", "until")} ${new Date(u.abo_bis).toLocaleDateString("de-CH")}${u.abo_gekuendigt ? ` (${t("gekündigt", "cancelled")})` : ""}` : ""}` : ""}
          </div>
        </div>
        <div style={{ display: "flex", gap: 18, fontSize: 12.5, color: "#6b7280" }}>
          <div><b style={{ color: "#1a1c22" }}>{u.token_balance}</b> {t("Guthaben", "balance")}</div>
          <div><b style={{ color: "#1a1c22" }}>{u.free_used_tokens}</b>/{u.monthly_free_tokens ?? 50} {t("gratis", "free")}</div>
          <div><b style={{ color: "#1a1c22" }}>{u.verbraucht_tokens}</b> {t("verbraucht", "used")}</div>
        </div>
        <button
          onClick={() => setOpen(!open)}
          style={{ border: "1px solid #e7e8ee", background: "#fbfbfd", borderRadius: 10, padding: "8px 13px", fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}
        >
          {open ? t("Schliessen", "Close") : t("± Tokens", "± Tokens")}
        </button>
      </div>

      {open && (
        <div style={{ borderTop: "1px solid #f4f5f8", marginTop: 12, paddingTop: 12, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input
            value={tokens}
            onChange={(e) => setTokens(e.target.value)}
            placeholder="+200 / -50"
            inputMode="numeric"
            style={{ width: 110, border: "1px solid #d2d4dd", borderRadius: 10, padding: "9px 12px", fontSize: 13 }}
          />
          <input
            value={grund}
            onChange={(e) => setGrund(e.target.value)}
            placeholder={t("Grund (z.B. Webhook verpasst, Kulanz)", "Reason (e.g. missed webhook, goodwill credit)")}
            style={{ flex: "1 1 220px", border: "1px solid #d2d4dd", borderRadius: 10, padding: "9px 12px", fontSize: 13 }}
          />
          <button onClick={book} disabled={busy} className="btn-primary" style={{ border: "none", borderRadius: 10, padding: "10px 16px", fontSize: 13 }}>
            {busy ? t("bucht …", "booking …") : t("Buchen", "Book")}
          </button>
          {note && (
            <div style={{ flexBasis: "100%", fontSize: 12.5, color: note.type === "error" ? "#b3492f" : "#1a7f3c" }}>
              {note.text}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
