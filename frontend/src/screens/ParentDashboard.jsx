import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { useLang, gradeLabel } from "../lib/i18n.jsx";
import { ChildDashboard } from "./Eltern.jsx";
import { DeleteAccount, PasswordTab, chf } from "./Einstellungen.jsx";
import { useDialog } from "../lib/dialog.jsx";

// Eigenständige Eltern-Ansicht (Rolle parent). Kein Schüler-Sidebar.
// preview: Admin-Vorschau – zeigt dieselbe Ansicht mit den EIGENEN
// Übungsdaten (GET /api/parents/preview), zum Testen der Eltern-Sicht.
export default function ParentDashboard({ preview = false }) {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const { t, lang } = useLang();
  const [children, setChildren] = useState([]);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [active, setActive] = useState(0);
  const [kontoOpen, setKontoOpen] = useState(false);
  const [params] = useSearchParams();
  const [zahlungNote, setZahlungNote] = useState(null);

  const load = () => (preview
    ? api.get("/api/parents/preview").then((d) => setChildren([d]))
    : api.get("/api/parents/children").then(setChildren)
  ).catch(() => setChildren([]));
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // Rueckkehr von der Stripe-Bezahlseite: der Webhook braucht evtl. 1–2 Sekunden.
  useEffect(() => {
    const z = params.get("zahlung");
    if (z === "ok") {
      setZahlungNote({ type: "ok", text: t("Zahlung erhalten – das Abo ist in wenigen Sekunden aktiv. 🎉", "Payment received – the subscription will be active in a few seconds. 🎉") });
      const t1 = setTimeout(load, 2500);
      const t2 = setTimeout(load, 8000);
      return () => { clearTimeout(t1); clearTimeout(t2); };
    }
    if (z === "abbruch") setZahlungNote({ type: "error", text: t("Zahlung abgebrochen – es wurde nichts belastet.", "Payment cancelled – nothing was charged.") });
  }, [params]); // eslint-disable-line react-hooks/exhaustive-deps

  async function redeem(e) {
    e?.preventDefault();
    if (!code.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/parents/redeem", { invite_code: code.trim() });
      setCode("");
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const child = children[active];

  return (
    // Vorschau laeuft INNERHALB der App-Shell: dort selber scrollen und den
    // doppelten Logo-Kopfbalken weglassen; echte Eltern-Seite bleibt Vollseite.
    <div style={preview ? { height: "100%", overflowY: "auto", background: "#fbfbfd" } : { minHeight: "100vh", background: "#fbfbfd" }}>
      {!preview && (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 28px", borderBottom: "1px solid #eef0f3", background: "#fff" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <span style={{ width: 22, height: 22, borderRadius: 7, background: "#6366f1" }} />
          <span style={{ fontWeight: 800, fontSize: 16, color: "#4f46e5", letterSpacing: "-.02em" }}>Kniff</span>
          <span style={{ fontSize: 12, fontWeight: 600, color: "#6b7280", background: "#f1f2f6", borderRadius: 999, padding: "4px 12px", marginLeft: 8 }}>{t("Elternansicht", "Parent view")}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span style={{ fontSize: 13, color: "#6b7280" }}>{user?.display_name}</span>
          <span onClick={() => setKontoOpen(!kontoOpen)} style={{ fontSize: 12, fontWeight: 600, color: kontoOpen ? "#1a1c22" : "#4f46e5", cursor: "pointer" }}>⚙ {t("Konto", "Account")}</span>
          <button
            onClick={() => { logout(); nav("/login", { replace: true }); }}
            style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 14px", borderRadius: 999, border: "1px solid #e7e8ee", background: "#fff", color: "#1a1c22", fontSize: 12, fontWeight: 600, cursor: "pointer" }}
          >
            <span aria-hidden="true">⏻</span> {t("Abmelden", "Log out")}
          </button>
        </div>
      </div>
      )}

      {preview && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap", background: "#fdf3e6", borderBottom: "1px solid #f2ddb8", padding: "8px 28px", fontSize: 12.5, color: "#a05c12" }}>
          <span>
            {t("👁 Elternansicht (Vorschau): So sehen Eltern die Ansicht – gezeigt werden deine eigenen Übungsdaten.",
               "👁 Parent view (preview): this is what parents see – showing your own practice data.")}
          </span>
          <Link to="/app/lernen" style={{ fontSize: 12, fontWeight: 700, color: "#4f46e5", whiteSpace: "nowrap" }}>{t("← Zurück zur App", "← Back to the app")}</Link>
        </div>
      )}

      <div style={{ maxWidth: 1000, margin: "0 auto", padding: "24px 28px" }}>
        {children.length > 1 && (
          <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
            {children.map((k, i) => (
              <span key={i} onClick={() => setActive(i)} style={{ cursor: "pointer", fontSize: 13, fontWeight: 600, color: i === active ? "#4f46e5" : "#6b7280", background: i === active ? "#eef0fe" : "#fff", border: i === active ? "none" : "1px solid #e7e8ee", borderRadius: 999, padding: "7px 14px" }}>{k.student_display_name}</span>
            ))}
          </div>
        )}

        {child ? (
          <>
            <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 8 }}>
              <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em" }}>{child.student_display_name} · {gradeLabel(child.grade_level, lang)}</div>
            </div>
            {zahlungNote && (
              <div style={{ marginBottom: 14, fontSize: 13, borderRadius: 12, padding: "11px 16px", background: zahlungNote.type === "error" ? "#fdecec" : "#e8f6ec", color: zahlungNote.type === "error" ? "#c0392b" : "#1a7f3c", border: `1px solid ${zahlungNote.type === "error" ? "#f5cccc" : "#cde7d6"}` }}>
                {zahlungNote.text}
              </div>
            )}
            {!preview && <PlusBox child={child} onChanged={load} />}
            {child.shared ? (
              <ChildDashboard data={child} />
            ) : (
              <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 16, padding: 24, color: "#6b7280", fontSize: 14 }}>
                {child.student_display_name} {t("hat die Fortschritts-Freigabe (noch) nicht aktiviert. Du siehst Aggregate, sobald die Freigabe an ist.", "has not (yet) enabled progress sharing. You will see aggregated progress as soon as sharing is turned on.")}
              </div>
            )}
          </>
        ) : (
          <div style={{ textAlign: "center", maxWidth: 460, margin: "60px auto 0" }}>
            <div style={{ width: 64, height: 64, borderRadius: 18, background: "#eef0fe", color: "#4f46e5", fontSize: 28, display: "grid", placeItems: "center", margin: "0 auto 16px" }}>👪</div>
            <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 6 }}>{t("Kind verknüpfen", "Link your child")}</div>
            <div style={{ fontSize: 14, color: "#6b7280", marginBottom: 20 }}>{t("Gib den Einladungscode ein, den dein Kind dir aus der App gegeben hat. Du siehst nur den groben Fortschritt – nie einzelne Nachrichten.", "Enter the invite code your child gave you from the app. You only see high-level progress – never individual messages.")}</div>
          </div>
        )}

        {!preview && (
        <form onSubmit={redeem} style={{ display: "flex", gap: 10, marginTop: 24, maxWidth: 420 }}>
          <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder={t("Einladungscode, z.B. 8ZEWHBZT", "Invite code, e.g. 8ZEWHBZT")} style={{ flex: 1, border: "1px solid #d2d4dd", borderRadius: 11, padding: "11px 13px", fontSize: 14, outline: "none", letterSpacing: ".1em", fontFamily: "ui-monospace, monospace" }} />
          <button type="submit" disabled={busy} className="btn-primary" style={{ padding: "11px 20px", borderRadius: 11, fontSize: 14, border: "none" }}>{busy ? "…" : t("Verknüpfen", "Link")}</button>
        </form>
        )}
        {error && <div style={{ fontSize: 13, color: "#c0392b", marginTop: 10 }}>{error}</div>}

        {kontoOpen && (
          <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 16, padding: 24, marginTop: 28, maxWidth: 620 }}>
            <PasswordTab />
            <DeleteAccount />
          </div>
        )}

        {!preview && (
          <div style={{ fontSize: 11, color: "#9aa0ab", textAlign: "center", margin: "48px 0 24px" }}>
            <Link to="/impressum" style={{ color: "#9aa0ab", textDecoration: "underline" }}>{t("Impressum", "Legal notice")}</Link>
            {" · "}
            <Link to="/datenschutz" style={{ color: "#9aa0ab", textDecoration: "underline" }}>{t("Datenschutz", "Privacy")}</Link>
            {" · "}
            <Link to="/agb" style={{ color: "#9aa0ab", textDecoration: "underline" }}>{t("AGB", "Terms")}</Link>
          </div>
        )}
      </div>
    </div>
  );
}


// Kniff Plus aus der Elternansicht: Eltern zahlen, also schliessen sie das
// Abo hier ab und kuendigen es hier – das Kind muss nichts tun.
function PlusBox({ child, onChanged }) {
  const { t, lang } = useLang();
  const dialog = useDialog();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const q = child.plus;
  if (!q || !q.abo_enabled || q.unlimited || !child.student_id) return null;
  const name = q.plus_name || "Kniff Plus";
  const kind = child.student_display_name;
  const datum = q.abo_bis ? new Date(q.abo_bis).toLocaleDateString(lang === "en" ? "en-GB" : "de-CH") : "";

  async function kaufen(intervall) {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.post("/api/pay/checkout", { intervall, student_id: child.student_id });
      window.location.href = r.url; // weiter zur Stripe-Bezahlseite (Karte/TWINT)
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  }

  async function umstellen(kuendigen) {
    if (kuendigen) {
      const ja = await dialog.bestaetigen({
        titel: t(`${name} für ${kind} kündigen?`, `Cancel ${name} for ${kind}?`),
        text: t(`Das Abo läuft bis ${datum} weiter und verlängert sich danach nicht mehr. Bis dahin kannst du die Kündigung jederzeit zurücknehmen.`,
                `The subscription stays active until ${datum} and will not renew afterwards. Until then you can undo the cancellation at any time.`),
        bestaetigen: t("Kündigen", "Cancel subscription"),
        gefahr: true,
      });
      if (!ja) return;
    }
    setBusy(true);
    setErr(null);
    try {
      await api.post(kuendigen ? "/api/pay/abo/kuendigen" : "/api/pay/abo/weiter", { student_id: child.student_id });
      onChanged?.();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  const karte = { background: "#fff", border: "1px solid #e7e8ee", borderRadius: 16, padding: "16px 20px", marginBottom: 16, display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" };
  const knopf = { borderRadius: 11, padding: "10px 16px", fontSize: 13, fontWeight: 700, cursor: "pointer", border: "none", opacity: busy ? 0.6 : 1 };
  if (q.stufe === "plus") {
    return (
      <div style={karte}>
        <div style={{ flex: "1 1 260px" }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "#1a7f3c" }}>✨ {name} {t("aktiv", "active")}</div>
          <div style={{ fontSize: 12.5, color: "#6b7280", marginTop: 3 }}>
            {q.abo_gekuendigt
              ? t(`Gekündigt – aktiv bis ${datum}, danach keine Verlängerung.`, `Cancelled – active until ${datum}, no renewal afterwards.`)
              : t(`${q.abo_intervall === "jahr" ? "Jahresabo" : "Monatsabo"} · verlängert sich am ${datum} · jederzeit kündbar`, `${q.abo_intervall === "jahr" ? "Yearly" : "Monthly"} plan · renews on ${datum} · cancel anytime`)}
          </div>
          {err && <div style={{ fontSize: 12.5, color: "#c0392b", marginTop: 4 }}>{err}</div>}
        </div>
        <button onClick={() => umstellen(!q.abo_gekuendigt)} disabled={busy}
          style={{ ...knopf, border: "1px solid #e7e8ee", background: "#fff", color: q.abo_gekuendigt ? "#4f46e5" : "#6b7280", fontWeight: 600 }}>
          {q.abo_gekuendigt ? t("Kündigung zurücknehmen", "Undo cancellation") : t("Abo kündigen", "Cancel subscription")}
        </button>
      </div>
    );
  }
  const stand = q.stufe === "trial"
    ? t(`🎁 Noch ${q.trial_left} von ${q.trial_tasks} Gratis-Aufgaben`, `🎁 ${q.trial_left} of ${q.trial_tasks} free tasks left`)
    : q.stufe === "guthaben"
      ? t(`⚡ Guthaben aus einem früheren Kauf: ${q.token_balance} Tokens`, `⚡ Balance from an earlier purchase: ${q.token_balance} tokens`)
      : t("Die Gratis-Aufgaben sind aufgebraucht", "The free tasks are used up");
  return (
    <div style={{ ...karte, background: "#1a1c22", color: "#fff", border: "none" }}>
      <div style={{ flex: "1 1 260px" }}>
        <div style={{ fontSize: 12.5, color: "#c9ccf6" }}>{stand}</div>
        <div style={{ fontSize: 15, fontWeight: 700, marginTop: 4 }}>
          {t(`${name} für ${kind}: so viel üben, wie ${kind} will.`, `${name} for ${kind}: practise as much as ${kind} likes.`)}
        </div>
        <div style={{ fontSize: 12, color: "#9aa0ab", marginTop: 3 }}>{t("Karte oder TWINT · jederzeit kündbar · die Rechnung geht an dich", "Card or TWINT · cancel anytime · the invoice goes to you")}</div>
        {err && <div style={{ fontSize: 12.5, color: "#f7b2a3", marginTop: 4 }}>{err}</div>}
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button onClick={() => kaufen("monat")} disabled={busy} className="btn-primary" style={knopf}>
          {t(`Monatlich CHF ${chf(q.preise.monat)}`, `Monthly CHF ${chf(q.preise.monat)}`)}
        </button>
        <button onClick={() => kaufen("jahr")} disabled={busy} style={{ ...knopf, background: "#fff", color: "#1a1c22" }}>
          {t(`Jährlich CHF ${chf(q.preise.jahr)}`, `Yearly CHF ${chf(q.preise.jahr)}`)}
        </button>
      </div>
    </div>
  );
}
