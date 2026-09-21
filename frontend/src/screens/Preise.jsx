import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../lib/api.js";
import { useShell } from "../components/AppShell.jsx";
import { useLang } from "../lib/i18n.jsx";

function Feature({ children, color = "#1a7f3c" }) {
  return (
    <div style={{ fontSize: 13, display: "flex", gap: 9 }}>
      <span style={{ color, fontWeight: 700 }}>✓</span>
      {children}
    </div>
  );
}

// Altpfad (Token-Pakete) – bleibt, solange abo_enabled aus ist.
function PreiseAlt() {
  const nav = useNavigate();
  const shell = useShell();
  const { t } = useLang();
  const [params] = useSearchParams();
  const plan = shell.quota?.plan || "free";
  const [busyPkg, setBusyPkg] = useState(null); // Paket-Key waehrend des Checkouts
  const [note, setNote] = useState(null); // {type, text}
  // Ist die Zahlung freigeschaltet (Stripe-Schluessel gesetzt)? Sonst Kauf-
  // Knoepfe sperren statt die Schueler in eine Fehlermeldung laufen lassen.
  const [zahlungAktiv, setZahlungAktiv] = useState(null); // null = noch unbekannt
  useEffect(() => {
    api.get("/api/health").then((h) => setZahlungAktiv(h?.zahlung !== false)).catch(() => setZahlungAktiv(true));
  }, []);

  // Rückkehr von der Stripe-Bezahlseite (?zahlung=ok|abbruch)
  useEffect(() => {
    const z = params.get("zahlung");
    if (z === "ok") {
      setNote({ type: "ok", text: t("Zahlung erhalten – deine Tokens werden in wenigen Sekunden gutgeschrieben. 🎉", "Payment received – your tokens will be credited in a few seconds. 🎉") });
      // Webhook braucht evtl. 1–2 Sekunden; Kontingent verzögert nachladen
      const t1 = setTimeout(() => shell.reloadQuota?.(), 2500);
      const t2 = setTimeout(() => shell.reloadQuota?.(), 8000);
      return () => { clearTimeout(t1); clearTimeout(t2); };
    }
    if (z === "abbruch") {
      setNote({ type: "error", text: t("Zahlung abgebrochen – es wurde nichts belastet.", "Payment cancelled – nothing was charged.") });
    }
  }, [params, shell]);

  async function buy(pkg) {
    setBusyPkg(pkg);
    setNote(null);
    try {
      const res = await api.post("/api/pay/checkout", { package: pkg });
      window.location.href = res.url; // weiter zur Stripe-Bezahlseite (Karte/TWINT)
    } catch (e) {
      setNote({ type: "error", text: e.message });
      setBusyPkg(null);
    }
  }

  // Alt: drei Einmal-Pakete, kein Abo. 1 Token = 1 Rappen.
  const PAKETE = [
    { key: "schnupper", preis: "2.–", tokens: 200, hint: t("≈ 100–200 Antworten · zum Reinschnuppern", "≈ 100–200 answers · to try it out") },
    { key: "starter", preis: "9.–", tokens: 900, hint: t("≈ 500–900 Antworten · der Klassiker", "≈ 500–900 answers · the classic") },
    { key: "power", preis: "19.–", tokens: 1900, hint: t("≈ 1000–1900 Antworten", "≈ 1000–1900 answers"), beliebt: true },
  ];

  return (
    <div style={{ height: "100%", overflowY: "auto", background: "#fbfbfd", padding: "36px 40px" }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 24 }}>
        <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em" }}>{t("Preise & Tokens", "Prices & tokens")}</div>
        <span onClick={() => nav("/app/lernen")} style={{ marginLeft: "auto", fontSize: 12, fontWeight: 600, color: "#4f46e5", cursor: "pointer" }}>{t("← zur App", "← back to the app")}</span>
      </div>
      {zahlungAktiv === false && (
        <div style={{ maxWidth: 920, margin: "0 auto 18px", fontSize: 13, borderRadius: 12, padding: "11px 16px", background: "#fdf3e6", color: "#a05c12", border: "1px solid #f2ddb8" }}>
          {t("Der Token-Kauf wird gerade freigeschaltet – bis dahin kannst du mit den Gratis-Tokens weiterüben. Es wird nichts belastet.",
             "Token purchase is being enabled right now – until then you can keep practicing with your free tokens. Nothing will be charged.")}
        </div>
      )}
      {shell.quota?.unlimited && (
        <div style={{ maxWidth: 920, margin: "0 auto 18px", fontSize: 13, borderRadius: 12, padding: "11px 16px", background: "#eef0fe", color: "#4f46e5", border: "1px solid #dfe1fb" }}>
          {t("∞ Dein Betreiber-Konto ist unbegrenzt und gratis – kaufen brauchst du nichts. Die Kauf-Knöpfe bleiben nur zum Testen der Zahlung aktiv.",
             "∞ Your operator account is unlimited and free – you don't need to buy anything. The buy buttons stay active only for testing payments.")}
        </div>
      )}
      {note && (
        <div style={{ maxWidth: 920, margin: "0 auto 18px", fontSize: 13, borderRadius: 12, padding: "11px 16px", background: note.type === "error" ? "#fdecec" : "#e8f6ec", color: note.type === "error" ? "#c0392b" : "#1a7f3c", border: `1px solid ${note.type === "error" ? "#f5cccc" : "#cde7d6"}` }}>
          {note.text}
        </div>
      )}
      <div style={{ textAlign: "center", marginBottom: 28 }}>
        <div style={{ fontSize: 24, fontWeight: 800, letterSpacing: "-.025em", marginBottom: 8 }}>{t("Fair bleiben, ohne Bezahlschranke.", "Staying fair, with no paywall.")}</div>
        <div style={{ fontSize: 14, color: "#6b7280", maxWidth: "60ch", margin: "0 auto" }}>
          {t("Üben kostet nichts zum Start. Wer mehr will, lädt Tokens oder nimmt das Schul-Abo.", "Practicing is free to start. Want more? Top up tokens or get the school plan.")}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 18, maxWidth: 920, margin: "0 auto" }} className="preise-grid">
        {/* Gratis */}
        <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 18, padding: 24 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "#6b7280", marginBottom: 12 }}>{t("Gratis", "Free")}</div>
          <div style={{ fontSize: 32, fontWeight: 800, letterSpacing: "-.02em", marginBottom: 6 }}>0.–</div>
          <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 20 }}>{t("zum Ausprobieren", "to try things out")}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 11, marginBottom: 22 }}>
            <Feature>{t("50 Gratis-Tokens pro Monat", "50 free tokens per month")}</Feature>
            <Feature>{t("Alle Themen", "All topics")}</Feature>
            <Feature>{t("Foto-Upload", "Photo upload")}</Feature>
          </div>
          <div style={{ border: "1px solid #d2d4dd", borderRadius: 11, padding: 11, textAlign: "center", fontSize: 14, fontWeight: 600, color: plan === "free" ? "#1a1c22" : "#6b7280" }}>
            {plan === "free" ? t("Aktueller Plan", "Current plan") : t("Gratis", "Free")}
          </div>
        </div>

        {/* Token-Pakete (einmalig, kein Abo) */}
        <div style={{ background: "#1a1c22", borderRadius: 18, padding: 24, position: "relative", color: "#fff", transform: "translateY(-8px)", boxShadow: "0 20px 44px rgba(26,28,34,.28)" }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "#c9ccf6", marginBottom: 4 }}>{t("Token-Pakete", "Token packs")}</div>
          <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 16 }}>{t("einmalig kaufen · kein Abo · läuft nie ab", "one-time purchase · no subscription · never expires")}</div>

          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 18 }}>
            {PAKETE.map((p) => (
              <div key={p.key} style={{ background: p.beliebt ? "#26293346" : "transparent", border: `1px solid ${p.beliebt ? "#8b8ef7" : "#3a3d49"}`, borderRadius: 13, padding: "12px 14px", position: "relative" }}>
                {p.beliebt && (
                  <span style={{ position: "absolute", top: -9, right: 12, fontSize: 10, fontWeight: 700, color: "#1a1c22", background: "#fff", borderRadius: 999, padding: "2px 9px" }}>{t("Beliebt", "Popular")}</span>
                )}
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                      <span style={{ fontSize: 21, fontWeight: 800, letterSpacing: "-.02em" }}>{p.preis}</span>
                      <span style={{ fontSize: 12.5, color: "#c5c9d2" }}>{p.tokens} {t("Tokens", "tokens")}</span>
                    </div>
                    <div style={{ fontSize: 11, color: "#9aa0ab" }}>{p.hint}</div>
                  </div>
                  <button
                    onClick={() => buy(p.key)}
                    disabled={busyPkg !== null || zahlungAktiv === false}
                    className="btn-primary"
                    style={{ borderRadius: 10, padding: "9px 15px", fontSize: 13, opacity: (busyPkg && busyPkg !== p.key) || zahlungAktiv === false ? 0.5 : 1 }}
                  >
                    {busyPkg === p.key ? t("Moment …", "One sec …")
                      : zahlungAktiv === false ? t("bald", "soon") : t("Kaufen", "Buy")}
                  </button>
                </div>
              </div>
            ))}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 9, marginBottom: 14 }}>
            <Feature color="#8be0a4">{t("1 Token = 1 Rappen KI-Hilfe", "1 token = 1 rappen of AI help")}</Feature>
            <Feature color="#8be0a4">{t("Normale Antwort ≈ 1 Token · mit Foto ≈ 3–5", "Normal answer ≈ 1 token · with photo ≈ 3–5")}</Feature>
            <Feature color="#8be0a4">{t("Tokens laufen nie ab", "Tokens never expire")}</Feature>
            <Feature color="#8be0a4">{t("Karte oder TWINT", "Card or TWINT")}</Feature>
          </div>
          <div style={{ fontSize: 11, color: "#9aa0ab", textAlign: "center" }}>
            {t("Sichere Zahlung über Stripe · Minderjährige: bitte Eltern fragen", "Secure payment via Stripe · under 18? Please ask your parents")}
            <br />
            {t("Mit dem Kauf akzeptierst du die", "By purchasing you accept the")} <a href="/agb" target="_blank" rel="noreferrer" style={{ color: "#c9ccf6", textDecoration: "underline" }}>{t("AGB", "terms & conditions")}</a>
          </div>
        </div>

        {/* Schule */}
        <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 18, padding: 24 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "#6b7280", marginBottom: 12 }}>{t("Schule / Klasse", "School / class")}</div>
          <div style={{ fontSize: 24, fontWeight: 800, letterSpacing: "-.02em", marginBottom: 6 }}>{t("auf Anfrage", "on request")}</div>
          <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 20 }}>{t("pro Klasse / Jahr", "per class / year")}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 11, marginBottom: 22 }}>
            <Feature>{t("Unbegrenzt für alle", "Unlimited for everyone")}</Feature>
            <Feature>{t("Lehrpersonen-Dashboard", "Teacher dashboard")}</Feature>
            <Feature>{t("Rechnung an die Schule", "Invoice sent to the school")}</Feature>
          </div>
          <a
            href="mailto:mahmmouds62@gmail.com?subject=Schul-Abo%20Kniff"
            style={{ display: "block", border: "1px solid #d2d4dd", borderRadius: 11, padding: 11, textAlign: "center", fontSize: 14, fontWeight: 600, color: "#1a1c22" }}
          >
            {t("Kontakt aufnehmen", "Get in touch")}
          </a>
        </div>
      </div>
    </div>
  );
}


function chf(rappen) {
  const v = (rappen / 100).toFixed(2);
  return v.endsWith(".00") ? v.slice(0, -3) + ".–" : v;
}

// Kniff Plus: EIN Abo pro Kind, in Aufgaben gedacht statt in Tokens.
function PreisePlus({ quota }) {
  const nav = useNavigate();
  const shell = useShell();
  const { t } = useLang();
  const [params] = useSearchParams();
  const [intervall, setIntervall] = useState("monat");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);
  const [aboAktiv, setAboAktiv] = useState(null); // null = noch unbekannt
  useEffect(() => {
    api.get("/api/health").then((h) => setAboAktiv(h?.abo !== false)).catch(() => setAboAktiv(true));
  }, []);
  useEffect(() => {
    const z = params.get("zahlung");
    if (z === "ok") {
      setNote({ type: "ok", text: t("Zahlung erhalten – dein Abo ist in wenigen Sekunden aktiv. 🎉", "Payment received – your subscription will be active in a few seconds. 🎉") });
      const t1 = setTimeout(() => shell.reloadQuota?.(), 2500);
      const t2 = setTimeout(() => shell.reloadQuota?.(), 8000);
      return () => { clearTimeout(t1); clearTimeout(t2); };
    }
    if (z === "abbruch") setNote({ type: "error", text: t("Zahlung abgebrochen – es wurde nichts belastet.", "Payment cancelled – nothing was charged.") });
  }, [params, shell]);

  async function abschliessen() {
    setBusy(true);
    setNote(null);
    try {
      const res = await api.post("/api/pay/checkout", { intervall });
      window.location.href = res.url; // weiter zur Stripe-Bezahlseite (Karte/TWINT)
    } catch (e) {
      setNote({ type: "error", text: e.message });
      setBusy(false);
    }
  }

  const name = quota.plus_name;
  const monat = chf(quota.preise.monat);
  const jahr = chf(quota.preise.jahr);
  const proMonatImJahr = (quota.preise.jahr / 12 / 100).toFixed(2);
  const istPlus = quota.stufe === "plus";
  const karte = { background: "#fff", border: "1px solid #e7e8ee", borderRadius: 18, padding: 24 };

  return (
    <div style={{ height: "100%", overflowY: "auto", background: "#fbfbfd", padding: "36px 40px" }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 24 }}>
        <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em" }}>{name}</div>
        <span onClick={() => nav("/app/lernen")} style={{ marginLeft: "auto", fontSize: 12, fontWeight: 600, color: "#4f46e5", cursor: "pointer" }}>{t("← zur App", "← back to the app")}</span>
      </div>
      {aboAktiv === false && (
        <div style={{ maxWidth: 920, margin: "0 auto 18px", fontSize: 13, borderRadius: 12, padding: "11px 16px", background: "#fdf3e6", color: "#a05c12", border: "1px solid #f2ddb8" }}>
          {t(`${name} wird gerade freigeschaltet – bis dahin kannst du mit deinen Gratis-Aufgaben weiterüben. Es wird nichts belastet.`,
             `${name} is being enabled right now – until then you can keep practising with your free tasks. Nothing will be charged.`)}
        </div>
      )}
      {quota.unlimited && (
        <div style={{ maxWidth: 920, margin: "0 auto 18px", fontSize: 13, borderRadius: 12, padding: "11px 16px", background: "#eef0fe", color: "#4f46e5", border: "1px solid #dfe1fb" }}>
          {t("∞ Dein Betreiber-Konto ist unbegrenzt und gratis – kaufen brauchst du nichts. Der Knopf bleibt nur zum Testen der Zahlung aktiv.",
             "∞ Your operator account is unlimited and free – you don't need to buy anything. The button stays active only for testing payments.")}
        </div>
      )}
      {note && (
        <div style={{ maxWidth: 920, margin: "0 auto 18px", fontSize: 13, borderRadius: 12, padding: "11px 16px", background: note.type === "error" ? "#fdecec" : "#e8f6ec", color: note.type === "error" ? "#c0392b" : "#1a7f3c", border: `1px solid ${note.type === "error" ? "#f5cccc" : "#cde7d6"}` }}>
          {note.text}
        </div>
      )}
      <div style={{ textAlign: "center", marginBottom: 28 }}>
        <div style={{ fontSize: 24, fontWeight: 800, letterSpacing: "-.025em", marginBottom: 8 }}>{t("Gratis probieren. Dann so viel üben, wie du willst.", "Try it for free. Then practise as much as you like.")}</div>
        <div style={{ fontSize: 14, color: "#6b7280", maxWidth: "60ch", margin: "0 auto" }}>
          {t(`Die ersten ${quota.trial_tasks} Aufgaben sind geschenkt. Danach kostet ${name} weniger als eine Nachhilfestunde im Monat – und ist jederzeit kündbar.`,
             `The first ${quota.trial_tasks} tasks are on us. After that ${name} costs less than one tutoring lesson a month – and you can cancel anytime.`)}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 18, maxWidth: 920, margin: "0 auto" }} className="preise-grid">
        {/* Probe */}
        <div style={karte}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "#6b7280", marginBottom: 12 }}>{t("Probe", "Trial")}</div>
          <div style={{ fontSize: 32, fontWeight: 800, letterSpacing: "-.02em", marginBottom: 6 }}>0.–</div>
          <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 20 }}>{t("einmalig, ohne Zahlungsangaben", "once, no payment details")}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 11, marginBottom: 22 }}>
            <Feature>{t(`${quota.trial_tasks} Gratis-Aufgaben`, `${quota.trial_tasks} free tasks`)}</Feature>
            <Feature>{t("Alle Funktionen", "All features")}</Feature>
            <Feature>{t("Foto, Stift, Aufgabensammlung", "Photo, pen, task collection")}</Feature>
          </div>
          <div style={{ border: "1px solid #d2d4dd", borderRadius: 11, padding: 11, textAlign: "center", fontSize: 14, fontWeight: 600, color: quota.stufe === "trial" ? "#1a1c22" : "#6b7280" }}>
            {quota.stufe === "trial"
              ? t(`Noch ${quota.trial_left} von ${quota.trial_tasks}`, `${quota.trial_left} of ${quota.trial_tasks} left`)
              : quota.stufe === "gesperrt" ? t("Aufgebraucht", "Used up") : t("Probe", "Trial")}
          </div>
        </div>

        {/* Kniff Plus */}
        <div style={{ background: "#1a1c22", borderRadius: 18, padding: 24, position: "relative", color: "#fff", transform: "translateY(-8px)", boxShadow: "0 20px 44px rgba(26,28,34,.28)" }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "#c9ccf6", marginBottom: 4 }}>{name}</div>
          <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 14 }}>{t("pro Kind · jederzeit kündbar", "per child · cancel anytime")}</div>

          <div style={{ display: "flex", gap: 6, background: "#26293346", border: "1px solid #3a3d49", borderRadius: 11, padding: 4, marginBottom: 14 }}>
            {[["monat", t("Monatlich", "Monthly")], ["jahr", t("Jährlich", "Yearly")]].map(([k, label]) => (
              <button key={k} onClick={() => setIntervall(k)}
                style={{ flex: 1, border: "none", borderRadius: 8, padding: "8px 6px", fontSize: 12.5, fontWeight: 700, cursor: "pointer", background: intervall === k ? "#fff" : "transparent", color: intervall === k ? "#1a1c22" : "#c5c9d2" }}>
                {label}
              </button>
            ))}
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
            <span style={{ fontSize: 30, fontWeight: 800, letterSpacing: "-.02em" }}>CHF {intervall === "jahr" ? jahr : monat}</span>
            <span style={{ fontSize: 12.5, color: "#c5c9d2" }}>{intervall === "jahr" ? t("im Jahr", "per year") : t("im Monat", "per month")}</span>
          </div>
          <div style={{ fontSize: 11, color: "#9aa0ab", marginBottom: 16, minHeight: 15 }}>
            {intervall === "jahr" ? t(`entspricht ${proMonatImJahr} im Monat – zwei Monate geschenkt`, `equals ${proMonatImJahr} a month – two months free`) : t(`oder ${jahr} im Jahr`, `or ${jahr} a year`)}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 9, marginBottom: 18 }}>
            <Feature color="#8be0a4">{t("So viel üben, wie du willst", "Practise as much as you like")}</Feature>
            <Feature color="#8be0a4">{t("Foto, Stift, Aufgabensammlung, Probeprüfungen", "Photo, pen, task collection, mock exams")}</Feature>
            <Feature color="#8be0a4">{t("Elternansicht inklusive", "Parent view included")}</Feature>
            <Feature color="#8be0a4">{t("Karte oder TWINT · läuft bis zum Ende der bezahlten Zeit", "Card or TWINT · runs until the end of the paid period")}</Feature>
          </div>

          {istPlus ? (
            <button onClick={() => nav("/app/einstellungen?tab=abo")} className="btn-primary" style={{ width: "100%", borderRadius: 11, padding: 12, fontSize: 14, border: "none" }}>
              {t("Aktiv ✓ · Abo verwalten", "Active ✓ · manage subscription")}
            </button>
          ) : (
            <button onClick={abschliessen} disabled={busy || aboAktiv === false} className="btn-primary"
              style={{ width: "100%", borderRadius: 11, padding: 12, fontSize: 14, border: "none", opacity: busy || aboAktiv === false ? 0.5 : 1 }}>
              {busy ? t("Moment …", "One sec …") : aboAktiv === false ? t("bald", "soon") : t(`${name} aktivieren`, `Activate ${name}`)}
            </button>
          )}
          <div style={{ fontSize: 11, color: "#9aa0ab", textAlign: "center", marginTop: 12 }}>
            {t("Sichere Zahlung über Stripe · Minderjährige: bitte Eltern fragen", "Secure payment via Stripe · under 18? Please ask your parents")}
            <br />
            {t("Mit dem Abschluss akzeptierst du die", "By subscribing you accept the")} <a href="/agb" target="_blank" rel="noreferrer" style={{ color: "#c9ccf6", textDecoration: "underline" }}>{t("AGB", "terms & conditions")}</a>
          </div>
        </div>

        {/* Schule */}
        <div style={karte}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "#6b7280", marginBottom: 12 }}>{t("Schule / Klasse", "School / class")}</div>
          <div style={{ fontSize: 24, fontWeight: 800, letterSpacing: "-.02em", marginBottom: 6 }}>{t("auf Anfrage", "on request")}</div>
          <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 20 }}>{t("pro Klasse / Jahr", "per class / year")}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 11, marginBottom: 22 }}>
            <Feature>{t("Unbegrenzt für alle", "Unlimited for everyone")}</Feature>
            <Feature>{t("Lehrpersonen-Dashboard", "Teacher dashboard")}</Feature>
            <Feature>{t("Rechnung an die Schule", "Invoice sent to the school")}</Feature>
          </div>
          <a href="mailto:mahmmouds62@gmail.com?subject=Schul-Abo%20Kniff"
            style={{ display: "block", border: "1px solid #d2d4dd", borderRadius: 11, padding: 11, textAlign: "center", fontSize: 14, fontWeight: 600, color: "#1a1c22" }}>
            {t("Kontakt aufnehmen", "Get in touch")}
          </a>
        </div>
      </div>
      <div style={{ maxWidth: 920, margin: "22px auto 0", fontSize: 12, color: "#9aa0ab", textAlign: "center", lineHeight: 1.6 }}>
        {t(`Fair-Use: ${name} ist für Menschen gemacht. Bei aussergewöhnlich hoher Nutzung pausiert das Konto bis zum Monatsanfang – im Alltag merkt das niemand.`,
           `Fair use: ${name} is made for people. With exceptionally heavy use the account pauses until the start of the next month – nobody notices this in everyday use.`)}
      </div>
    </div>
  );
}

export default function Preise() {
  const shell = useShell();
  const { t } = useLang();
  const quota = shell.quota;
  if (!quota) return <div style={{ padding: 40, fontSize: 14, color: "#9aa0ab" }}>{t("lädt …", "loading …")}</div>;
  return quota.abo_enabled ? <PreisePlus quota={quota} /> : <PreiseAlt />;
}
