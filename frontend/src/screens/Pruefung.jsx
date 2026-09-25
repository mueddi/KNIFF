import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api.js";
import { useShell } from "../components/AppShell.jsx";
import { useLang } from "../lib/i18n.jsx";
import { useDialog } from "../lib/dialog.jsx";
import MathText from "../lib/MathText.jsx";
import DrawPad from "../components/DrawPad.jsx";

// Probeprüfung: bewusst KEIN Chat und KEINE Hinweise. Alle Aufgaben stehen
// untereinander, das Kind arbeitet sie durch und gibt am Schluss ab – wie auf
// einem Prüfungsblatt. Ein Tutor daneben würde die Prüfung wertlos machen.

const URTEIL = {
  correct: { text: ["✓ richtig", "✓ correct"], bg: "#e8f6ec", fg: "#1a7f3c" },
  incorrect: { text: ["✗ falsch", "✗ wrong"], bg: "#fdecec", fg: "#c0392b" },
  leer: { text: ["– nicht bearbeitet", "– left blank"], bg: "#f3f4f6", fg: "#6b7280" },
  unknown: { text: ["○ von Hand prüfen", "○ check by hand"], bg: "#fdf3e6", fg: "#a05c12" },
};

const KASTEN = { background: "#fff", border: "1px solid #e7e8ee", borderRadius: 16, padding: 18 };

export default function Pruefung() {
  const { examId } = useParams();
  const nav = useNavigate();
  const shell = useShell();
  const { t, lang } = useLang();
  const dialog = useDialog();
  const li = lang === "en" ? 1 : 0;
  const [pruefung, setPruefung] = useState(null);
  const [antworten, setAntworten] = useState({});
  const [stiftFuer, setStiftFuer] = useState(null);   // Aufgaben-ID mit offenem Stift
  const [bilder, setBilder] = useState({});
  const [busy, setBusy] = useState(false);
  const [fehler, setFehler] = useState("");
  const [ladefehler, setLadefehler] = useState(false);
  const oben = useRef(null);

  const laden = useCallback(async () => {
    try {
      const p = await api.get(`/api/exams/${examId}`);
      setPruefung(p);
      setAntworten(Object.fromEntries(p.items.map((i) => [i.id, i.student_answer || ""])));
      setBilder(Object.fromEntries(p.items.filter((i) => i.image_path).map((i) => [i.id, i.image_path])));
    } catch {
      setLadefehler(true);
    }
  }, [examId]);
  useEffect(() => { laden(); }, [laden]);

  async function abgeben() {
    const offen = pruefung.items.filter((i) => !(antworten[i.id] || "").trim() && !bilder[i.id]);
    if (offen.length) {
      const ja = await dialog.bestaetigen({
        titel: offen.length === 1
          ? t("Eine Aufgabe ist noch leer", "One task is still empty")
          : t(`${offen.length} Aufgaben sind noch leer`, `${offen.length} tasks are still empty`),
        text: t("Leere Aufgaben zählen als falsch.", "Blank tasks count as wrong."),
        bestaetigen: t("Trotzdem abgeben", "Submit anyway"),
        abbrechen: t("Zurück zur Prüfung", "Back to the test"),
      });
      if (!ja) return;
    }
    setBusy(true);
    setFehler("");
    try {
      const fertig = await api.post(`/api/exams/${examId}/abgeben`, {
        antworten: pruefung.items.map((i) => ({
          id: i.id, answer: antworten[i.id] || "", image_path: bilder[i.id] || null,
        })),
      });
      setPruefung(fertig);
      shell.reloadTopics?.();
      oben.current?.scrollIntoView({ behavior: "smooth" });
    } catch (e) {
      setFehler(e?.message || t("Das hat nicht geklappt.", "That didn't work."));
    } finally {
      setBusy(false);
    }
  }

  async function uebernehmen(item) {
    if (busy) return;
    setBusy(true);
    setFehler("");
    try {
      const { exercise_id } = await api.post(`/api/exams/${examId}/items/${item.id}/uebernehmen`);
      const st = await api.post(`/api/exercises/${exercise_id}/attempts`, {});
      shell.reloadTopics?.();
      nav(`/app/lernen/${st.attempt.id}`);
    } catch (e) {
      // Vorher verschluckt: der Knopf tat einfach nichts. Jetzt steht da, warum.
      setFehler(e?.message || t("Das hat nicht geklappt – versuch es nochmal.", "That didn't work – please try again."));
    } finally {
      setBusy(false);
    }
  }

  if (ladefehler) {
    return (
      <div style={{ height: "100%", display: "grid", placeItems: "center", background: "#f6f7fb" }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 34, marginBottom: 10 }}>🔍</div>
          <div style={{ fontSize: 16, fontWeight: 700 }}>{t("Prüfung nicht gefunden", "Test not found")}</div>
          <button onClick={() => nav("/app/themen")} className="btn-primary"
                  style={{ marginTop: 14, padding: "10px 18px", borderRadius: 11, border: "none", fontSize: 13 }}>
            {t("Zu den Themen", "Back to topics")}
          </button>
        </div>
      </div>
    );
  }
  if (!pruefung) {
    return <div style={{ display: "grid", placeItems: "center", height: "100%", color: "#9aa0ab", fontSize: 14 }}>{t("lädt …", "loading …")}</div>;
  }

  const fertig = pruefung.status === "bewertet";
  const note = pruefung.grade_value;

  return (
    <div style={{ height: "100%", overflowY: "auto", background: "#fbfbfd" }}>
      <div ref={oben} style={{ padding: "24px 28px", maxWidth: 820 }}>
        <span onClick={() => nav(`/app/themen/${pruefung.topic_id}`)}
              style={{ fontSize: 13, fontWeight: 600, color: "#4f46e5", cursor: "pointer" }}>
          {t("← Thema", "← Topic")}
        </span>
        <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em", margin: "6px 0 4px" }}>
          {t("Probeprüfung", "Practice test")}
        </div>
        <div style={{ fontSize: 13.5, color: "#6b7280", marginBottom: 18 }}>
          {fertig
            ? t("Fertig korrigiert. Unten siehst du, was sitzt und was du noch üben solltest.",
                "Marked. Below you can see what you've got and what to practice.")
            : t("Kein Tutor, keine Tipps – wie in einer echten Prüfung. Am Schluss abgeben.",
                "No tutor, no hints – just like a real test. Submit when you're done.")}
        </div>

        {fertig && (
          <div style={{ ...KASTEN, marginBottom: 18, display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap" }}>
            <div>
              <div style={{ fontSize: 34, fontWeight: 800, color: note >= 4 ? "#1a7f3c" : "#c0392b", lineHeight: 1.1 }}>
                {note?.toFixed(1)}
              </div>
              <div style={{ fontSize: 11.5, color: "#9aa0ab" }}>{t("geschätzte Note", "estimated grade")}</div>
            </div>
            <div style={{ fontSize: 13.5, color: "#3b3f4a" }}>
              {pruefung.richtig} {t("von", "of")} {pruefung.total} {t("richtig", "correct")}
              <div style={{ fontSize: 12, color: "#9aa0ab", marginTop: 2 }}>
                {t("Die Note ist eine Schätzung und steht jetzt in deinem Notenverlauf.",
                   "This is an estimate and now appears in your grade history.")}
              </div>
            </div>
          </div>
        )}

        {fertig && pruefung.ziele.length > 0 && (
          <div style={{ ...KASTEN, marginBottom: 18 }}>
            <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 10 }}>{t("Deine Lernziele", "Your goals")}</div>
            {/* Mit Trefferquote: «2 von 3» sagt einem Kind viel mehr als ein
                blosses «noch üben» – und entmutigt weniger. */}
            {pruefung.ziele.map((z) => {
              const sitzt = z.richtig === z.total;
              return (
                <div key={z.name} style={{ fontSize: 13.5, marginBottom: 6, display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ color: sitzt ? "#1a7f3c" : "#c0392b" }}>{sitzt ? "✓" : "○"}</span>
                  <span style={{ flex: 1, minWidth: 0 }}>{z.name}</span>
                  <span style={{ fontSize: 12, fontWeight: 700, color: sitzt ? "#1a7f3c" : "#c0392b" }}>
                    {z.richtig} {t("von", "of")} {z.total}
                  </span>
                </div>
              );
            })}
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {pruefung.items.map((item) => {
            const u = fertig ? URTEIL[item.verdict] : null;
            return (
              <div key={item.id} style={KASTEN}>
                <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 10 }}>
                  <span style={{ flex: "0 0 26px", width: 26, height: 26, borderRadius: 8, background: "#eef0fe", color: "#4f46e5", display: "grid", placeItems: "center", fontSize: 12.5, fontWeight: 800 }}>
                    {item.position}
                  </span>
                  <div style={{ flex: 1, minWidth: 0, fontSize: 14.5, lineHeight: 1.6 }}>
                    <MathText text={item.question} />
                  </div>
                  {u && (
                    <span style={{ fontSize: 11, fontWeight: 700, borderRadius: 999, padding: "3px 10px", background: u.bg, color: u.fg, whiteSpace: "nowrap" }}>
                      {u.text[li]}
                    </span>
                  )}
                </div>

                {bilder[item.id] && (
                  <img src={`${api.base}${bilder[item.id]}`} alt={t("Deine Zeichnung", "Your drawing")}
                       style={{ display: "block", maxWidth: 240, maxHeight: 180, borderRadius: 10, border: "1px solid #e7e8ee", marginBottom: 8 }} />
                )}

                {fertig ? (
                  <div style={{ fontSize: 13.5, color: "#6b7280", marginLeft: 38 }}>
                    {item.student_answer
                      ? <>{t("Deine Antwort:", "Your answer:")} <b style={{ color: "#1a1c22" }}>{item.student_answer}</b></>
                      : t("(nicht bearbeitet)", "(left blank)")}
                    {item.verdict !== "correct" && (
                      <button onClick={() => uebernehmen(item)}
                              style={{ marginLeft: 12, border: "1px solid #dcdff5", background: "#f8f8ff", color: "#4f46e5", borderRadius: 999, padding: "5px 12px", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                        {t("→ Mit dem Tutor üben", "→ Practice with the tutor")}
                      </button>
                    )}
                  </div>
                ) : (
                  <div style={{ display: "flex", gap: 8, marginLeft: 38, flexWrap: "wrap" }}>
                    <input value={antworten[item.id] || ""}
                           onChange={(e) => setAntworten((a) => ({ ...a, [item.id]: e.target.value }))}
                           placeholder={t("Deine Antwort, z.B. x = 5", "Your answer, e.g. x = 5")}
                           style={{ flex: "1 1 220px", border: "1px solid #d2d4dd", borderRadius: 10, padding: "9px 12px", fontSize: 14, outline: "none" }} />
                    <button onClick={() => setStiftFuer(item.id)} title={t("Mit dem Stift schreiben", "Write with the pen")}
                            style={{ border: "1px solid #dcdff5", background: "#f8f8ff", borderRadius: 10, padding: "9px 13px", fontSize: 14, cursor: "pointer" }}>✍️</button>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {fertig && fehler && <div style={{ marginTop: 14, fontSize: 13, color: "#c0392b" }}>{fehler}</div>}
        {!fertig && (
          <>
            {fehler && <div style={{ marginTop: 14, fontSize: 13, color: "#c0392b" }}>{fehler}</div>}
            <button onClick={abgeben} disabled={busy} className="btn-primary"
                    style={{ marginTop: 18, padding: "12px 22px", borderRadius: 12, fontSize: 14, border: "none", opacity: busy ? 0.6 : 1 }}>
              {busy ? t("wird korrigiert …", "marking …") : t("Prüfung abgeben", "Submit test")}
            </button>
          </>
        )}
        {fertig && (
          <button onClick={() => nav(`/app/themen/${pruefung.topic_id}`)} className="btn-primary"
                  style={{ marginTop: 18, padding: "12px 22px", borderRadius: 12, fontSize: 14, border: "none" }}>
            {t("Zurück zum Thema", "Back to the topic")}
          </button>
        )}
      </div>

      {stiftFuer !== null && (
        <DrawPad
          onClose={() => setStiftFuer(null)}
          onResult={({ text, imagePath }) => {
            // Die Erkennung liefert Text; das Bild haengt zusaetzlich dran,
            // damit die Handschrift bei der Korrektur nachvollziehbar bleibt.
            if (text) setAntworten((a) => ({ ...a, [stiftFuer]: text }));
            if (imagePath) setBilder((b) => ({ ...b, [stiftFuer]: imagePath }));
            setStiftFuer(null);
          }}
        />
      )}
    </div>
  );
}
