import { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { Tile } from "./Eltern.jsx";
import { useLang } from "../lib/i18n.jsx";

// Admin-Seite «Rückmeldungen»: alle Feedbacks und Problem-Meldungen auf
// EINER Seite – Zähler, Verlauf pro Woche, Zähler pro Kategorie und
// gleiche Rückmeldungen gebündelt. Zahlen und Gruppen kommen fertig vom
// Server (/api/admin/feedback); hier wird nur gezeichnet.
const FARBE = { feedback: "#4f46e5", problem: "#d9573a" };

export default function FeedbackAdmin() {
  const { t, lang } = useLang();
  const [tage, setTage] = useState(90);
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [art, setArt] = useState("alle");          // "alle" | "feedback" | "problem"
  const [nurOffene, setNurOffene] = useState(false);
  const [auf, setAuf] = useState({});               // aufgeklappte Gruppen
  const [stand, setStand] = useState(0);            // zwingt nach «Erledigt» ein Neuladen

  useEffect(() => {
    let alive = true;
    api
      .get(`/api/admin/feedback?tage=${tage}`)
      .then((d) => alive && (setData(d), setErr("")))
      .catch((e) => alive && setErr(e.message || t("Konnte die Rückmeldungen nicht laden.", "Could not load feedback.")));
    return () => {
      alive = false;
    };
  }, [tage, stand]); // eslint-disable-line react-hooks/exhaustive-deps

  const locale = lang === "en" ? "en-GB" : "de-CH";
  const zeit = (iso) => (iso ? new Date(iso).toLocaleString(locale, { dateStyle: "short", timeStyle: "short" }) : "–");
  const datum = (iso) => new Date(iso + "T00:00:00").toLocaleDateString(locale, { day: "2-digit", month: "2-digit" });

  async function erledigt(e) {
    try {
      await api.patch(`/api/feedback/${e.id}/erledigt?erledigt=${e.resolved_at ? "false" : "true"}`, {});
      setStand((s) => s + 1);
    } catch (ex) {
      setErr(ex.message || t("Konnte den Eintrag nicht ändern.", "Could not change the entry."));
    }
  }

  const gruppen = (data?.gruppen || [])
    .filter((g) => art === "alle" || g.kind === art)
    .filter((g) => !nurOffene || g.offen > 0);
  const wochenMax = Math.max(0, ...(data?.wochen || []).map((w) => w.gesamt));
  const katMax = Math.max(0, ...(data?.nach_kategorie || []).map((k) => k.anzahl));

  return (
    <div style={{ flex: 1, overflowY: "auto", background: "#fbfbfd" }}>
      <div style={{ maxWidth: 860, margin: "0 auto", padding: "28px 20px 60px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 6 }}>
          <h1 style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em", margin: 0 }}>{t("📝 Rückmeldungen", "📝 Feedback inbox")}</h1>
          <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
            {[30, 90, 365].map((n) => (
              <button key={n} onClick={() => setTage(n)} style={pille(tage === n)}>
                {n} {t("Tage", "days")}
              </button>
            ))}
          </div>
        </div>
        <div style={{ fontSize: 13, color: "#6b7280", marginBottom: 20 }}>
          {t("Alles, was Schüler und Eltern geschrieben haben – wann es kam, wovon es handelt, und ob dasselbe mehrfach kam.", "Everything students and parents wrote – when it came, what it is about, and whether the same thing came more than once.")}
        </div>

        {err && (
          <div style={{ background: "#fdf0ee", border: "1px solid #f2c9c0", color: "#b3492f", borderRadius: 12, padding: "12px 16px", fontSize: 13, marginBottom: 16 }}>
            {err}
          </div>
        )}
        {!data && !err && <div style={{ fontSize: 13, color: "#9aa0ab" }}>{t("lädt …", "loading …")}</div>}

        {data && (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 12, marginBottom: 20 }}>
              <Tile label={t("Rückmeldungen gesamt", "Feedback total")} value={data.gesamt} sub={`${data.zeitraum_tage} ${t("Tage", "days")}`} />
              <Tile label={t("Noch offen", "Still open")} value={data.offen} sub={t("nicht als erledigt markiert", "not marked as done")} color={data.offen > 0 ? "#d9573a" : "#1a7f3c"} />
              <Tile label={t("Problem-Meldungen", "Problem reports")} value={data.nach_art.problem} sub={t("Knopf «Problem melden»", "\"Report a problem\" button")} color={FARBE.problem} />
              <Tile label={t("Freies Feedback", "Free feedback")} value={data.nach_art.feedback} sub={t("aus dem Feedback-Fenster", "from the feedback window")} color={FARBE.feedback} />
            </div>

            <Card title={t("Verlauf pro Woche", "Trend per week")}>
              {wochenMax === 0 ? (
                <div style={{ fontSize: 13, color: "#9aa0ab" }}>{t("Im gewählten Zeitraum kam nichts.", "Nothing came in during the selected period.")}</div>
              ) : (
                <>
                  <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 120 }}>
                    {data.wochen.map((w) => (
                      <div key={w.start} title={`${t("Woche ab", "Week from")} ${datum(w.start)}: ${w.gesamt}`} style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "flex-end", height: "100%", minWidth: 6 }}>
                        <div style={{ height: `${(w.problem / wochenMax) * 100}%`, background: FARBE.problem, borderRadius: "4px 4px 0 0" }} />
                        <div style={{ height: `${(w.feedback / wochenMax) * 100}%`, background: FARBE.feedback, borderRadius: w.problem ? 0 : "4px 4px 0 0" }} />
                      </div>
                    ))}
                  </div>
                  <div style={{ display: "flex", gap: 4, marginTop: 6 }}>
                    {data.wochen.map((w, i) => {
                      const schritt = Math.ceil(data.wochen.length / 8);
                      return (
                        <div key={w.start} style={{ flex: 1, minWidth: 6, fontSize: 10.5, color: "#9aa0ab", textAlign: "center", whiteSpace: "nowrap", overflow: "visible" }}>
                          {i % schritt === 0 ? datum(w.start) : ""}
                        </div>
                      );
                    })}
                  </div>
                  <div style={{ display: "flex", gap: 14, marginTop: 10, fontSize: 12, color: "#6b7280" }}>
                    <Legende farbe={FARBE.feedback} text={t("Freies Feedback", "Free feedback")} />
                    <Legende farbe={FARBE.problem} text={t("Problem-Meldungen", "Problem reports")} />
                  </div>
                </>
              )}
            </Card>

            <Card title={t("Nach Kategorie", "By category")}>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {data.nach_kategorie.map((k) => (
                  <div key={k.id} style={{ display: "grid", gridTemplateColumns: "minmax(140px, 220px) 1fr 40px 70px", alignItems: "center", gap: 10, fontSize: 13 }}>
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{k.label}</span>
                    <div style={{ background: "#f0f1f5", borderRadius: 6, height: 10, overflow: "hidden" }}>
                      <div style={{ width: `${katMax ? Math.round((k.anzahl / katMax) * 100) : 0}%`, background: k.id === "feedback" ? FARBE.feedback : FARBE.problem, height: "100%" }} />
                    </div>
                    <span style={{ textAlign: "right", fontWeight: 600 }}>{k.anzahl}</span>
                    <span style={{ textAlign: "right", color: "#9aa0ab", fontSize: 12 }}>{k.offen > 0 ? `${k.offen} ${t("offen", "open")}` : ""}</span>
                  </div>
                ))}
              </div>
            </Card>

            <Card title={t("Gleiche Rückmeldungen", "Same feedback")}>
              <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 12 }}>
                {t("Texte, bei denen mindestens die Hälfte der Wörter übereinstimmt, liegen in einer Gruppe. Klick auf eine Gruppe zeigt die einzelnen Einträge.", "Texts sharing at least half of their words are grouped. Click a group to see the individual entries.")}
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 14 }}>
                {[["alle", t("Alle", "All")], ["feedback", t("Feedback", "Feedback")], ["problem", t("Probleme", "Problems")]].map(([k, label]) => (
                  <button key={k} onClick={() => setArt(k)} style={pille(art === k)}>{label}</button>
                ))}
                <button onClick={() => setNurOffene(!nurOffene)} style={{ ...pille(nurOffene), marginLeft: "auto" }}>
                  {nurOffene ? "☑" : "☐"} {t("nur offene", "open only")}
                </button>
              </div>

              {gruppen.length === 0 && (
                <div style={{ fontSize: 13, color: "#9aa0ab" }}>{t("Nichts in dieser Auswahl.", "Nothing in this selection.")}</div>
              )}

              {gruppen.map((g) => {
                const offenG = !!auf[g.id];
                const farbe = FARBE[g.kind] || FARBE.feedback;
                return (
                  <div key={g.id} style={{ border: "1px solid #eef0f3", borderLeft: `4px solid ${farbe}`, borderRadius: 12, marginBottom: 10, overflow: "hidden" }}>
                    <button
                      onClick={() => setAuf({ ...auf, [g.id]: !offenG })}
                      aria-expanded={offenG}
                      style={{ width: "100%", textAlign: "left", background: offenG ? "#fafbff" : "#fff", border: "none", padding: "12px 14px", cursor: "pointer", display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}
                    >
                      {g.anzahl > 1 && (
                        <span style={{ fontSize: 12, fontWeight: 800, color: "#fff", background: farbe, borderRadius: 999, padding: "3px 9px" }}>×{g.anzahl}</span>
                      )}
                      <span style={{ fontSize: 12, fontWeight: 700, color: "#4f46e5", background: "#eef0fe", borderRadius: 999, padding: "4px 10px" }}>{g.label}</span>
                      <span style={{ fontSize: 11.5, color: "#9aa0ab" }}>
                        {t("zuletzt", "last")} {zeit(g.letzter)}
                        {g.offen > 0 ? ` · ${g.offen} ${t("offen", "open")}` : ` · ${t("erledigt", "done")}`}
                      </span>
                      <span style={{ marginLeft: "auto", color: "#9aa0ab", fontSize: 12 }}>{offenG ? "▲" : "▼"}</span>
                      <span style={{ flexBasis: "100%", fontSize: 13.5, lineHeight: 1.5, color: "#1a1c22", fontWeight: 500 }}>
                        {g.text ? `«${g.text}»` : <span style={{ color: "#9aa0ab", fontStyle: "italic" }}>{t("(ohne Text)", "(no text)")}</span>}
                      </span>
                    </button>

                    {offenG && (
                      <div style={{ borderTop: "1px solid #eef0f3", padding: "6px 14px 10px", display: "flex", flexDirection: "column", gap: 8 }}>
                        {g.eintraege.map((e) => (
                          <div key={e.id} style={{ borderTop: "1px solid #f4f5f8", padding: "10px 0 4px", opacity: e.resolved_at ? 0.6 : 1 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 4 }}>
                              <span style={{ fontSize: 11.5, color: "#9aa0ab" }}>
                                {zeit(e.created_at)} · {e.display_name} ({e.role}){e.page ? ` · ${e.page}` : ""}{e.attempt_id ? ` · ${t("Versuch", "Attempt")} #${e.attempt_id}` : ""}
                              </span>
                              <button onClick={() => erledigt(e)} style={e.resolved_at ? knopfNeutral : knopfGruen}>
                                {e.resolved_at ? `↩ ${t("Wieder öffnen", "Reopen")}` : `✓ ${t("Erledigt", "Done")}`}
                              </button>
                            </div>
                            {e.text && <div style={{ fontSize: 13.5, lineHeight: 1.5, whiteSpace: "pre-wrap", marginBottom: 6 }}>{e.text}</div>}
                            <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                              {e.image_path && (
                                <a href={`${api.base}${e.image_path}`} target="_blank" rel="noopener noreferrer" title={t("Bild öffnen", "Open image")}>
                                  <img src={`${api.base}${e.image_path}`} alt="" style={{ width: 110, height: 80, objectFit: "cover", borderRadius: 8, border: "1px solid #e7e8ee" }} />
                                </a>
                              )}
                              {e.context && <pre style={code}>{e.context}</pre>}
                            </div>
                            {e.attempt_id && (
                              <a href={`/app/lernen/${e.attempt_id}`} target="_blank" rel="noopener noreferrer" style={{ fontSize: 12, color: "#4f46e5", fontWeight: 600, display: "inline-block", marginTop: 6 }}>
                                {t("Gespräch öffnen →", "Open conversation →")}
                              </a>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}

              {data.gekappt && (
                <div style={{ fontSize: 12, color: "#9aa0ab", marginTop: 8 }}>
                  {t("Es werden nur die neuesten 2000 Rückmeldungen ausgewertet – wähl einen kürzeren Zeitraum.", "Only the newest 2000 entries are evaluated – choose a shorter period.")}
                </div>
              )}
            </Card>
          </>
        )}
      </div>
    </div>
  );
}

function Legende({ farbe, text }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span style={{ width: 10, height: 10, borderRadius: 3, background: farbe, display: "inline-block" }} />
      {text}
    </span>
  );
}

function Card({ title, children }) {
  return (
    <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 16, padding: 18, marginBottom: 16 }}>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12 }}>{title}</div>
      <div style={{ overflowX: "auto" }}>{children}</div>
    </div>
  );
}

const pille = (aktiv) => ({
  padding: "7px 13px",
  borderRadius: 999,
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
  border: "1px solid " + (aktiv ? "#4f46e5" : "#e7e8ee"),
  background: aktiv ? "#eef0fe" : "#fff",
  color: aktiv ? "#4f46e5" : "#6b7280",
});
const knopfGruen = { marginLeft: "auto", fontSize: 11, fontWeight: 600, border: "1px solid #c6e6cf", background: "#eef8f0", color: "#1a7f3c", borderRadius: 999, padding: "5px 11px", cursor: "pointer" };
const knopfNeutral = { ...knopfGruen, border: "1px solid #e7e8ee", background: "#fff", color: "#6b7280" };
const code = { fontSize: 12, background: "#f6f7fa", border: "1px solid #eef0f3", borderRadius: 8, padding: "8px 10px", whiteSpace: "pre-wrap", wordBreak: "break-word", margin: 0, color: "#3b3f4a", fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", flex: 1 };
