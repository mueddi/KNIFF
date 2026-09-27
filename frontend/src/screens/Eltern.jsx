import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { useLang } from "../lib/i18n.jsx";

// Zwei Dinge, sauber getrennt:
// - ChildDashboard: das echte Eltern-Dashboard (genutzt von ParentDashboard.jsx)
// - Eltern (default): die SCHUELER-Seite «Eltern verbinden» – nur Code +
//   Erklaerung, KEIN Dashboard-Klon in der Kinder-App.

// Backend-Labels -> elternverstaendliche Chips (Keys sind Backend-Werte, nicht anfassen)
function labelChip(raw, t) {
  const map = {
    "Noch üben": { text: t("Braucht Hilfe", "Needs help"), bg: "#fdecec", fg: "#c0392b" },
    "Braucht Hilfe": { text: t("Braucht Hilfe", "Needs help"), bg: "#fdecec", fg: "#c0392b" },
    "Wird besser": { text: t("Wird besser", "Improving"), bg: "#eef0fe", fg: "#4f46e5" },
    Sitzt: { text: t("Sitzt", "Solid"), bg: "#e8f6ec", fg: "#1a7f3c" },
  };
  return map[raw] || { text: raw, bg: "#f1f2f6", fg: "#6b7280" };
}

export function Tile({ label, value, unit, sub, color = "#1a1c22" }) {
  return (
    <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 16, padding: 18 }}>
      <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 8 }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: "-.02em", color }}>
        {value}
        {unit && <span style={{ fontSize: 16 }}>{unit}</span>}
      </div>
      <div style={{ fontSize: 12, color: "#6b7280", marginTop: 4 }}>{sub}</div>
    </div>
  );
}

// Klartext-Zusammenfassung aus den echten Wochendaten – das Wichtigste in
// einem Satz, ohne Prozent-Jargon.
// Klartext-Satz aus den Wochenzahlen. Traegt bewusst «bearbeitet», nicht
// «gelöst»: nur 12 % aller Aufgaben werden ueberhaupt abgehakt, ein Satz auf
// dieser Grundlage haette fast immer «noch keine Aufgabe gelöst» gemeldet –
// obwohl das Kind gearbeitet hat.
function summarySentence(d, t) {
  const name = d.student_display_name;
  const bearbeitet = d.worked_count ?? 0;
  if (!bearbeitet && !d.active_days) {
    return t(`${name} hat diese Woche noch nicht geübt.`, `${name} hasn't practiced yet this week.`);
  }
  let s = t(
    `${name} hat diese Woche an ${d.active_days} ${d.active_days === 1 ? "Tag" : "Tagen"} an ${bearbeitet} ${bearbeitet === 1 ? "Aufgabe" : "Aufgaben"} gearbeitet`,
    `${name} worked on ${bearbeitet} ${bearbeitet === 1 ? "task" : "tasks"} on ${d.active_days} ${d.active_days === 1 ? "day" : "days"} this week`
  );
  s += (d.own_steps ?? 0) > 0
    ? t(` und dabei ${d.own_steps} eigene Rechenschritte geschrieben.`,
        ` and wrote ${d.own_steps} own calculation steps.`)
    : ".";
  if (d.solved_count) {
    s += t(` ${d.solved_count} davon ${d.solved_count === 1 ? "wurde" : "wurden"} fertig gelöst.`,
           ` ${d.solved_count} of them ${d.solved_count === 1 ? "was" : "were"} fully solved.`);
  }
  return s;
}

// Hilfe-Tipps – nur wenn sie sich auf ein konkretes Thema oder eine konkrete
// Zahl stuetzen. Frueher gab es hier eine Auffang-Regel, die immer feuerte;
// das Ergebnis war jede Woche derselbe Satz. Lieber KEIN Tipp als ein
// beliebiger: ein Ratschlag, den man schon dreimal gelesen hat, entwertet
// auch die uebrige Ansicht.
function helpTips(d, t) {
  const tips = [];
  const worst = (d.top_struggles || [])[0];
  if (worst && worst.heavy >= 2) {
    tips.push(t(
      `Bei «${worst.topic}» war ${worst.heavy}× viel Hilfe nötig. Lassen Sie sich eine dieser Aufgaben erklären – wer erklärt, merkt selbst am schnellsten, wo es hakt.`,
      `"${worst.topic}" needed a lot of help ${worst.heavy} times. Have your child explain one of these tasks – explaining reveals the gap fastest.`
    ));
  }
  if ((d.ohne_thema ?? 0) >= 3) {
    tips.push(t(
      `${d.ohne_thema} Aufgaben sind keinem Thema zugeordnet. Wenn Ihr Kind sie einsortiert, zeigt diese Seite, woran es wirklich hakt.`,
      `${d.ohne_thema} tasks have no topic. Once your child sorts them, this page can show where the real difficulty lies.`
    ));
  }
  if ((d.worked_count ?? 0) >= 3 && (d.active_days ?? 0) === 1) {
    tips.push(t(
      `Alles an einem Tag: ${d.worked_count} Aufgaben in einer Sitzung. Dreimal 15 Minuten über die Woche verteilt bleibt deutlich besser hängen.`,
      `All on one day: ${d.worked_count} tasks in a single session. Three 15-minute sessions across the week stick far better.`
    ));
  }
  return tips.slice(0, 2);
}

// Trend. `null` heisst «zu wenig Daten» – und genau das wird dann auch
// hingeschrieben. Frueher stand hier bei leerer Vorwoche «etwa gleich viel wie
// letzte Woche», obwohl gar nicht geuebt worden war.
function trendText(delta, t) {
  if (delta == null) {
    return { value: t("—", "—"), sub: t("zu wenig Daten für einen Vergleich", "not enough data to compare"), color: "#9aa0ab" };
  }
  if (delta > 15) return { value: t("mehr", "more"), sub: t("geübt als letzte Woche", "practice than last week"), color: "#1a7f3c" };
  if (delta < -15) return { value: t("weniger", "less"), sub: t("geübt als letzte Woche", "practice than last week"), color: "#c0392b" };
  return { value: t("etwa gleich", "about the same"), sub: t("viel wie letzte Woche", "amount as last week"), color: "#4f46e5" };
}

// Woran diese Woche gearbeitet wurde – konkret statt abstrakt. Ein Elternteil
// kann mit «Bruchrechnen, Mittwoch, noch offen» etwas anfangen, mit
// «Selbständigkeit 67 %» nicht.
function WoranGearbeitet({ eintraege, lang, t }) {
  if (!eintraege || eintraege.length === 0) return null;
  return (
    <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 16, padding: 20, marginBottom: 16 }}>
      <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>{t("Woran gearbeitet wurde", "What was worked on")}</div>
      <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 12 }}>
        {t("diese Woche · fragen Sie danach, nicht nach den Zahlen", "this week · ask about these, not about the numbers")}
      </div>
      <div>
        {eintraege.map((e, i) => {
          const tag = e.wann
            ? new Date(e.wann).toLocaleDateString(lang === "en" ? "en-GB" : "de-CH", { weekday: "short" })
            : null;
          return (
            <div key={i} style={{ display: "flex", alignItems: "baseline", gap: 12, padding: "9px 0", borderTop: i ? "1px solid #f4f5f8" : "none" }}>
              <span style={{ flex: "0 0 auto", fontSize: 11.5, color: "#9aa0ab", width: 30 }}>{tag}</span>
              <span style={{ flex: 1, minWidth: 0, fontSize: 13.5, overflowWrap: "anywhere" }}>
                {e.aufgabe}
                {e.thema && <span style={{ color: "#9aa0ab" }}> · {e.thema}</span>}
              </span>
              <span style={{ flex: "0 0 auto", fontSize: 11, fontWeight: 700, borderRadius: 999, padding: "3px 10px",
                             background: e.geloest ? "#e8f6ec" : e.viel_hilfe ? "#fdecec" : "#f1f2f6",
                             color: e.geloest ? "#1a7f3c" : e.viel_hilfe ? "#c0392b" : "#6b7280" }}>
                {e.geloest ? t("fertig", "done") : e.viel_hilfe ? t("viel Hilfe", "lots of help") : t("dran", "in progress")}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function ChildDashboard({ data }) {
  const { t, lang } = useLang();
  const TAGE = [t("Mo", "Mon"), t("Di", "Tue"), t("Mi", "Wed"), t("Do", "Thu"), t("Fr", "Fri"), t("Sa", "Sat"), t("So", "Sun")];
  const struggles = data.top_struggles || [];
  const daily = data.daily_activity || [0, 0, 0, 0, 0, 0, 0];
  const maxV = Math.max(...daily, 1);
  // Bewusst nicht `|| 0`: null heisst «zu wenig Daten» und muss null bleiben.
  const trend = trendText(data.dranbleiben_delta ?? null, t);
  const tipps = helpTips(data, t);
  // «Woche vom …»: Montag der angezeigten Woche, lokal formatiert
  const weekLabel = data.week_start
    ? new Date(data.week_start).toLocaleDateString(lang === "en" ? "en-GB" : "de-CH", { day: "numeric", month: "long" })
    : null;
  return (
    <>
      {/* Das Wichtigste zuerst: ein Satz in Klartext, aus echten Daten */}
      <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 16, padding: "16px 20px", fontSize: 15, lineHeight: 1.6, marginBottom: 20 }}>
        {summarySentence(data, t)}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16, marginBottom: 20 }} className="eltern-tiles">
        {/* Hauptzahl ist «bearbeitet»: sie entsteht immer, wenn gearbeitet
            wurde. «Gelöst» steht daneben, traegt die Ansicht aber nicht mehr
            allein – es wird nur in 12 % der Faelle ueberhaupt vergeben. */}
        <Tile label={t("Bearbeitete Aufgaben", "Tasks worked on")} value={data.worked_count ?? 0}
              sub={data.solved_count
                ? t(`davon ${data.solved_count} fertig gelöst`, `${data.solved_count} of them fully solved`)
                : t("diese Woche", "this week")} />
        <Tile label={t("Eigene Rechenschritte", "Own steps written")} value={data.own_steps ?? 0}
              sub={t("selbst geschrieben, nicht nur gelesen", "written by your child, not just read")} color="#1a7f3c" />
        <Tile label={t("Übungstage", "Practice days")} value={data.active_days} unit={t(" von 7", " of 7")} sub={t("diese Woche", "this week")} />
        <Tile label={t("Trend", "Trend")} value={trend.value} sub={trend.sub} color={trend.color} />
      </div>

      <WoranGearbeitet eintraege={data.worked_on} lang={lang} t={t} />
      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 16 }} className="eltern-charts">
        <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 16, padding: 20 }}>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>{t("Themen mit viel Hilfebedarf", "Topics needing a lot of help")}</div>
          <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 14 }}>{t("hier lohnt sich gemeinsames Üben", "practicing together pays off here")}</div>
          {struggles.length === 0 && (
            <div style={{ fontSize: 13, color: "#9aa0ab", lineHeight: 1.6 }}>
              {(data.ohne_thema ?? 0) > 0
                ? t(`Kein Thema auffällig. ${data.ohne_thema} bearbeitete ${data.ohne_thema === 1 ? "Aufgabe ist" : "Aufgaben sind"} keinem Thema zugeordnet – erst dann kann hier etwas stehen.`,
                    `No topic stands out. ${data.ohne_thema} ${data.ohne_thema === 1 ? "task has" : "tasks have"} no topic – only then can something appear here.`)
                : t("Kein Thema auffällig – läuft rund.", "No topic stands out – everything is going smoothly.")}
            </div>
          )}
          {struggles.map((s) => {
            const chip = labelChip(s.label, t);
            // Sammel-Eintrag fuer Aufgaben ohne Themen-Zuordnung uebersetzen
            const topicLabel = s.topic === "Ohne Thema" ? t("Ohne Thema", "No topic") : s.topic;
            return (
              <div key={s.topic} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "9px 0", borderTop: "1px solid #f4f5f8" }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 600 }}>{topicLabel}</div>
                  {s.heavy != null && s.total ? (
                    <div style={{ fontSize: 11.5, color: "#9aa0ab" }}>
                      {s.heavy} {t("von", "of")} {s.total} {s.total === 1 ? t("Aufgabe brauchte", "task needed") : t("Aufgaben brauchten", "tasks needed")} {t("viel Hilfe", "a lot of help")}
                    </div>
                  ) : null}
                </div>
                <span style={{ flex: "0 0 auto", fontSize: 11, fontWeight: 700, borderRadius: 999, padding: "4px 11px", background: chip.bg, color: chip.fg }}>{chip.text}</span>
              </div>
            );
          })}
        </div>
        <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 16, padding: 20 }}>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>{t("An welchen Tagen geübt wurde", "Which days were practice days")}</div>
          <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 12 }}>
            {weekLabel ? `${t("Woche vom", "Week of")} ${weekLabel} · ` : ""}{t("Zahl = gestartete Aufgaben", "number = tasks started")}
          </div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height: 104 }}>
            {daily.map((v, i) => {
              const h = Math.max(Math.round((v / maxV) * 68), v > 0 ? 10 : 2);
              return (
                <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end", gap: 4 }}>
                  {v > 0 && <span style={{ fontSize: 10.5, fontWeight: 700, color: v >= maxV ? "#4f46e5" : "#9aa0ab" }}>{v}</span>}
                  <div style={{ width: "100%", height: h, background: v > 0 ? (v >= maxV ? "#6366f1" : "#e7e8fb") : "#eef0f3", borderRadius: 6 }} />
                  <span style={{ fontSize: 10, color: "#9aa0ab" }}>{TAGE[i]}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 16, marginTop: 16 }} className="eltern-charts">
        {/* Tipps nur, wenn eine Regel wirklich greift – siehe helpTips(). */}
        {tipps.length > 0 ? (
          <div style={{ background: "#f8f8ff", border: "1px solid #e0e2fb", borderRadius: 16, padding: 20 }}>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 12 }}>{t("💡 So können Sie helfen", "💡 How you can help")}</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {tipps.map((tip, i) => (
                <div key={i} style={{ display: "flex", gap: 9, fontSize: 13.5, lineHeight: 1.55, color: "#3a3d46" }}>
                  <span style={{ color: "#4f46e5", fontWeight: 800 }}>→</span>
                  <span>{tip}</span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div style={{ background: "#fff", border: "1px dashed #e7e8ee", borderRadius: 16, padding: 20, display: "grid", placeItems: "center", fontSize: 12.5, color: "#9aa0ab", textAlign: "center", lineHeight: 1.6 }}>
            {t("Diese Woche fällt nichts auf, das einen Rat rechtfertigt. Fragen Sie einfach nach einer Aufgabe aus der Liste.",
               "Nothing this week warrants advice. Just ask about one of the tasks in the list.")}
          </div>
        )}
        {/* Verlauf ueber die letzten Wochen (nur mit genug Daten) */}
        {(data.history || []).length >= 2 ? (
          <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 16, padding: 20 }}>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>{t("Verlauf", "Trend over time")}</div>
            {/* Balken = bearbeitete Aufgaben. Frueher stand hier «gelöst» –
                bei 0 gelösten Aufgaben in mehreren Wochen war das eine Reihe
                leerer Balken, obwohl durchgehend geuebt wurde. */}
            <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 12 }}>{t("Bearbeitete Aufgaben pro Woche", "Tasks worked on per week")}</div>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 10, height: 104 }}>
              {[...data.history].reverse().map((w, i, arr) => {
                const wert = w.worked_count ?? 0;
                const maxWert = Math.max(...arr.map((x) => x.worked_count ?? 0), 1);
                const h = Math.max(Math.round((wert / maxWert) * 62), wert > 0 ? 10 : 2);
                const isCurrent = i === arr.length - 1;
                const label = new Date(w.week_start).toLocaleDateString(lang === "en" ? "en-GB" : "de-CH", { day: "numeric", month: "numeric" });
                return (
                  <div key={w.week_start} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end", gap: 4 }}>
                    <span style={{ fontSize: 10.5, fontWeight: 700, color: isCurrent ? "#4f46e5" : "#9aa0ab" }}>{wert > 0 ? wert : "–"}</span>
                    <div title={`${wert} ${t("bearbeitet", "worked on")} · ${w.solved_count} ${t("gelöst", "solved")}`} style={{ width: "100%", height: h, background: wert > 0 ? (isCurrent ? "#6366f1" : "#e7e8fb") : "#eef0f3", borderRadius: 6 }} />
                    <span style={{ fontSize: 10, color: "#9aa0ab" }}>{label}</span>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div style={{ background: "#fff", border: "1px dashed #e7e8ee", borderRadius: 16, padding: 20, display: "grid", placeItems: "center", fontSize: 12.5, color: "#9aa0ab", textAlign: "center" }}>
            {t("Der Wochen-Verlauf erscheint hier, sobald zwei Übungswochen zusammengekommen sind.", "The weekly trend will appear here once there are two weeks of practice.")}
          </div>
        )}
      </div>
      <div style={{ marginTop: 16, fontSize: 12.5, color: "#9aa0ab" }}>
        {t("🔒 Sie sehen den groben Fortschritt – nie einzelne Nachrichten Ihres Kindes.", "🔒 You see overall progress – never your child's individual messages.")}
      </div>
    </>
  );
}

// SCHUELER-Seite: nur Eltern verbinden – kein Dashboard in der Kinder-App.
export default function Eltern() {
  const { t } = useLang();
  const { user } = useAuth();
  const [invite, setInvite] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api.get("/api/parents/invite").then(setInvite).catch(() => setInvite(null));
  }, []);

  return (
    <div style={{ height: "100%", overflowY: "auto", background: "#fbfbfd", padding: "36px 40px" }}>
      <div style={{ maxWidth: 620, margin: "0 auto" }}>
        <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em", marginBottom: 6 }}>{t("Eltern verbinden", "Connect parents")}</div>
        <div style={{ fontSize: 14, color: "#6b7280", marginBottom: 24, lineHeight: 1.55 }}>
          {t("Deine Eltern erstellen ein eigenes Eltern-Konto und geben dort diesen Code ein.", "Your parents create their own parent account and enter this code there.")}
        </div>

        {invite ? (
          <div style={{ background: "#eef0fe", border: "1px solid #dfe1fb", borderRadius: 18, padding: "22px 24px", textAlign: "center", marginBottom: 20 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: "#4f46e5", marginBottom: 10 }}>{t("DEIN EINLADUNGSCODE", "YOUR INVITE CODE")}</div>
            <div style={{ fontFamily: "ui-monospace, monospace", fontSize: 30, fontWeight: 800, letterSpacing: ".22em", color: "#1a1c22", background: "#fff", borderRadius: 12, padding: "12px 18px", border: "1px solid #dfe1fb", display: "inline-block", marginBottom: 14 }}>
              {invite.invite_code}
            </div>
            <div>
              <button
                onClick={async () => {
                  // Kopieren kann scheitern (fehlende Berechtigung, alter Browser).
                  // Vorher stand trotzdem «kopiert ✓» – und das Kind schickte nichts.
                  try {
                    await navigator.clipboard.writeText(invite.invite_code);
                    setCopied(true);
                  } catch {
                    setCopied("fehler");
                  }
                  setTimeout(() => setCopied(false), 2500);
                }}
                className="btn-primary"
                style={{ padding: "10px 20px", borderRadius: 10, fontSize: 13, border: "none" }}
              >
                {copied === "fehler" ? t("Bitte von Hand abschreiben", "Please copy it by hand") : copied ? t("kopiert ✓", "copied ✓") : t("Code kopieren", "Copy code")}
              </button>
            </div>
          </div>
        ) : (
          <div style={{ color: "#9aa0ab", fontSize: 14, marginBottom: 20 }}>{t("lädt …", "loading …")}</div>
        )}

        <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 16, padding: "18px 22px", marginBottom: 16 }}>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 12 }}>{t("Das sehen deine Eltern", "What your parents can see")}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 9, fontSize: 13.5, color: "#3a3d46" }}>
            <div><span style={{ color: "#1a7f3c", fontWeight: 700 }}>✓</span> {t("Wie viele Aufgaben du diese Woche gelöst hast", "How many tasks you solved this week")}</div>
            <div><span style={{ color: "#1a7f3c", fontWeight: 700 }}>✓</span> {t("Wie selbständig du arbeitest", "How independently you work")}</div>
            <div><span style={{ color: "#1a7f3c", fontWeight: 700 }}>✓</span> {t("An welchen Tagen du geübt hast", "Which days you practiced on")}</div>
            <div><span style={{ color: "#c0392b", fontWeight: 700 }}>✗</span> <b>{t("Nie", "Never")}</b> {t("deine Nachrichten mit dem Tutor – die bleiben privat", "your messages with the tutor – those stay private")}</div>
          </div>
        </div>

        <div style={{ fontSize: 12.5, color: "#9aa0ab", lineHeight: 1.55 }}>
          {t("Du kannst die Freigabe jederzeit ausschalten:", "You can turn off sharing at any time:")}{" "}
          <Link to="/app/einstellungen" style={{ color: "#4f46e5", fontWeight: 600 }}>{t("Einstellungen → Privatsphäre", "Settings → Privacy")}</Link>
        </div>

        {user?.is_admin && (
          <div style={{ background: "#fdf3e6", border: "1px solid #f2ddb8", borderRadius: 14, padding: "14px 18px", marginTop: 20, fontSize: 13 }}>
            <span style={{ color: "#a05c12", fontWeight: 700 }}>{t("Admin:", "Admin:")}</span>{" "}
            <Link to="/app/elternansicht" style={{ color: "#4f46e5", fontWeight: 700 }}>
              {t("👁 Elternansicht als Vorschau öffnen →", "👁 Open the parent view preview →")}
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
