import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../lib/api.js";
import { useShell } from "../components/AppShell.jsx";
import { useAuth } from "../lib/auth.jsx";
import { useLang, gradeLabel } from "../lib/i18n.jsx";
import { useDialog } from "../lib/dialog.jsx";
import Noten from "../components/Noten.jsx";
import PruefungStart from "../components/PruefungStart.jsx";

// Themen sind persoenliche Container: Name + Farbe (keine fixen Kategorien).
const TOPIC_COLORS = ["#6366f1", "#1a7f3c", "#c26a1f", "#d6558e", "#0e8f83", "#6b7280"];
const LABEL_COLOR = { Sitzt: "#1a7f3c", "Wird besser": "#4f46e5", "Noch üben": "#c0392b", Neu: "#6b7280" };
const MENU_ITEM = {
  display: "block", width: "100%", textAlign: "left", border: "none", background: "none",
  padding: "10px 14px", fontSize: 13, fontWeight: 600, color: "#3b3f4a", cursor: "pointer",
};

function TopicGrid() {
  const shell = useShell();
  const { user } = useAuth();
  const { t, lang } = useLang();
  const dialog = useDialog();
  // Anzeige-Uebersetzung der Backend-Keys (Keys selbst bleiben unveraendert)
  const LABEL_TEXT = {
    Sitzt: t("Sitzt", "Nailed it"),
    "Wird besser": t("Wird besser", "Getting better"),
    "Noch üben": t("Noch üben", "Keep practicing"),
    Neu: t("Neu", "New"),
  };
  const nav = useNavigate();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [color, setColor] = useState(TOPIC_COLORS[0]);
  const [imArchiv, setImArchiv] = useState(false);
  const [archiv, setArchiv] = useState([]);
  const [menu, setMenu] = useState(null); // id des Themas mit offenem ⋯-Menü

  // Aktive Themen kommen aus der Shell (die lädt sie ohne archivierte);
  // das Archiv holen wir nur, wenn der Reiter offen ist.
  const ladeArchiv = useCallback(async () => {
    try {
      setArchiv(await api.get("/api/topics?archiviert=true"));
    } catch {
      setArchiv([]);
    }
  }, []);
  useEffect(() => { if (imArchiv) ladeArchiv(); }, [imArchiv, ladeArchiv]);

  const topics = imArchiv ? archiv : (shell.topics || []);

  const [anlegen, setAnlegen] = useState(false);
  // Ref statt nur Zustand: Enter und Klick im selben Augenblick sehen beide
  // noch den alten Zustand – der Ref sperrt sofort.
  const anlegenLaeuft = useRef(false);
  async function createTopic() {
    if (!name.trim() || anlegenLaeuft.current) return; // Enter + Klick legte das Thema doppelt an
    anlegenLaeuft.current = true;
    setAnlegen(true);
    try {
      await api.post("/api/topics", { name: name.trim(), color });
      setName("");
      setAdding(false);
      shell.reloadTopics?.();
    } catch (e) {
      melden(e);
    } finally {
      anlegenLaeuft.current = false;
      setAnlegen(false);
    }
  }

  // Geht etwas schief, muss das Kind es SEHEN. Ohne diesen Fang blieb der
  // Fehler unbehandelt: die Karte stand einfach weiter da, ohne ein Wort.
  async function melden(fehler) {
    await dialog.hinweis({
      titel: t("Das hat nicht geklappt", "That didn't work"),
      text: fehler?.message || t("Versuch es gleich nochmal.", "Please try again in a moment."),
    });
  }

  async function archivieren(id) {
    setMenu(null);
    try {
      await api.post(`/api/topics/${id}/archivieren`);
    } catch (e) {
      return melden(e);
    }
    shell.reloadTopics?.();
    if (imArchiv) ladeArchiv();
  }

  async function wiederherstellen(id) {
    setMenu(null);
    try {
      await api.post(`/api/topics/${id}/wiederherstellen`);
    } catch (e) {
      return melden(e);
    }
    shell.reloadTopics?.();
    ladeArchiv();
  }

  async function loeschen(k) {
    setMenu(null);
    // Archivieren ist hier fast immer das Richtige – deshalb steht es gleich
    // im ERSTEN Fenster als empfohlener Weg. Frueher kamen hier bis zu drei
    // Browser-Fenster nacheinander, weil so eines nur «OK/Abbrechen» kann.
    const weg = await dialog.wahl({
      titel: t(`«${k.name}» löschen?`, `Delete “${k.name}”?`),
      text: t("Die Aufgaben bleiben erhalten – sie verlieren nur ihr Thema.",
              "The tasks are kept – they just lose their topic."),
      optionen: [
        { id: "archivieren", label: t("Archivieren", "Archive"), art: "primaer",
          hinweis: t("legt das Thema weg, behält aber alles", "puts the topic away but keeps everything") },
        { id: "loeschen", label: t("Löschen", "Delete"), art: "gefahr",
          hinweis: t("weg für immer", "gone for good") },
      ],
    });
    if (weg === "archivieren") return archivieren(k.id);
    if (weg !== "loeschen") return;
    try {
      await api.del(`/api/topics/${k.id}`);
    } catch (e) {
      // 409: am Thema hängen Noten. Der Server sagt, warum.
      if (e?.status !== 409) return melden(e);
      const trotzdem = await dialog.wahl({
        titel: t("Am Thema hängen Noten", "This topic has grades"),
        text: e.message,
        optionen: [
          { id: "archivieren", label: t("Archivieren", "Archive"), art: "primaer" },
          { id: "loeschen", label: t("Trotzdem löschen", "Delete anyway"), art: "gefahr",
            hinweis: t("die Noten bleiben, verlieren aber das Thema", "the grades are kept but lose their topic") },
        ],
      });
      if (trotzdem === "archivieren") return archivieren(k.id);
      if (trotzdem !== "loeschen") return;
      try {
        await api.del(`/api/topics/${k.id}?trotzdem=true`);
      } catch (e2) {
        return melden(e2);
      }
    }
    shell.reloadTopics?.();
    if (imArchiv) ladeArchiv();
  }

  return (
    <div style={{ height: "100%", overflowY: "auto", background: "#fbfbfd" }}>
      <div style={{ padding: "24px 28px 8px" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em", marginBottom: 4 }}>{t("Themen", "Topics")}</div>
            <div style={{ fontSize: 14, color: "#6b7280", marginBottom: 18 }}>{gradeLabel(user?.grade_level, lang)} · Lehrplan 21</div>
          </div>
          <button onClick={() => setAdding((v) => !v)} className="btn-primary" style={{ padding: "10px 16px", borderRadius: 11, fontSize: 13, border: "none" }}>{t("+ Neues Thema", "+ New topic")}</button>
        </div>
        {/* Reiter: aktive Themen / Archiv. Der Reiter erscheint erst, wenn es
            wirklich etwas Archiviertes gibt – sonst ist er nur Ballast. */}
        <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
          {[[false, t("Aktive Themen", "Active topics")], [true, t("Archiv", "Archive")]].map(([wert, beschriftung]) => (
            <button key={String(wert)} onClick={() => setImArchiv(wert)}
                    style={{ border: "1px solid", borderColor: imArchiv === wert ? "#c9ccf6" : "#e7e8ee",
                             background: imArchiv === wert ? "#eef0fe" : "#fff",
                             color: imArchiv === wert ? "#4f46e5" : "#6b7280",
                             borderRadius: 999, padding: "6px 14px", fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>
              {beschriftung}
            </button>
          ))}
        </div>
        {adding && (
          <div className="popin" style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16, background: "#fff", border: "1px solid #e7e8ee", borderRadius: 14, padding: 12, flexWrap: "wrap" }}>
            <input autoFocus value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && createTopic()} placeholder={t("Themen-Name, z.B. Bruchrechnen", "Topic name, e.g. fractions")} style={{ flex: "1 1 200px", border: "1px solid #d2d4dd", borderRadius: 10, padding: "9px 12px", fontSize: 14, outline: "none" }} />
            <div style={{ display: "flex", gap: 7 }}>
              {TOPIC_COLORS.map((c) => (
                <button
                  key={c}
                  onClick={() => setColor(c)}
                  aria-label={`${t("Farbe", "Color")} ${c}`}
                  style={{ width: 24, height: 24, borderRadius: "50%", background: c, border: "none", cursor: "pointer", outline: color === c ? `3px solid ${c}55` : "none", transform: color === c ? "scale(1.15)" : "none", transition: "transform .12s" }}
                />
              ))}
            </div>
            <button onClick={createTopic} disabled={anlegen} className="btn-primary" style={{ padding: "9px 16px", borderRadius: 10, fontSize: 13, border: "none", opacity: anlegen ? 0.6 : 1 }}>{t("Anlegen", "Create")}</button>
          </div>
        )}
      </div>
      <div style={{ padding: "14px 28px 28px", display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 16 }} className="themen-grid">
        {topics.length === 0 && (
          <div style={{ gridColumn: "1 / -1", background: "#fff", border: "1px dashed #d2d4dd", borderRadius: 16, padding: 30, textAlign: "center", color: "#6b7280" }}>
            <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 6, color: "#1a1c22" }}>{t("Noch keine Themen", "No topics yet")}</div>
            <div style={{ fontSize: 13 }}>{t("Themen sind deine eigenen Ordner – leg oben eins an und ordne Aufgaben zu.", "Topics are your own folders – create one above and add tasks to it.")}</div>
          </div>
        )}
        {topics.map((k) => {
          const fg = k.color || "#6366f1";
          const bg = `${fg}1f`; // Themen-Farbe mit leichter Deckkraft als Hintergrund
          return (
            <div key={k.id} onClick={() => nav(`/app/themen/${k.id}`)} style={{ position: "relative", background: "#fff", border: "1px solid #e7e8ee", borderRadius: 16, padding: 18, boxShadow: "0 1px 2px rgba(40,40,90,.04)", cursor: "pointer", opacity: imArchiv ? 0.75 : 1 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
                <span style={{ width: 36, height: 36, borderRadius: 11, fontWeight: 800, fontSize: 15, display: "grid", placeItems: "center", background: bg, color: fg }}>{k.name.charAt(0).toUpperCase()}</span>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, borderRadius: 999, padding: "3px 10px", background: bg, color: LABEL_COLOR[k.progress_label] || fg }}>{LABEL_TEXT[k.progress_label] || k.progress_label}</span>
                  <button onClick={(e) => { e.stopPropagation(); setMenu(menu === k.id ? null : k.id); }}
                          aria-label={t("Mehr", "More")} title={t("Mehr", "More")}
                          style={{ border: "none", background: "none", color: "#b6bcc6", cursor: "pointer", fontSize: 17, lineHeight: 1, padding: "0 2px" }}>⋯</button>
                </div>
              </div>
              {menu === k.id && (
                <div onClick={(e) => e.stopPropagation()} className="popin"
                     style={{ position: "absolute", top: 52, right: 14, zIndex: 5, background: "#fff", border: "1px solid #e7e8ee", borderRadius: 12, boxShadow: "0 6px 20px rgba(40,40,90,.12)", overflow: "hidden", minWidth: 168 }}>
                  {imArchiv ? (
                    <button onClick={() => wiederherstellen(k.id)} style={MENU_ITEM}>{t("↩ Wiederherstellen", "↩ Restore")}</button>
                  ) : (
                    <button onClick={() => archivieren(k.id)} style={MENU_ITEM}>{t("📦 Archivieren", "📦 Archive")}</button>
                  )}
                  <button onClick={() => loeschen(k)} style={{ ...MENU_ITEM, color: "#c0392b" }}>{t("🗑 Löschen", "🗑 Delete")}</button>
                </div>
              )}
              <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>{k.name}</div>
              <div style={{ fontSize: 12, color: "#9aa0ab", marginBottom: 12 }}>
                {k.solved_count}/{k.exercise_count} {t("gelöst", "solved")}
                {k.grade_avg != null && (
                  <> · <span style={{ fontWeight: 700, color: k.grade_avg >= 4 ? "#1a7f3c" : "#c0392b" }}>
                    ⌀ {k.grade_avg.toFixed(1)}
                  </span></>
                )}
              </div>
              <div style={{ height: 6, borderRadius: 999, background: "#eef0f3", overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${k.progress_pct}%`, background: k.progress_pct >= 90 ? "#1a7f3c" : "#6366f1" }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// Lernziele: die Grundlage der Probeprüfung. Frei formuliert, eine pro Zeile –
// ein Kind schreibt hier ab, was auf dem Arbeitsblatt oder an der Tafel steht.
function Lernziele({ topicId, start, onSaved }) {
  const { t } = useLang();
  const [text, setText] = useState(start);
  const [offen, setOffen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [fehler, setFehler] = useState("");
  // Wechselt das Thema (oder kommen die Themen erst nach), Feld nachziehen
  useEffect(() => { setText(start); }, [start, topicId]);

  async function speichern() {
    setBusy(true);
    setFehler("");
    try {
      await api.patch(`/api/topics/${topicId}`, { learning_goals: text });
      onSaved?.();
      setOffen(false);
    } catch (e) {
      // Vorher verschwand die Eingabe nicht, aber es kam auch kein Wort – das
      // Kind dachte, es sei gespeichert.
      setFehler(e?.message || t("Speichern hat nicht geklappt – versuch es nochmal.", "Saving didn't work – please try again."));
    } finally {
      setBusy(false);
    }
  }

  const zeilen = text.split("\n").map((z) => z.trim()).filter(Boolean);
  return (
    <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 16, padding: 18, marginBottom: 18 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ fontSize: 15, fontWeight: 700 }}>{t("Lernziele", "Learning goals")}</div>
        <button onClick={() => setOffen((v) => !v)}
                style={{ border: "1px solid #dcdff5", background: "#f8f8ff", color: "#4f46e5", borderRadius: 999, padding: "6px 13px", fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>
          {offen ? t("Abbrechen", "Cancel") : zeilen.length ? t("Bearbeiten", "Edit") : t("+ Ziele erfassen", "+ Add goals")}
        </button>
      </div>
      {offen ? (
        <div className="popin" style={{ marginTop: 12 }}>
          <textarea autoFocus value={text} onChange={(e) => setText(e.target.value)} rows={4}
                    placeholder={t("Was sollst du am Ende können? Ein Ziel pro Zeile, z.B.:\nBrüche kürzen\nBrüche addieren",
                                   "What should you be able to do? One goal per line, e.g.:\nreduce fractions\nadd fractions")}
                    style={{ width: "100%", boxSizing: "border-box", border: "1px solid #d2d4dd", borderRadius: 10, padding: "10px 12px", fontSize: 14, outline: "none", resize: "vertical", fontFamily: "inherit", lineHeight: 1.5 }} />
          {fehler && <div style={{ fontSize: 12.5, color: "#c0392b", margin: "8px 0" }}>{fehler}</div>}
          <button onClick={speichern} disabled={busy} className="btn-primary"
                  style={{ marginTop: 8, padding: "9px 16px", borderRadius: 10, fontSize: 13, border: "none", opacity: busy ? 0.6 : 1 }}>
            {t("Speichern", "Save")}
          </button>
        </div>
      ) : zeilen.length === 0 ? (
        <div style={{ fontSize: 13, color: "#6b7280", marginTop: 10 }}>
          {t("Noch keine Lernziele. Sie sind die Grundlage für die Probeprüfung.",
             "No learning goals yet. They're the basis for the practice test.")}
        </div>
      ) : (
        <ul style={{ margin: "10px 0 0", paddingLeft: 20, fontSize: 13.5, color: "#3b3f4a", lineHeight: 1.7 }}>
          {zeilen.map((z, i) => <li key={i}>{z}</li>)}
        </ul>
      )}
    </div>
  );
}

function TopicDetail({ topicId }) {
  const shell = useShell();
  const nav = useNavigate();
  const { t } = useLang();
  const topic = (shell.topics || []).find((t) => String(t.id) === String(topicId));
  const [exercises, setExercises] = useState([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setExercises(await api.get(`/api/topics/${topicId}/exercises`));
    } catch {
      setExercises([]);
    }
  }, [topicId]);
  useEffect(() => { load(); }, [load]);

  async function open(ex) {
    if (busy) return;
    setBusy(true);
    try {
      if (ex.latest_attempt_id) {
        nav(`/app/lernen/${ex.latest_attempt_id}`);
      } else {
        const st = await api.post(`/api/exercises/${ex.id}/attempts`, {});
        nav(`/app/lernen/${st.attempt.id}`);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ height: "100%", overflowY: "auto", background: "#fbfbfd" }}>
      <div style={{ padding: "24px 28px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <span onClick={() => nav("/app/themen")} style={{ fontSize: 13, fontWeight: 600, color: "#4f46e5", cursor: "pointer" }}>{t("← Themen", "← Topics")}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
          <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em" }}>{topic?.name || t("Thema", "Topic")}</div>
          <button onClick={() => shell.openNewTask(Number(topicId))} className="btn-primary" style={{ padding: "10px 16px", borderRadius: 11, fontSize: 13, border: "none" }}>{t("+ Neue Aufgabe", "+ New task")}</button>
        </div>

        <Noten topicId={topicId} />
        <Lernziele topicId={topicId} start={topic?.learning_goals || ""} onSaved={shell.reloadTopics} />
        {/* Lernziele mitgeben: sobald sie gespeichert sind, holt die
            Pruefungs-Karte ihre Vorschau neu – sonst haelt sie an ihrer
            veralteten Auskunft fest. */}
        <PruefungStart topicId={topicId} lernziele={topic?.learning_goals || ""} />

        <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 10 }}>{t("Aufgaben", "Tasks")}</div>
        {exercises.length === 0 && (
          <div style={{ background: "#fff", border: "1px dashed #d2d4dd", borderRadius: 16, padding: 30, textAlign: "center", color: "#6b7280" }}>
            <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 6, color: "#1a1c22" }}>{t("Noch keine Aufgaben", "No tasks yet")}</div>
            <div style={{ fontSize: 13 }}>{t("Leg mit «+ Neue Aufgabe» los – tippen oder fotografieren.", "Get started with “+ New task” – type it in or snap a photo.")}</div>
          </div>
        )}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {exercises.map((ex) => (
            <div key={ex.id} onClick={() => open(ex)} style={{ display: "flex", alignItems: "center", gap: 14, background: "#fff", border: "1px solid #e7e8ee", borderRadius: 14, padding: "14px 16px", cursor: "pointer" }}>
              <span style={{ width: 34, height: 34, borderRadius: 10, display: "grid", placeItems: "center", background: ex.solved ? "#e8f6ec" : "#eef0fe", color: ex.solved ? "#1a7f3c" : "#4f46e5", fontWeight: 700 }}>{ex.solved ? "✓" : "∑"}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{ex.image_path ? "📷 " : ""}{ex.text}</div>
                <div style={{ fontSize: 12, color: "#9aa0ab" }}>{ex.solved ? t("gelöst", "solved") : ex.latest_attempt_id ? t("weiter üben", "keep practicing") : t("noch nicht gestartet", "not started yet")}</div>
              </div>
              <span style={{ color: "#b6bcc6", fontSize: 18 }}>›</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function Themen() {
  const { topicId } = useParams();
  return topicId ? <TopicDetail topicId={topicId} /> : <TopicGrid />;
}
