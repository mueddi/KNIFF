import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { useLang, GRADE_KEYS, gradeLabel } from "../lib/i18n.jsx";
import { useDialog } from "../lib/dialog.jsx";

export default function Einstellungen() {
  const nav = useNavigate();
  const { user, setUser, logout } = useAuth();
  const { t, lang, setLang } = useLang();
  const [params] = useSearchParams();
  // Stripe schickt nach dem Kauf auf ?zahlung=ok zurueck – dann gehoert der Abo-Reiter auf.
  const [tab, setTab] = useState(params.get("tab") || (params.get("zahlung") ? "abo" : "profil"));
  const [name, setName] = useState(user?.display_name || "");
  const [grade, setGrade] = useState(user?.grade_level || "oberstufe");
  const [language, setLanguage] = useState(user?.language === "en" ? "en" : "de");
  const [share, setShare] = useState(user?.share_with_parents ?? true);
  const [saved, setSaved] = useState(false);
  const [speicherFehler, setSpeicherFehler] = useState("");
  const [busy, setBusy] = useState(false);

  const TABS = [
    { key: "profil", icon: "👤", label: t("Profil", "Profile") },
    { key: "passwort", icon: "🔑", label: t("Passwort", "Password") },
    { key: "sprache", icon: "🌐", label: t("Sprache", "Language") },
    { key: "privat", icon: "🔒", label: t("Privatsphäre", "Privacy") },
    { key: "abo", icon: "💳", label: t("Abo & Tokens", "Plan & tokens") },
  ];

  async function save(extra = {}) {
    setBusy(true);
    setSaved(false);
    setSpeicherFehler("");
    try {
      const updated = await api.patch("/api/auth/me", {
        display_name: name,
        grade_level: grade,
        language,
        share_with_parents: share,
        ...extra,
      });
      setUser(updated);
      // Sprache sofort in der ganzen App umschalten
      if (updated?.language === "de" || updated?.language === "en") setLang(updated.language);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      return true;
    } catch (e) {
      // Ein eigenes Fenster waere fuer «Speichern ging nicht» zu viel: die
      // Meldung gehoert dorthin, wo der Knopf steht.
      setSpeicherFehler(e.message || t("Speichern hat nicht geklappt.", "Saving didn't work."));
      return false;
    } finally {
      setBusy(false);
    }
  }

  const initial = (user?.display_name || "?").charAt(0).toUpperCase();

  return (
    <div style={{ height: "100%", display: "flex" }} className="settings">
      <div style={{ flex: "0 0 220px", background: "#fbfbfd", borderRight: "1px solid #eef0f3", padding: "18px 0" }} className="settings-nav">
        <div style={{ padding: "0 18px 14px", fontSize: 18, fontWeight: 800, letterSpacing: "-.02em" }}>{t("Einstellungen", "Settings")}</div>
        {TABS.map((tb) => (
          <div
            key={tb.key}
            onClick={() => setTab(tb.key)}
            style={{ display: "flex", alignItems: "center", gap: 10, margin: "2px 8px", padding: "9px 12px", borderRadius: 10, fontSize: 13, cursor: "pointer", background: tab === tb.key ? "#eef0fe" : "transparent", color: tab === tb.key ? "#4f46e5" : "#1a1c22", fontWeight: tab === tb.key ? 600 : 400 }}
          >
            {tb.icon} {tb.label}
          </div>
        ))}
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "30px 36px", background: "#fff" }}>
        {tab === "profil" && (
          <>
            <div style={{ fontSize: 20, fontWeight: 800, letterSpacing: "-.02em", marginBottom: 24 }}>{t("Profil", "Profile")}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 28 }}>
              <span style={{ width: 64, height: 64, borderRadius: "50%", background: "#eef0fe", color: "#4f46e5", fontWeight: 800, fontSize: 24, display: "grid", placeItems: "center" }}>{initial}</span>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#4f46e5", marginBottom: 4 }}>{t("Anzeigename statt Klarname", "Display name instead of real name")}</div>
                <div style={{ fontSize: 12, color: "#9aa0ab" }}>{t("Wir speichern bewusst keinen echten Namen.", "We deliberately don't store your real name.")}</div>
              </div>
            </div>
            <div style={{ maxWidth: 520 }}>
              <Field label={t("Anzeigename", "Display name")}>
                <input value={name} onChange={(e) => setName(e.target.value)} className="input-clean" style={{ width: "100%", fontSize: 14 }} />
              </Field>
              <Field label={t("E-Mail", "Email")}>
                <div style={{ display: "flex", justifyContent: "space-between", color: "#6b7280" }}>
                  <span>{user?.email}</span>
                  {user?.email_verified ? (
                    <span style={{ fontSize: 11, color: "#1a7f3c", fontWeight: 700 }}>{t("✓ bestätigt", "✓ confirmed")}</span>
                  ) : (
                    <span style={{ fontSize: 11, color: "#a05c12", fontWeight: 700 }}>{t("noch nicht bestätigt", "not yet confirmed")}</span>
                  )}
                </div>
              </Field>
              <Field label={t("Stufe", "Level")}>
                <select value={grade} onChange={(e) => setGrade(e.target.value)} style={selectStyle}>
                  {!GRADE_KEYS.includes(grade) && grade && <option value={grade}>{grade}</option>}
                  {GRADE_KEYS.map((g) => <option key={g} value={g}>{gradeLabel(g, lang)}</option>)}
                </select>
              </Field>
              <SaveRow busy={busy} saved={saved} fehler={speicherFehler} onSave={() => save()} onCancel={() => nav("/app/lernen")} t={t} />

              {/* Abmelden gehoert dorthin, wo man es sucht – nicht nur in die Seitenleiste. */}
              <div style={{ borderTop: "1px solid #eef0f3", marginTop: 28, paddingTop: 20 }}>
                <button
                  onClick={() => { logout(); nav("/login", { replace: true }); }}
                  style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "10px 18px", borderRadius: 11, border: "1px solid #e7e8ee", background: "#fff", color: "#1a1c22", fontSize: 13.5, fontWeight: 600, cursor: "pointer" }}
                >
                  <span aria-hidden="true">⏻</span> {t("Abmelden", "Sign out")}
                </button>
                <div style={{ fontSize: 12, color: "#9aa0ab", marginTop: 8 }}>
                  {t("Du wirst auf diesem Gerät abgemeldet. Deine Aufgaben und dein Fortschritt bleiben erhalten.",
                     "You'll be signed out on this device. Your tasks and progress are kept.")}
                </div>
              </div>
            </div>
          </>
        )}

        {tab === "passwort" && <PasswordTab />}

        {tab === "abo" && <AboTab onBuy={() => nav("/app/preise")} />}

        {tab === "sprache" && (
          <>
            <div style={{ fontSize: 20, fontWeight: 800, marginBottom: 24 }}>{t("Sprache", "Language")}</div>
            <div style={{ maxWidth: 520 }}>
              <Field label={t("Sprache der App", "App language")}>
                <select value={language} onChange={(e) => setLanguage(e.target.value)} style={selectStyle}>
                  <option value="de">Deutsch</option>
                  <option value="en">English</option>
                </select>
              </Field>
              <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 20 }}>
                {t("Auch der Tutor antwortet in dieser Sprache. Die App erkennt die Sprache beim ersten Besuch automatisch – hier stellst du sie fest ein.",
                   "The tutor also replies in this language. The app auto-detects your language on first visit – here you set it permanently.")}
              </div>
              <SaveRow busy={busy} saved={saved} fehler={speicherFehler} onSave={() => save()} onCancel={() => nav("/app/lernen")} t={t} />
            </div>
          </>
        )}

        {tab === "privat" && (
          <>
            <div style={{ fontSize: 20, fontWeight: 800, marginBottom: 24 }}>{t("Privatsphäre", "Privacy")}</div>
            <div style={{ maxWidth: 620 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderTop: "1px solid #eef0f3", padding: "16px 0" }}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>{t("Fortschritt für Eltern freigeben", "Share progress with parents")}</div>
                  <div style={{ fontSize: 12, color: "#9aa0ab" }}>{t("Nur grober Fortschritt, keine einzelnen Nachrichten.", "Only overall progress, never individual messages.")}</div>
                </div>
                <Toggle on={share} onClick={async () => {
                  const next = !share;
                  setShare(next);
                  const ok = await save({ share_with_parents: next });
                  if (!ok) setShare(!next); // PATCH fehlgeschlagen -> Schalter zuruecksetzen
                }} />
              </div>
              <div style={{ background: "#f6f7fb", border: "1px solid #eef0f3", borderRadius: 14, padding: 16, fontSize: 13, color: "#6b7280", lineHeight: 1.55, marginTop: 12 }}>
                {t("🔒 Deine Chats bleiben privat. Eltern sehen nur Aggregate wie Selbständigkeit, gelöste Aufgaben und Themen-Trends – technisch gibt es aus der Eltern-Ansicht keinen Zugriff auf deine Nachrichten.",
                   "🔒 Your chats stay private. Parents only see aggregates like independence, solved tasks and topic trends – technically the parent view has no access to your messages.")}
              </div>
              <DeleteAccount />
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export function chf(rappen) {
  const s = (rappen / 100).toFixed(2);
  return s.endsWith(".00") ? s.slice(0, -3) + ".–" : s;
}

function AboTab({ onBuy }) {
  const { t, lang } = useLang();
  const dialog = useDialog();
  const [params] = useSearchParams();
  const [quota, setQuota] = useState(null);
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => api.get("/api/quota").then(setQuota).catch(() => setQuota(null));
  useEffect(() => { load(); }, []);
  // Rueckkehr von der Stripe-Bezahlseite: der Webhook braucht evtl. 1–2 Sekunden.
  useEffect(() => {
    const z = params.get("zahlung");
    if (z === "ok") {
      setNote({ type: "ok", text: t("Zahlung erhalten – dein Abo ist in wenigen Sekunden aktiv. 🎉", "Payment received – your subscription will be active in a few seconds. 🎉") });
      const t1 = setTimeout(load, 2500);
      const t2 = setTimeout(load, 8000);
      return () => { clearTimeout(t1); clearTimeout(t2); };
    }
    if (z === "abbruch") setNote({ type: "error", text: t("Zahlung abgebrochen – es wurde nichts belastet.", "Payment cancelled – nothing was charged.") });
  }, [params]);

  async function umstellen(kuendigen) {
    const datum = quota.abo_bis ? new Date(quota.abo_bis).toLocaleDateString(lang === "en" ? "en-GB" : "de-CH") : "";
    if (kuendigen) {
      const ja = await dialog.bestaetigen({
        titel: t(`${quota.plus_name} kündigen?`, `Cancel ${quota.plus_name}?`),
        text: t(`Dein Abo läuft bis ${datum} weiter und verlängert sich danach nicht mehr. Bis dahin kannst du die Kündigung jederzeit zurücknehmen.`,
                `Your subscription stays active until ${datum} and will not renew afterwards. Until then you can undo the cancellation at any time.`),
        bestaetigen: t("Kündigen", "Cancel subscription"),
        gefahr: true,
      });
      if (!ja) return;
    }
    setBusy(true);
    setNote(null);
    try {
      setQuota(await api.post(kuendigen ? "/api/pay/abo/kuendigen" : "/api/pay/abo/weiter"));
      setNote({ type: "ok", text: kuendigen
        ? t(`Gekündigt. ${quota.plus_name} bleibt bis ${datum} aktiv.`, `Cancelled. ${quota.plus_name} stays active until ${datum}.`)
        : t("Kündigung zurückgenommen – dein Abo läuft weiter.", "Cancellation undone – your subscription continues.") });
    } catch (e) {
      setNote({ type: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  }

  if (!quota) return <div style={{ fontSize: 14, color: "#9aa0ab" }}>{t("lädt …", "loading …")}</div>;

  const hinweis = note && (
    <div style={{ maxWidth: 620, marginBottom: 16, fontSize: 13, borderRadius: 12, padding: "11px 16px", background: note.type === "error" ? "#fdecec" : "#e8f6ec", color: note.type === "error" ? "#c0392b" : "#1a7f3c", border: `1px solid ${note.type === "error" ? "#f5cccc" : "#cde7d6"}` }}>
      {note.text}
    </div>
  );

  if (quota.abo_enabled && !quota.unlimited) {
    const datum = quota.abo_bis ? new Date(quota.abo_bis).toLocaleDateString(lang === "en" ? "en-GB" : "de-CH") : "";
    const karte = { background: "#fff", border: "1px solid #e7e8ee", borderRadius: 14, padding: 20, maxWidth: 620, marginBottom: 16 };
    return (
      <>
        <div style={{ fontSize: 20, fontWeight: 800, marginBottom: 24 }}>{quota.plus_name}</div>
        {hinweis}
        {quota.stufe === "plus" ? (
          <div style={karte}>
            <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 6 }}>{t("Dein Abo", "Your subscription")}</div>
            <div style={{ fontSize: 20, fontWeight: 800, color: "#1a7f3c" }}>✨ {quota.plus_name} {t("aktiv", "active")}</div>
            <div style={{ fontSize: 13, color: "#6b7280", marginTop: 8, lineHeight: 1.55 }}>
              {quota.abo_gekuendigt
                ? t(`Gekündigt – aktiv bis ${datum}, danach keine Verlängerung mehr.`, `Cancelled – active until ${datum}, no renewal afterwards.`)
                : t(`${quota.abo_intervall === "jahr" ? "Jahresabo" : "Monatsabo"} · verlängert sich am ${datum} · jederzeit kündbar.`,
                    `${quota.abo_intervall === "jahr" ? "Yearly" : "Monthly"} plan · renews on ${datum} · cancel anytime.`)}
            </div>
            {quota.percent_used >= 80 && (
              <div style={{ fontSize: 12.5, color: "#a05c12", marginTop: 10 }}>
                {t("Du hast diesen Monat sehr viel geübt – ab dem 1. geht es unbegrenzt weiter.", "You practised a lot this month – from the 1st it continues without limit.")}
              </div>
            )}
            <button onClick={() => umstellen(!quota.abo_gekuendigt)} disabled={busy}
              style={{ marginTop: 16, borderRadius: 11, padding: "10px 16px", fontSize: 13, fontWeight: 600, cursor: "pointer", border: "1px solid #e7e8ee", background: "#fff", color: quota.abo_gekuendigt ? "#4f46e5" : "#6b7280", opacity: busy ? 0.6 : 1 }}>
              {busy ? t("Moment …", "One sec …") : quota.abo_gekuendigt ? t("Kündigung zurücknehmen", "Undo cancellation") : t("Abo kündigen", "Cancel subscription")}
            </button>
          </div>
        ) : (
          <div style={karte}>
            <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 6 }}>{t("Aktuell", "Currently")}</div>
            {quota.stufe === "trial" ? (
              <>
                <div style={{ fontSize: 20, fontWeight: 800 }}>🎁 {t(`${quota.trial_used} von ${quota.trial_tasks} Gratis-Aufgaben genutzt`, `${quota.trial_used} of ${quota.trial_tasks} free tasks used`)}</div>
                <div style={{ height: 5, borderRadius: 999, background: "#eef0f3", overflow: "hidden", marginTop: 10 }}>
                  <div style={{ width: `${quota.percent_used}%`, height: "100%", background: quota.percent_used >= 90 ? "#d9573a" : "#6366f1" }} />
                </div>
              </>
            ) : quota.stufe === "guthaben" ? (
              <div style={{ fontSize: 20, fontWeight: 800 }}>⚡ {t(`Guthaben: ${quota.token_balance} Tokens`, `Balance: ${quota.token_balance} tokens`)}
                <div style={{ fontSize: 13, color: "#6b7280", fontWeight: 400, marginTop: 6 }}>{t("Aus einem früheren Kauf – wird pro Antwort abgebucht, bis es leer ist.", "From an earlier purchase – deducted per answer until it is used up.")}</div>
              </div>
            ) : (
              <div style={{ fontSize: 20, fontWeight: 800 }}>{t("Deine Gratis-Aufgaben sind aufgebraucht", "Your free tasks are used up")}</div>
            )}
          </div>
        )}
        {quota.stufe !== "plus" && (
          <div style={{ ...karte, background: "#1a1c22", color: "#fff", border: "none" }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#c9ccf6", marginBottom: 6 }}>{quota.plus_name}</div>
            <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em" }}>CHF {chf(quota.preise.monat)} <span style={{ fontSize: 13, color: "#9aa0ab", fontWeight: 500 }}>{t("im Monat", "per month")}</span></div>
            <div style={{ fontSize: 12.5, color: "#9aa0ab", marginBottom: 12 }}>{t(`oder CHF ${chf(quota.preise.jahr)} im Jahr · pro Kind · jederzeit kündbar`, `or CHF ${chf(quota.preise.jahr)} per year · per child · cancel anytime`)}</div>
            <div style={{ fontSize: 13, lineHeight: 1.6, marginBottom: 14 }}>{t("So viel üben, wie du willst – Foto, Stift, Aufgabensammlung, Probeprüfungen, Elternansicht.", "Practise as much as you like – photo, pen, task collection, mock exams, parent view.")}</div>
            <button onClick={onBuy} className="btn-primary" style={{ padding: "11px 20px", borderRadius: 11, fontSize: 14, border: "none" }}>
              {t(`${quota.plus_name} aktivieren →`, `Activate ${quota.plus_name} →`)}
            </button>
          </div>
        )}
      </>
    );
  }

  if (quota.unlimited) {
    return (
      <>
        <div style={{ fontSize: 20, fontWeight: 800, marginBottom: 24 }}>{t("Abo & Tokens", "Plan & tokens")}</div>
        <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 14, padding: 20, maxWidth: 620 }}>
          <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 6 }}>{t("Plan", "Plan")}</div>
          <div style={{ fontSize: 20, fontWeight: 800 }}>{t("∞ Unbegrenzt", "∞ Unlimited")}</div>
          <div style={{ fontSize: 13, color: "#6b7280", marginTop: 8, lineHeight: 1.55 }}>
            {t("Dieses Konto ist ein Betreiber-Konto: Aufgaben sind unbegrenzt und kostenlos – es werden weder Gratis-Kontingent noch Tokens abgebucht.",
               "This is an operator account: tasks are unlimited and free – neither the free quota nor tokens are charged.")}
          </div>
        </div>
      </>
    );
  }

  const freeUsed = Math.min(quota.free_used_tokens, quota.monthly_free_tokens);
  const freePct = quota.monthly_free_tokens ? Math.min(100, Math.round((freeUsed / quota.monthly_free_tokens) * 100)) : 0;

  return (
    <>
      <div style={{ fontSize: 20, fontWeight: 800, marginBottom: 24 }}>{t("Abo & Tokens", "Plan & tokens")}</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14, maxWidth: 620, marginBottom: 20 }} className="eltern-tiles">
        <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 14, padding: 16 }}>
          <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 6 }}>{t("Plan", "Plan")}</div>
          <div style={{ fontSize: 20, fontWeight: 800 }}>{quota.plan === "free" ? t("Gratis", "Free") : "Token"}</div>
        </div>
        <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 14, padding: 16 }}>
          <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 6 }}>{t("Gratis-Tokens (Monat)", "Free tokens (month)")}</div>
          <div style={{ fontSize: 20, fontWeight: 800 }}>{freeUsed} <span style={{ fontSize: 13, color: "#9aa0ab" }}>{t("von", "of")} {quota.monthly_free_tokens}</span></div>
          <div style={{ height: 5, borderRadius: 999, background: "#eef0f3", overflow: "hidden", marginTop: 8 }}>
            <div style={{ width: `${freePct}%`, height: "100%", background: freePct >= 90 ? "#d9573a" : "#6366f1" }} />
          </div>
        </div>
        <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 14, padding: 16 }}>
          <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 6 }}>{t("Token-Guthaben", "Token balance")}</div>
          <div style={{ fontSize: 20, fontWeight: 800, color: quota.token_balance > 0 ? "#1a7f3c" : "#1a1c22" }}>{quota.token_balance}</div>
        </div>
      </div>
      <div style={{ fontSize: 13, color: "#6b7280", marginBottom: 18, lineHeight: 1.55 }}>
        {t("1 Token = 1 Rappen KI-Hilfe · eine normale Tutor-Antwort kostet ≈ 1 Token, eine Antwort mit Foto-Auswertung ≈ 3–5 · Tokens laufen nie ab · kein Abo, keine automatische Verlängerung",
           "1 token = 1 Swiss centime of AI help · a normal tutor reply costs ≈ 1 token, a reply with photo analysis ≈ 3–5 · tokens never expire · no subscription, no automatic renewal")}
      </div>
      <button onClick={onBuy} className="btn-primary" style={{ padding: "11px 20px", borderRadius: 11, fontSize: 14, border: "none" }}>
        {t("Tokens kaufen →", "Buy tokens →")}
      </button>
    </>
  );
}

export function PasswordTab() {
  const { login } = useAuth();
  const { t } = useLang();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null); // {type, text}

  async function change() {
    if (next.length < 8) {
      setNote({ type: "error", text: t("Das neue Passwort braucht mindestens 8 Zeichen.", "The new password needs at least 8 characters.") });
      return;
    }
    if (next !== repeat) {
      setNote({ type: "error", text: t("Die beiden neuen Passwörter stimmen nicht überein.", "The two new passwords don't match.") });
      return;
    }
    setBusy(true);
    setNote(null);
    try {
      const res = await api.post("/api/auth/change-password", {
        current_password: current || null,
        new_password: next,
      });
      await login(res.access_token, res.user); // frisches Token übernehmen
      setCurrent(""); setNext(""); setRepeat("");
      setNote({ type: "ok", text: t("✓ Passwort geändert.", "✓ Password changed.") });
    } catch (e) {
      setNote({ type: "error", text: e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div style={{ fontSize: 20, fontWeight: 800, marginBottom: 8 }}>{t("Passwort ändern", "Change password")}</div>
      <div style={{ fontSize: 13, color: "#6b7280", marginBottom: 24, maxWidth: 520 }}>
        {t("Passwort vergessen? Melde dich ab und nutze auf der Anmelde-Seite «Passwort vergessen» – dann kommst du per E-Mail-Link zurück und kannst hier ohne altes Passwort ein neues setzen.",
           "Forgot your password? Sign out and use “Forgot password” on the sign-in page – you'll come back via email link and can set a new one here without the old password.")}
      </div>
      <div style={{ maxWidth: 520 }}>
        <Field label={t("Aktuelles Passwort", "Current password")}>
          <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" className="input-clean" style={{ width: "100%", fontSize: 14 }} />
        </Field>
        <Field label={t("Neues Passwort (mind. 8 Zeichen)", "New password (min. 8 characters)")}>
          <input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" className="input-clean" style={{ width: "100%", fontSize: 14 }} />
        </Field>
        <Field label={t("Neues Passwort wiederholen", "Repeat new password")}>
          <input type="password" value={repeat} onChange={(e) => setRepeat(e.target.value)} autoComplete="new-password" className="input-clean" style={{ width: "100%", fontSize: 14 }} />
        </Field>
        {note && (
          <div style={{ fontSize: 13, marginBottom: 12, color: note.type === "error" ? "#c0392b" : "#1a7f3c", fontWeight: 600 }}>{note.text}</div>
        )}
        <button onClick={change} disabled={busy} className="btn-primary" style={{ padding: "11px 20px", borderRadius: 11, fontSize: 14, border: "none", opacity: busy ? 0.7 : 1 }}>
          {busy ? t("ändert …", "changing …") : t("Passwort ändern", "Change password")}
        </button>
      </div>
    </>
  );
}

const selectStyle = { width: "100%", border: "none", outline: "none", background: "transparent", fontSize: 14 };

function Field({ label, children }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <label style={{ fontSize: 12, fontWeight: 600, color: "#6b7280", display: "block", marginBottom: 6 }}>{label}</label>
      <div style={{ border: "1px solid #d2d4dd", borderRadius: 11, padding: "11px 13px", fontSize: 14 }}>{children}</div>
    </div>
  );
}

function SaveRow({ busy, saved, fehler, onSave, onCancel, t }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 18, flexWrap: "wrap" }}>
      <button onClick={onSave} disabled={busy} className="btn-primary" style={{ padding: "11px 20px", borderRadius: 11, fontSize: 14, border: "none" }}>
        {busy ? t("speichert …", "saving …") : t("Speichern", "Save")}
      </button>
      <button onClick={onCancel} className="btn-ghost" style={{ padding: "11px 20px", fontSize: 14 }}>{t("Abbrechen", "Cancel")}</button>
      {saved && <span style={{ fontSize: 13, color: "#1a7f3c", fontWeight: 600 }}>{t("✓ gespeichert", "✓ saved")}</span>}
      {fehler && <span style={{ fontSize: 13, color: "#c0392b", fontWeight: 600 }}>{fehler}</span>}
    </div>
  );
}

function Toggle({ on, onClick }) {
  return (
    <div onClick={onClick} style={{ width: 42, height: 24, borderRadius: 999, position: "relative", cursor: "pointer", background: on ? "#6366f1" : "#d2d4dd", transition: "background .15s" }}>
      <span style={{ position: "absolute", top: 2, left: on ? 20 : 2, width: 20, height: 20, borderRadius: "50%", background: "#fff", transition: "left .15s" }} />
    </div>
  );
}

// Roter Bereich: Konto endgültig löschen (Datenschutz-Selbstbedienung)
export function DeleteAccount() {
  const { logout } = useAuth();
  const { t } = useLang();
  const dialog = useDialog();
  const [open, setOpen] = useState(false);
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function doDelete() {
    const ja = await dialog.bestaetigen({
      titel: t("Konto endgültig löschen?", "Delete your account for good?"),
      text: t("Aufgaben, Chats und dein Token-Guthaben sind danach unwiderruflich weg. Das lässt sich nicht rückgängig machen.",
              "Tasks, chats and your token balance will be gone for good. This cannot be undone."),
      bestaetigen: t("Endgültig löschen", "Delete permanently"),
      gefahr: true,
    });
    if (!ja) return;
    setBusy(true);
    setErr("");
    try {
      await api.post("/api/auth/delete-account", { password: pw });
      logout();
      window.location.href = "/";
    } catch (e) {
      setErr(e.message || t("Löschen fehlgeschlagen.", "Deletion failed."));
      setBusy(false);
    }
  }

  return (
    <div style={{ border: "1px solid #f2c9c0", background: "#fdf6f4", borderRadius: 14, padding: 16, marginTop: 24 }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: "#b3492f", marginBottom: 4 }}>{t("Konto löschen", "Delete account")}</div>
      <div style={{ fontSize: 12.5, color: "#6b7280", lineHeight: 1.55, marginBottom: 12 }}>
        {t("Löscht dein Konto mit allen Aufgaben, Chats, Bildern und deinem Token-Guthaben – endgültig. Zahlungsbelege bleiben beim Zahlungsanbieter (gesetzliche Aufbewahrung).",
           "Deletes your account with all tasks, chats, images and your token balance – permanently. Payment records remain with the payment provider (legal retention).")}
      </div>
      {!open ? (
        <button onClick={() => setOpen(true)} style={{ border: "1px solid #e5b0a4", background: "#fff", color: "#b3492f", borderRadius: 10, padding: "9px 14px", fontSize: 13, fontWeight: 700, cursor: "pointer" }}>
          {t("Konto löschen …", "Delete account …")}
        </button>
      ) : (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input
            type="password"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            placeholder={t("Passwort zur Bestätigung", "Password to confirm")}
            style={{ border: "1px solid #e5b0a4", borderRadius: 10, padding: "9px 12px", fontSize: 13, flex: "1 1 200px" }}
          />
          <button onClick={doDelete} disabled={busy} style={{ border: "none", background: "#b3492f", color: "#fff", borderRadius: 10, padding: "10px 14px", fontSize: 13, fontWeight: 700, cursor: "pointer", opacity: busy ? 0.7 : 1 }}>
            {busy ? t("lösche …", "deleting …") : t("Endgültig löschen", "Delete permanently")}
          </button>
          <button onClick={() => { setOpen(false); setPw(""); setErr(""); }} style={{ border: "none", background: "transparent", color: "#6b7280", fontSize: 13, cursor: "pointer" }}>
            {t("Abbrechen", "Cancel")}
          </button>
        </div>
      )}
      {err && <div style={{ fontSize: 12.5, color: "#b3492f", marginTop: 8 }}>{err}</div>}
    </div>
  );
}
