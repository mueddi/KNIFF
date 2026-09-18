import { useEffect, useRef, useState, useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, getToken } from "../lib/api.js";
import { useShell } from "../components/AppShell.jsx";
import DrawPad from "../components/DrawPad.jsx";
import MathText from "../lib/MathText.jsx";
import MathFigure from "../components/MathFigure.jsx";
import { ProblemButton } from "../components/ProblemMelden.jsx";
import { useLang } from "../lib/i18n.jsx";
import { useDialog } from "../lib/dialog.jsx";


// Fehler MIT Begruendung vom Server. Ohne ihn wurde jede Absage ausser 401/402
// zu «Ups, da ging etwas schief» eingedampft – auch die Frequenz-Bremse und
// die E-Mail-Sperre, bei denen der Server genau sagt, was zu tun ist.
class ServerFehler extends Error {}

const STUFEN_LABEL = {
  1: ["Stufe 1: Aktivierende Frage", "Level 1: Activating question"],
  2: ["Stufe 2: Kleiner Tipp", "Level 2: Small hint"],
  3: ["Stufe 3: Teilschritt vorgemacht", "Level 3: Partial step shown"],
  4: ["Stufe 4: Volle Lösung", "Level 4: Full solution"],
};

function Ladder({ level, solved, ownAttempts = 0 }) {
  const { t, lang } = useLang();
  // Nach 2 echten eigenen Versuchen auf hoher Stufe ist die Loesung verdient
  const unlocked = !solved && level >= 3 && ownAttempts >= 2;
  const accent = solved || unlocked ? "#1a7f3c" : "#4f46e5";
  const bg = solved || unlocked ? "#e8f6ec" : "#eef0fe";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, background: bg, borderRadius: 999, padding: "6px 14px", transition: "background .3s" }}>
      <span style={{ fontSize: 11, fontWeight: 700, color: accent }}>{t("HILFE", "HELP")}</span>
      {[1, 2, 3, 4].map((i) => (
        <span
          key={i}
          title={STUFEN_LABEL[i][lang === "en" ? 1 : 0]}
          className={`ladder-dot ${i <= level ? "filled" : ""}`}
          style={{
            width: 9, height: 9, borderRadius: "50%", display: "inline-block", cursor: "help",
            background: i <= level ? accent : "#fff",
            border: i <= level ? "none" : `1.5px solid ${solved || unlocked ? "#bfe3cb" : "#c9ccf6"}`,
          }}
        />
      ))}
      <span style={{ fontSize: 11, fontWeight: 600, color: accent }}>
        {solved ? t("Gelöst 🎉", "Solved 🎉") : unlocked ? t("🔓 Lösung verfügbar", "🔓 Solution available") : `${t("Stufe", "Level")} ${Math.max(level, 0)}/4`}
      </span>
    </div>
  );
}

// Tutor-Text mit eingebetteten Skizzen: [[FIGUR]]{json}[[/FIGUR]]-Bloecke
// werden zu praezisen MathFigure-Vorlagen, der Rest bleibt MathText.
const FIG_RE = /\[\[FIGUR\]\]([\s\S]*?)\[\[\/FIGUR\]\]/g;

// Tolerant parsen: falls das Modell Fuellsel vor das JSON setzt (z.B. ein
// woertlich kopiertes «{json}»), das echte Objekt herausfischen.
function parseSpec(raw) {
  const t = (raw || "").trim();
  try {
    return JSON.parse(t);
  } catch { /* weiter unten retten */ }
  const start = t.indexOf('{"');
  const end = t.lastIndexOf("}");
  if (start !== -1 && end > start) {
    try {
      return JSON.parse(t.slice(start, end + 1));
    } catch { /* nicht rettbar */ }
  }
  return null;
}

function TutorContent({ text, streaming = false }) {
  const { t } = useLang();
  let src = text || "";
  let drawing = false;
  // Unvollstaendiger Block am Ende: ausblenden statt rohes JSON zu zeigen.
  // Gilt AUCH fuer gespeicherte Nachrichten – eine abgebrochene Antwort
  // (Client weg, Timeout) wird mit Torso gespeichert und zeigte danach bei
  // jedem Laden «[[FIGUR]]{"typ":"waage","links":"3x + 5» als Text.
  const open = src.lastIndexOf("[[FIGUR]]");
  if (open !== -1 && src.indexOf("[[/FIGUR]]", open) === -1) {
    src = src.slice(0, open);
    drawing = streaming; // nur live heisst das «zeichnet gerade»
  }
  const parts = [];
  let last = 0;
  let i = 0;
  const re = new RegExp(FIG_RE.source, "g");
  let m;
  while ((m = re.exec(src)) !== null) {
    if (m.index > last) parts.push(<MathText key={`t${i++}`} text={src.slice(last, m.index)} />);
    const spec = parseSpec(m[1]); // kaputtes JSON: Skizze still weglassen
    if (spec) parts.push(<MathFigure key={`f${i++}`} spec={spec} />);
    last = re.lastIndex;
  }
  if (last < src.length) parts.push(<MathText key={`t${i++}`} text={src.slice(last)} />);
  if (drawing) parts.push(<span key="draw" style={{ display: "block", fontSize: 12.5, color: "#9aa0ab", marginTop: 6 }}>{t("✏️ Skizze wird gezeichnet …", "✏️ drawing the sketch …")}</span>);
  return <>{parts}</>;
}

// Was diese Tutor-Antwort ist – macht die Hilfe-Stufen im Chat sichtbar.
const STAGE_TAG = {
  1: { label: ["💬 Frage zum Nachdenken", "💬 Question to think about"], bg: "#eef0fe", fg: "#4f46e5" },
  2: { label: ["💡 Kleiner Tipp", "💡 Small hint"], bg: "#fdf3e6", fg: "#a05c12" },
  3: { label: ["👣 Teilschritt vorgemacht", "👣 Partial step shown"], bg: "#e7f0fd", fg: "#1d4ed8" },
  4: { label: ["🔓 Ganzer Lösungsweg", "🔓 Full solution path"], bg: "#e8f6ec", fg: "#1a7f3c" },
};

// Visuelles Feedback zur SymPy-Prüfung unter der Schüler-Bubble (nie die Lösung)
const VERIFY_CHIP = {
  correct: { label: ["✓ stimmt!", "✓ correct!"], bg: "#e8f6ec", fg: "#1a7f3c" },
  partial: { label: ["→ guter Zwischenschritt", "→ good intermediate step"], bg: "#eef0fe", fg: "#4f46e5" },
  incorrect: { label: ["✗ noch nicht – bleib dran", "✗ not yet – keep going"], bg: "#fdecec", fg: "#c0392b" },
};

function Bubble({ role, verifyStatus, hintLevel, children }) {
  const { lang } = useLang();
  const li = lang === "en" ? 1 : 0;
  const tutor = role === "tutor";
  const chip = !tutor && VERIFY_CHIP[verifyStatus];
  const tag = tutor && STAGE_TAG[hintLevel];
  // Feedback direkt an der Bubble: richtig = gruen + ✓-Badge; falsch = weicher
  // roter Ring (bewusst NICHT rot gefuellt – soll nicht bestrafend wirken).
  const correct = !tutor && verifyStatus === "correct";
  const incorrect = !tutor && verifyStatus === "incorrect";
  return (
    <div style={{ alignSelf: tutor ? "flex-start" : "flex-end", maxWidth: "78%", display: "flex", flexDirection: "column", alignItems: tutor ? "flex-start" : "flex-end", gap: 4 }}>
      {tag && (
        <span style={{ marginLeft: 34, fontSize: 10.5, fontWeight: 700, borderRadius: 999, padding: "2px 9px", background: tag.bg, color: tag.fg }}>
          {tag.label[li]}
        </span>
      )}
      <div style={{ display: "flex", alignItems: "flex-end", gap: 8, position: "relative" }}>
        {tutor && (
          <span aria-hidden style={{ flex: "0 0 26px", width: 26, height: 26, borderRadius: "50%", background: "#eef0fe", color: "#4f46e5", display: "grid", placeItems: "center", fontSize: 13, fontWeight: 800, border: "1px solid #e0e2fb" }}>∑</span>
        )}
        <div
          className="popin"
          style={{
            background: tutor ? "#fff" : correct ? "#1f9048" : "#6366f1",
            color: tutor ? "#1a1c22" : "#fff",
            border: tutor ? "1px solid #e7e8ee" : "none",
            borderRadius: 18,
            borderBottomLeftRadius: tutor ? 5 : 18,
            borderBottomRightRadius: tutor ? 18 : 5,
            boxShadow: tutor
              ? "0 1px 2px rgba(40,40,90,.05),0 6px 16px rgba(40,40,90,.06)"
              : incorrect
                ? "0 0 0 2.5px #f3c1bc"
                : "none",
            padding: tutor ? "12px 16px" : "11px 16px",
            fontSize: 14.5,
            lineHeight: 1.6,
            whiteSpace: "pre-wrap",
          }}
        >
          {children}
        </div>
        {correct && (
          <span aria-hidden style={{ position: "absolute", top: -8, right: -8, width: 21, height: 21, borderRadius: "50%", background: "#1a7f3c", color: "#fff", fontSize: 11, fontWeight: 800, display: "grid", placeItems: "center", border: "2px solid #f6f7fb" }}>✓</span>
        )}
      </div>
      {chip && (
        <span className="verify-chip" style={{ fontSize: 11, fontWeight: 700, borderRadius: 999, padding: "3px 10px", background: chip.bg, color: chip.fg }}>
          {chip.label[li]}
        </span>
      )}
    </div>
  );
}

// Schnell-Antworten: ein Tipp genuegt – junge Schueler muessen nicht tippen.
//
// Die Beschriftung ist uebersetzt, der GESENDETE Text bleibt immer deutsch:
// die Absichts-Erkennung im Backend kennt nur deutsche Muster, weshalb jeder
// englische Knopf als blosses Reden ankam. Sichtbare Folge: der Knopf «Show me
// the full solution» erschien – und die Loesung wurde dann verweigert. Der
// Tutor antwortet trotzdem auf Englisch, das steuert die Regie-Anweisung.
// Die drei «anders erklären»-Wege stehen hinter EINEM Knopf. Grund: alle drei
// lösen im Backend genau denselben Zustand aus wie «Ich verstehe es nicht»
// (Absicht «simpler») – sie unterscheiden sich nur im Satz, den sie schicken.
// Vorne standen dafür fünf Chips nebeneinander, die für ein Kind gleich
// aussahen und dieselbe Art Antwort brachten.
const ANDERS = [
  { label: ["🎨 Mit Skizze", "🎨 With a sketch"], text: "Kannst du es mir mit einer Skizze zeigen?" },
  { label: ["🍕 Mit Alltagsbeispiel", "🍕 With an everyday example"], text: "Erklär es mir mit einem Beispiel aus dem Alltag." },
  { label: ["🔢 Mit Zahlen statt x", "🔢 With numbers instead of x"], text: "Erklär es mir mit konkreten Zahlen statt mit x." },
];

function QuickReplies({ solved, unlocked, onSend, onNew, onVariant, fertigMoeglich }) {
  const { t, lang } = useLang();
  const li = lang === "en" ? 1 : 0;
  const [andersOffen, setAndersOffen] = useState(false);
  const items = solved
    ? [
        ...(onVariant ? [{ label: t("🔁 Nochmal so eine", "🔁 Another one like this"), act: onVariant, accent: true }] : []),
        { label: t("🎯 Erklär mir den Weg nochmal", "🎯 Explain the path again"), act: () => onSend("Erklär mir den Lösungsweg nochmal Schritt für Schritt.") },
        { label: t("➕ Neue Aufgabe", "➕ New task"), act: onNew },
      ]
    : [
        // «Fertig» ist KEIN Knopf, der abhakt: das Kind sagt es dem Tutor, der
        // schaut die Rechnung an und entscheidet. Ein Haken zum Selberdruecken
        // waere eine Behauptung, keine Leistung – und stuende ab der ersten
        // Sekunde im Weg, bevor ueberhaupt etwas gerechnet wurde.
        ...(fertigMoeglich ? [{ label: t("✓ Ich bin fertig", "✓ I'm done"), act: () => onSend("Ich bin fertig."), accent: true }] : []),
        // verdient nach 2 eigenen Versuchen: die Loesung ist jetzt abholbar
        ...(unlocked ? [{ label: t("🔓 Zeig mir die ganze Lösung", "🔓 Show me the full solution"), act: () => onSend("Zeig mir die Lösung bitte.") }] : []),
        { label: t("🤔 Ich verstehe es nicht", "🤔 I don't get it"), act: () => onSend("Ich verstehe es nicht.") },
        { label: t("💡 Gib mir einen Tipp", "💡 Give me a hint"), act: () => onSend("Gib mir bitte einen Tipp.") },
        { label: t("👣 Zeig mir den ersten Schritt", "👣 Show me the first step"), act: () => onSend("Zeig mir bitte den ersten Schritt.") },
        ...(andersOffen
          ? ANDERS.map((a) => ({ label: a.label[li], act: () => { setAndersOffen(false); onSend(a.text); } }))
          : [{ label: t("🔄 Anders erklären", "🔄 Explain differently"), act: () => setAndersOffen(true) }]),
      ];
  return (
    <div style={{ display: "flex", gap: 8, overflowX: "auto", padding: "0 2px 9px", WebkitOverflowScrolling: "touch" }}>
      {items.map((it) => (
        <button
          key={it.label}
          onClick={it.act}
          style={{
            flex: "0 0 auto", borderRadius: 999, padding: "8px 14px", fontSize: 12.5, fontWeight: 600, whiteSpace: "nowrap",
            border: it.accent ? "1px solid #bfe3cb" : "1px solid #dcdff5",
            background: it.accent ? "#e8f6ec" : "#f8f8ff",
            color: it.accent ? "#1a7f3c" : "#4f46e5",
          }}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}

// Konfetti-Regen beim Lösen (rein dekorativ, respektiert prefers-reduced-motion)
const CONFETTI_COLORS = ["#6366f1", "#8b8ef7", "#1a7f3c", "#8be0a4", "#f2b93b", "#e878a8"];
function Confetti() {
  const pieces = Array.from({ length: 28 }, (_, i) => ({
    left: `${(i * 37 + 13) % 100}%`,
    delay: `${(i % 7) * 0.12}s`,
    dur: `${1.6 + (i % 5) * 0.22}s`,
    color: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
  }));
  return (
    <div aria-hidden style={{ position: "absolute", inset: 0, overflow: "hidden", pointerEvents: "none", zIndex: 15 }}>
      {pieces.map((p, i) => (
        <span key={i} className="confetti-piece" style={{ left: p.left, background: p.color, animationDuration: p.dur, animationDelay: p.delay }} />
      ))}
    </div>
  );
}

export default function Lernen() {
  const { attemptId } = useParams();
  const nav = useNavigate();
  const shell = useShell();
  const dialog = useDialog();
  const { t } = useLang();
  const [state, setState] = useState(null); // {attempt, messages, exercise}
  const [streaming, setStreaming] = useState("");
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [celebrate, setCelebrate] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [drawOpen, setDrawOpen] = useState(false);
  const [variantBusy, setVariantBusy] = useState(false);
  const [lightbox, setLightbox] = useState(null); // Bild-URL fuer die Gross-Ansicht (Aufgabe/Nachricht)
  const [pendingImage, setPendingImage] = useState(null); // Zeichnung/Foto fuer die naechste Nachricht
  const [uploadBusy, setUploadBusy] = useState(false); // 📷-Upload im Composer laeuft
  const fileRef = useRef(null);
  const [showTaskText, setShowTaskText] = useState(false); // Text unter Foto-Aufgabe
  const [showTaskImage, setShowTaskImage] = useState(true); // Aufgaben-Bild einklappbar (mehr Platz zum Chatten)
  const [stats, setStats] = useState(null); // {serie_tage, geloest_woche}
  const inputRef = useRef(null);
  const chatRef = useRef(null);
  // Jeder Attempt-Wechsel/Send bekommt eine Token-Nummer; abgelaufene Antworten
  // (Race beim Aufgabenwechsel waehrend des Streamens) werden verworfen.
  const reqToken = useRef(0);
  const abortRef = useRef(null);

  const nearBottom = (rand = 120) => {
    const el = chatRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < rand;
  };
  const scrollDown = useCallback(() => {
    requestAnimationFrame(() => {
      if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
    });
  }, []);

  // ``erstesLaden``: nur beim OEFFNEN der Session darf ein Fehler zur Meldung
  // «Diese Uebungssession gibt es nicht (mehr)» fuehren. Beim NACHLADEN nach
  // einer Antwort reichte bisher ein einziger wackliger Aufruf (Tunnel, 502),
  // um das ganze intakte Gespraech durch diese Sackgasse zu ersetzen.
  const load = useCallback(async (token, erstesLaden = false) => {
    if (!attemptId) return null;
    try {
      const s = await api.get(`/api/attempts/${attemptId}`);
      if (token !== undefined && token !== reqToken.current) return null; // veraltet
      setState(s);
      setLoadError(false);
      scrollDown();
      return s;
    } catch {
      if (token !== undefined && token !== reqToken.current) return null;
      if (erstesLaden) {
        setState(null);
        setLoadError(true);
      }
      return null;
    }
  }, [attemptId, scrollDown]);

  useEffect(() => {
    // Attempt gewechselt: laufenden Stream abbrechen, Token invalidieren, neu laden.
    const meins = ++reqToken.current;
    if (abortRef.current) abortRef.current.abort();
    setStreaming("");
    setBusy(false);
    setState(null);
    setLoadError(false);
    setPendingImage(null); // Anhang gehoert zur alten Aufgabe
    setShowTaskImage(true); // neue Aufgabe: Bild wieder zeigen
    setShowTaskText(false);
    // MIT Token: sonst greift der Veraltet-Schutz nicht, und beim schnellen
    // Hin- und Herwechseln (A -> B -> A) konnte die spaeter eintreffende
    // Antwort von B das Gespraech von A auf dem Bildschirm ueberschreiben,
    // waehrend Senden weiterhin an A ging.
    let nachschlag;
    load(meins, true).then((s) => {
      // Wer waehrend der Antwort woanders hinklickt, kommt zurueck und sieht
      // seine Frage OHNE Antwort – der Server schreibt sie erst zu Ende. Das
      // sah aus, als haette der Tutor das Kind ignoriert: es fragte nochmal
      // (doppelte Kosten) oder gab auf. Steht zuletzt eine Schuelernachricht,
      // laeuft die Antwort also noch: Punkte zeigen und kurz nachladen.
      const letzte = s?.messages?.[s.messages.length - 1];
      if (meins !== reqToken.current || letzte?.role !== "student") return;
      setBusy(true);
      nachschlag = setTimeout(() => {
        if (meins !== reqToken.current) return;
        load(meins).finally(() => {
          if (meins === reqToken.current) setBusy(false);
        });
      }, 4000);
    });
    return () => clearTimeout(nachschlag);
  }, [load]);

  useEffect(() => {
    if (nearBottom()) scrollDown();
  }, [streaming, state]);

  // Motivations-Zahlen (Serie/Woche) – einmal laden, nach jedem Lösen frisch
  useEffect(() => {
    api.get("/api/stats/mini").then(setStats).catch(() => setStats(null));
  }, [attemptId, state?.attempt?.solved]);

  async function send(overrideText) {
    // onClick={send} liefert ein Event-Objekt als erstes Argument – nur echte
    // Strings (Schnell-Antworten) zaehlen als Override.
    const text = (typeof overrideText === "string" ? overrideText : input).trim();
    if ((!text && !pendingImage) || busy) return;
    // Angehaengtes Bild (Zeichnung/Foto) mitschicken; ohne Text nur mit Platzhalter
    const img = pendingImage;
    const sendText = text || "(siehe Bild)";
    const myToken = ++reqToken.current;
    const myAttempt = attemptId;
    const controller = new AbortController();
    abortRef.current = controller;
    if (typeof overrideText !== "string") setInput(""); // getippten Entwurf nicht wegwerfen
    setPendingImage(null);
    setBusy(true);
    // Nachricht kam NICHT durch: Entwurf und Anhang zurueck ins Formular, damit
    // «Versuch es nochmal» auch wirklich moeglich ist. Bei einer Schnellantwort
    // bleibt das Eingabefeld leer – dort stand nie ein Entwurf drin.
    const zurueckgeben = () => {
      if (typeof overrideText !== "string" && text) setInput(text);
      if (img) setPendingImage(img);
    };
    // Schüler-Bubble sofort optimistisch anzeigen
    setState((s) => (s ? { ...s, messages: [...s.messages, { id: `tmp-${Date.now()}`, role: "student", text: sendText, image_path: img }] } : s));
    setStreaming("");
    scrollDown();
    // Kam schon Text an, IST der Turn passiert (der Server speichert auch eine
    // abgebrochene Antwort). Dann darf der Entwurf nicht zurueck, sonst
    // schickt das Kind dieselbe Nachricht ein zweites Mal – und zahlt doppelt.
    let gestreamt = false;
    try {
      // Einmal automatisch nachfassen, statt das Kind zu bitten, die Nachricht
      // nochmal zu schicken. NUR wenn die Anfrage gar nicht erst rausging
      // (Funkloch, Tunnel) – dann ist nichts gespeichert und nichts verrechnet.
      // Bei einer echten Absage des Servers (Guthaben, Sperre, Bremse) wird
      // NICHT wiederholt, die käme nur nochmal genauso zurück.
      let res;
      for (let anlauf = 0; ; anlauf++) {
        try {
          res = await fetch(`${api.base}/api/attempts/${myAttempt}/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
            body: JSON.stringify({ text: sendText, image_path: img || undefined }),
            signal: controller.signal,
          });
          break;
        } catch (netz) {
          if (anlauf > 0 || controller.signal.aborted || myToken !== reqToken.current) throw netz;
          await new Promise((r) => setTimeout(r, 3000));
        }
      }
      if (res.status === 401) {
        await api.get("/api/auth/me").catch(() => {}); // loest globalen Logout aus, falls Session weg
        if (myToken === reqToken.current) {
          // Session noch gueltig (Race) -> Fehlerhinweis statt stummer Nachricht
          zurueckgeben();
          setState((s) => (s ? { ...s, messages: [...s.messages.filter((m) => !String(m.id).startsWith("tmp-")), { id: `err-${Date.now()}`, role: "tutor", text: t("Ups, das hat nicht geklappt. Versuch es nochmal.", "Oops, that didn't work. Please try again.") }] } : s));
        }
        return;
      }
      if (res.status === 402) {
        // Guthaben leer: Nachricht wurde NICHT gesendet – optimistische Bubble
        // entfernen, Entwurf zurueckgeben und freundlich zum Laden einladen.
        if (myToken === reqToken.current) {
          const grund = res.headers.get("x-kniff-grund");
          setState((s) => (s ? { ...s, messages: [...s.messages.filter((m) => !String(m.id).startsWith("tmp-")), { id: `quota-${Date.now()}`, role: "tutor", kind: "quota", grund, text: "" }] } : s));
          zurueckgeben();
          shell.reloadQuota?.();
        }
        return;
      }
      if (!res.ok || !res.body) {
        // Der Server SAGT, was los ist («Langsam 🙂 – eine Nachricht nach der
        // anderen», «Bitte bestätige zuerst deine E-Mail-Adresse»). Bisher
        // wurde die Antwort nie gelesen und alles zu «Ups» eingedampft.
        let grund = "";
        try {
          grund = (await res.json())?.detail || "";
        } catch { /* kein JSON – dann bleibt der allgemeine Text */ }
        throw new ServerFehler(grund);
      }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let acc = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (myToken !== reqToken.current) return; // Aufgabe gewechselt -> Antwort verwerfen
        acc += dec.decode(value, { stream: true });
        gestreamt = true;
        setStreaming(acc);
        if (nearBottom()) scrollDown();
      }
      if (myToken !== reqToken.current) return;
      const wasSolved = state?.attempt?.solved;
      const fresh = await load(myToken); // echte Nachrichten + Leiter-Zustand nachladen
      // ERST jetzt den Stream-Text loeschen: vorher verschwand die fertige
      // Antwort fuer die Dauer des Nachladens und die Tipp-Punkte kamen
      // zurueck – nach jeder einzelnen Nachricht ein sichtbares Flackern.
      setStreaming("");
      if (myToken !== reqToken.current) return;
      shell.reloadQuota?.();
      if (!wasSolved) {
        shell.reloadTopics?.(); // Fortschritt in Sidebar/Grid aktualisieren
        // frisch gelöst -> Konfetti 🎉 (ausser reduced motion)
        if (fresh?.attempt?.solved && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
          setCelebrate(true);
          setTimeout(() => setCelebrate(false), 3200);
        }
      }
    } catch (e) {
      if (controller.signal.aborted || myToken !== reqToken.current) return; // bewusst abgebrochen
      setStreaming("");
      // Entwurf UND Zeichnung zurueckgeben: sonst stand «Versuch es nochmal»
      // da, waehrend beides geloescht war – erneutes Druecken tat gar nichts,
      // und eine mit dem Stift geschriebene Rechnung war unwiederbringlich weg.
      // Nur solange nichts gestreamt wurde (siehe oben).
      if (!gestreamt) zurueckgeben();
      const meldung = (e instanceof ServerFehler && e.message)
        ? e.message
        : t("Ups, da ging etwas schief. Versuch es nochmal.", "Oops, something went wrong. Please try again.");
      setState((s) => (s ? {
        ...s,
        // Die eigene Bubble nur wegnehmen, wenn die Nachricht wirklich nicht
        // ankam – sonst verschwindet sie vor den Augen des Kindes, obwohl sie
        // beim naechsten Laden wieder da ist.
        messages: [...(gestreamt ? s.messages : s.messages.filter((m) => !String(m.id).startsWith("tmp-"))),
                   { id: `err-${Date.now()}`, role: "tutor", text: meldung }],
      } : s));
    } finally {
      if (myToken === reqToken.current) setBusy(false);
    }
  }

  // Attempt-Load fehlgeschlagen (geloescht / fremd / Server weg) -> klarer Fehler
  if (attemptId && loadError) {
    return (
      <div style={{ flex: 1, background: "#f6f7fb", display: "grid", placeItems: "center", padding: 24, height: "100%" }}>
        <div style={{ textAlign: "center", maxWidth: 380 }}>
          <div style={{ fontSize: 34, marginBottom: 10 }}>🔍</div>
          <div style={{ fontSize: 17, fontWeight: 800, marginBottom: 6 }}>{t("Session nicht gefunden", "Session not found")}</div>
          <div style={{ fontSize: 14, color: "#6b7280", marginBottom: 18 }}>
            {t("Diese Übungssession gibt es nicht (mehr). Starte eine neue Aufgabe.", "This practice session doesn't exist (anymore). Start a new task.")}
          </div>
          <button onClick={() => shell.openNewTask()} className="btn-primary" style={{ padding: "12px 20px", borderRadius: 12, fontSize: 14 }}>
            {t("+ Neue Aufgabe", "+ New task")}
          </button>
        </div>
      </div>
    );
  }

  // Attempt gewählt, wird geladen -> dezenter Ladehinweis (kein Empty-State-Flackern)
  if (attemptId && !state) {
    return (
      <div style={{ flex: 1, background: "#f6f7fb", display: "grid", placeItems: "center", height: "100%", color: "#9aa0ab", fontSize: 14 }}>
        {t("lädt …", "loading …")}
      </div>
    );
  }

  // Kein Attempt gewählt -> Empty State
  if (!attemptId || !state) {
    return (
      <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, padding: "14px 22px", borderBottom: "1px solid #eef0f3" }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700 }}>{t("Lernen", "Learn")}</div>
            <div style={{ fontSize: 12, color: "#9aa0ab" }}>{t("Schritt für Schritt zur Lösung", "Step by step to the solution")}</div>
          </div>
          {/* keine Hilfe-Anzeige: sie gilt pro Aufgabe – hier ist keine offen */}
        </div>
        <div style={{ flex: 1, background: "#f6f7fb", display: "grid", placeItems: "center", padding: 24 }}>
          <div style={{ textAlign: "center", maxWidth: 420 }}>
            <div style={{ width: 64, height: 64, borderRadius: 18, background: "#eef0fe", color: "#4f46e5", fontSize: 28, display: "grid", placeItems: "center", margin: "0 auto 16px" }}>✎</div>
            <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 6 }}>{t("Bereit zum Üben?", "Ready to practice?")}</div>
            {stats?.serie_tage >= 2 && (
              <div style={{ display: "flex", gap: 8, justifyContent: "center", marginBottom: 12 }}>
                <span style={{ fontSize: 12.5, fontWeight: 700, color: "#d97706", background: "#fdf3e6", border: "1px solid #f2ddb8", borderRadius: 999, padding: "5px 13px" }}>🔥 {stats.serie_tage} {t("Tage in Folge", "days in a row")}</span>
              </div>
            )}
            <div style={{ fontSize: 14, color: "#6b7280", marginBottom: 20, lineHeight: 1.55 }}>
              {t("Leg eine neue Aufgabe an – tippe sie ab oder fotografiere sie. Ich verrate dir die Lösung nie direkt, sondern helfe dir Stufe für Stufe.", "Create a new task – type it in or take a photo. I never just tell you the answer; I help you level by level.")}
            </div>
            <button onClick={() => shell.openNewTask()} className="btn-primary" style={{ padding: "13px 22px", borderRadius: 12, fontSize: 15 }}>
              {t("+ Neue Aufgabe", "+ New task")}
            </button>
          </div>
        </div>
      </div>
    );
  }

  const { attempt, exercise } = state;
  const topicName = shell.topics?.find((t) => t.id === exercise.topic_id)?.name || t("Aufgabe", "Task");

  // Hand-Haken: die Aufgabe ist fertig, auch wenn die App sie nicht nachrechnen
  // kann (Zeichnen, Begruenden, zwei Unbekannte). Ohne diesen Knopf blieb so
  // eine Aufgabe fuer immer offen – der haeufigste Fall ueberhaupt.
  async function abhaken(geloest) {
    if (busy) return;
    setBusy(true);
    try {
      const a = await api.post(`/api/attempts/${attempt.id}/${geloest ? "geloest" : "offen"}`);
      setState((s) => (s ? { ...s, attempt: a } : s));
      shell.reloadTopics?.();
      if (geloest && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        setCelebrate(true);
        setTimeout(() => setCelebrate(false), 3200);
      }
    } catch (e) {
      await dialog.hinweis({
        titel: t("Das hat nicht geklappt", "That didn't work"),
        text: e?.message || t("Versuch es gleich nochmal.", "Please try again in a moment."),
      });
    } finally {
      setBusy(false);
    }
  }

  async function retry() {
    if (busy) return;
    setBusy(true);
    try {
      const st = await api.post(`/api/exercises/${exercise.id}/attempts`, {});
      nav(`/app/lernen/${st.attempt.id}`);
    } catch (e) {
      setState((s) => (s ? { ...s, messages: [...s.messages, { id: `err-${Date.now()}`, role: "tutor", text: e.message }] } : s));
    } finally {
      setBusy(false);
    }
  }

  // «Nochmal so eine»: KI erzeugt eine Variante (gleicher Typ, andere Zahlen)
  async function makeVariant() {
    if (busy || variantBusy) return;
    setVariantBusy(true);
    try {
      const st = await api.post(`/api/exercises/${exercise.id}/variante`, {});
      shell.reloadQuota?.();
      shell.reloadTopics?.();
      nav(`/app/lernen/${st.attempt.id}`);
    } catch (e) {
      if (e.status === 402) {
        setState((s) => (s ? { ...s, messages: [...s.messages, { id: `quota-${Date.now()}`, role: "tutor", kind: "quota", grund: e.grund, text: "" }] } : s));
      } else {
        setState((s) => (s ? { ...s, messages: [...s.messages, { id: `err-${Date.now()}`, role: "tutor", text: e.message }] } : s));
      }
    } finally {
      setVariantBusy(false);
    }
  }

  // OCR-Beschreibungszeilen ([Figur: …]/[Graph: …]) gehoeren nicht in den
  // Chat-Text – das Bild haengt sichtbar an der Nachricht und der Tutor
  // sieht es direkt. Nur der eigentliche Mathe-/Text-Inhalt bleibt.
  function stripFigureNotes(t) {
    return (t || "")
      .replace(/\[(Figur|Graph|Zeichnung|Skizze|Bild|Drawing|Figure|Sketch)\s*:[\s\S]*?\]/gi, "")
      .replace(/[ \t]+\n/g, "\n")
      .replace(/\n{2,}/g, "\n")
      .trim();
  }

  // Lose Figur-Beschriftungen («30», «x») ergeben ohne Bild keinen Sinn –
  // nur Text uebernehmen, der alleine aussagekraeftig ist (Satz, echtes
  // Wort oder echte Gleichung). Gleiche Heuristik wie im Backend-Opener.
  function looksMeaningful(t) {
    return (t || "").split("\n").some((line) => {
      const l = line.trim();
      if (!l) return false;
      if (l.split(/\s+/).length >= 3) return true;
      if (/[A-Za-zÄÖÜäöüß]{4,}/.test(l)) return true;
      if (l.includes("=")) return true;
      return false;
    });
  }

  // 📷 im Composer: Foto an die NAECHSTE Chat-Nachricht anhaengen.
  // Upload laeuft ueber die OCR-Route (speichert das Bild, liest den Text mit).
  async function attachPhoto(e) {
    const file = e.target.files?.[0];
    e.target.value = ""; // gleiches Foto darf erneut gewaehlt werden
    if (!file || uploadBusy) return;
    setUploadBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file, file.name || "foto.jpg");
      const res = await api.upload("/api/exercises/ocr", fd);
      const text = stripFigureNotes(res.text);
      if (text && looksMeaningful(text)) setInput((prev) => (prev.trim() ? `${prev.trim()} ${text}` : text));
      if (res.image_path) setPendingImage(res.image_path);
    } catch (err) {
      if (err.status === 402) {
        setState((s) => (s ? { ...s, messages: [...s.messages, { id: `quota-${Date.now()}`, role: "tutor", kind: "quota", grund: err.grund, text: "" }] } : s));
      } else {
        setState((s) => (s ? { ...s, messages: [...s.messages, { id: `err-${Date.now()}`, role: "tutor", text: err.message }] } : s));
      }
    } finally {
      setUploadBusy(false);
    }
  }

  // Mathe-Tastatur: Symbol an der Cursor-Position einfuegen
  function insertSymbol(snippet, cursorOffset) {
    const el = inputRef.current;
    const start = el?.selectionStart ?? input.length;
    const end = el?.selectionEnd ?? input.length;
    const next = input.slice(0, start) + snippet + input.slice(end);
    setInput(next);
    requestAnimationFrame(() => {
      if (!el) return;
      el.focus();
      const pos = start + (cursorOffset ?? snippet.length);
      el.setSelectionRange(pos, pos);
    });
  }

  const inputLooksMathy = /\d/.test(input) && /[+\-*/^=()]|sqrt|pi/.test(input);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", position: "relative" }}>
      {celebrate && <Confetti />}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, padding: "14px 22px", borderBottom: "1px solid #eef0f3", flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700 }}>{topicName}</div>
          <div style={{ fontSize: 12, color: "#9aa0ab" }}>
            {attempt.solved ? t("gelöst · gut gemacht", "solved · well done") : t("Schritt für Schritt", "Step by step")}
            {stats?.serie_tage >= 2 && <span style={{ color: "#d97706", fontWeight: 700 }}> · 🔥 {stats.serie_tage} {t("Tage in Folge", "days in a row")}</span>}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {/* Kein Knopf zum Selber-Abhaken: ob eine Aufgabe fertig ist,
              entscheidet der Tutor, wenn er die Rechnung gesehen hat. Was
              bleibt, ist die Korrektur eines FALSCHEN Hakens. */}
          {attempt.solved && (
            <>
              <button onClick={() => abhaken(false)} disabled={busy} className="btn-ghost"
                      style={{ fontSize: 12, padding: "8px 14px", borderRadius: 999 }}>
                {t("↩ Doch nicht fertig", "↩ Not done after all")}
              </button>
              <button onClick={retry} className="btn-ghost" style={{ fontSize: 12, padding: "8px 14px", borderRadius: 999 }}>
                {t("↻ Nochmal üben", "↻ Practice again")}
              </button>
            </>
          )}
          {/* Hilfe-Anzeige gilt PRO Aufgabe: erst zeigen, wenn in dieser
              Aufgabe Hilfe im Spiel ist (oder sie geloest wurde) – ein
              permanentes «Stufe 0/4» sagt nichts aus. */}
          {(attempt.solved || attempt.hint_level >= 1) && (
            <Ladder level={attempt.hint_level} solved={attempt.solved} ownAttempts={attempt.own_attempts} />
          )}
          {/* Ein Klick, wenn etwas schiefgeht: Aufgabe, Nachrichten und Bild
              gehen automatisch mit – das Kind muss nichts erklaeren. */}
          <ProblemButton attemptId={attempt.id} imagePath={exercise.image_path} />
        </div>
      </div>

      {/* Aufgabe immer sichtbar – Schueler muessen nie hochscrollen.
          Foto-Aufgaben: das BILD ist die Aufgabe (Text nur auf Wunsch). */}
      <div style={{ background: "#f6f7fb", padding: "12px 24px 0" }}>
        <div style={{ background: "#f8f8ff", border: "1px solid #e0e2fb", borderRadius: 14, padding: "10px 16px", maxHeight: exercise.image_path && showTaskImage ? 270 : 130, overflowY: "auto" }}>
          <div style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: ".07em", color: "#4f46e5", marginBottom: 3 }}>{t("DEINE AUFGABE", "YOUR TASK")}</div>
          {exercise.image_path ? (
            <>
              {showTaskImage && (
                <img
                  src={`${api.base}${exercise.image_path}`}
                  alt={t("Aufgaben-Bild", "Task image")}
                  title={t("🔍 vergrössern", "🔍 zoom in")}
                  onClick={() => setLightbox(exercise.image_path)}
                  style={{ display: "block", maxWidth: "100%", maxHeight: 190, borderRadius: 10, border: "1px solid #e0e2fb", cursor: "zoom-in" }}
                />
              )}
              <button
                onClick={() => setShowTaskImage(!showTaskImage)}
                style={{ border: "none", background: "transparent", color: "#6b7280", fontSize: 12, fontWeight: 600, cursor: "pointer", padding: "6px 12px 2px 0" }}
              >
                {t("Bild", "Image")} {showTaskImage ? t("ausblenden ▴", "hide ▴") : t("anzeigen ▾", "show ▾")}
              </button>
              {exercise.text && exercise.text !== "(Aufgabe auf dem Foto)" && (
                <>
                  <button
                    onClick={() => setShowTaskText(!showTaskText)}
                    style={{ border: "none", background: "transparent", color: "#6b7280", fontSize: 12, fontWeight: 600, cursor: "pointer", padding: "6px 0 2px" }}
                  >
                    {t("Aufgabentext", "Task text")} {showTaskText ? t("ausblenden ▴", "hide ▴") : t("anzeigen ▾", "show ▾")}
                  </button>
                  {showTaskText && (
                    <div style={{ fontSize: 13.5, lineHeight: 1.55, whiteSpace: "pre-wrap", color: "#4b4f5c" }}>
                      <MathText text={exercise.text} />
                    </div>
                  )}
                </>
              )}
            </>
          ) : (
            <div style={{ fontSize: 14.5, lineHeight: 1.55, whiteSpace: "pre-wrap" }}>
              <MathText text={exercise.text} />
            </div>
          )}
        </div>
      </div>

      <div ref={chatRef} style={{ flex: 1, background: "#f6f7fb", padding: "18px 24px 22px", display: "flex", flexDirection: "column", gap: 16, overflowY: "auto" }}>
        {(() => {
          const out = [];
          let lastLevel = 0;
          for (const m of state.messages) {
            if (m.role === "tutor" && m.hint_level) {
              if (lastLevel && m.hint_level > lastLevel) {
                out.push(
                  <div key={`lvl-${m.id}`} style={{ alignSelf: "center", fontSize: 11, fontWeight: 700, color: "#4f46e5", background: "#eef0fe", border: "1px solid #e0e2fb", borderRadius: 999, padding: "4px 13px" }}>
                    {t("⬆️ Nächste Hilfe-Stufe", "⬆️ Next help level")}
                  </div>
                );
              }
              lastLevel = m.hint_level;
            }
            if (m.kind === "quota") {
              // Drei Gruende, drei Karten: Probe aufgebraucht (Plus anbieten),
              // Fair-Use erreicht (freundlich, ohne Verkauf), altes Guthaben leer.
              const grund = m.grund || (shell.quota?.abo_enabled ? "trial" : "guthaben");
              const plusName = shell.quota?.plus_name || "Kniff Plus";
              const titel = grund === "fairuse"
                ? t("🎉 Wow – du hast diesen Monat riesig viel geübt!", "🎉 Wow – you practised a huge amount this month!")
                : grund === "trial"
                  ? t("🎁 Deine Gratis-Aufgaben sind aufgebraucht", "🎁 Your free tasks are used up")
                  : t("⚡ Dein Guthaben ist aufgebraucht", "⚡ Your balance is used up");
              const text = grund === "fairuse"
                ? t("Deine Nachricht wurde nicht gesendet. Ab dem 1. geht es weiter – bis dahin: gut gemacht.", "Your message was not sent. It continues on the 1st – until then: well done.")
                : grund === "trial"
                  ? t(`Deine Nachricht wurde nicht gesendet. Mit ${plusName} übst du weiter – so viel du willst, jederzeit kündbar.`, `Your message was not sent. With ${plusName} you keep practising – as much as you like, cancel anytime.`)
                  /* Bei einer Schnellantwort war das Eingabefeld nie gefuellt –
                     die alte Formulierung schickte einen auf die Suche. */
                  : t("Deine Nachricht wurde nicht gesendet. Lad Tokens oder warte auf die Gratis-Tokens vom nächsten Monat.", "Your message was not sent. Top up tokens or wait for next month's free tokens.");
              out.push(
                <div key={m.id} style={{ alignSelf: "flex-start", maxWidth: 420, background: "#fffaf0", border: "1px solid #f0e2c4", borderRadius: 16, padding: "14px 16px" }}>
                  <div style={{ fontSize: 13.5, fontWeight: 700, marginBottom: 4 }}>{titel}</div>
                  <div style={{ fontSize: 13, color: "#6b7280", lineHeight: 1.5, marginBottom: grund === "fairuse" ? 0 : 10 }}>{text}</div>
                  {grund !== "fairuse" && (
                    <button onClick={() => nav("/app/preise")} className="btn-primary" style={{ border: "none", borderRadius: 10, padding: "9px 14px", fontSize: 13 }}>
                      {grund === "trial" ? t(`${plusName} aktivieren →`, `Activate ${plusName} →`) : t("Tokens laden →", "Top up tokens →")}
                    </button>
                  )}
                </div>
              );
              continue;
            }
            const hideText = m.image_path && m.text === "(siehe Bild)"; // Platzhalter nicht doppelt zeigen
            out.push(
              <Bubble key={m.id} role={m.role} verifyStatus={m.verification_status} hintLevel={m.role === "tutor" ? m.hint_level : null}>
                {m.image_path && (
                  <img
                    src={`${api.base}${m.image_path}`}
                    alt={t("Angehängtes Bild", "Attached image")}
                    title={t("🔍 vergrössern", "🔍 zoom in")}
                    onClick={() => setLightbox(m.image_path)}
                    // Nach dem Laden nochmal ans Ende scrollen: das Bild hat
                    // beim ersten Scrollen noch keine Hoehe, deshalb ging ein
                    // Gespraech mit Zeichnungen mitten im Verlauf auf und die
                    // letzte Antwort stand unsichtbar darunter.
                    // Grosszuegiger Rand: das Bild ist bis 180 px hoch und hat
                    // die Ansicht gerade selbst nach unten geschoben.
                    onLoad={() => { if (nearBottom(340)) scrollDown(); }}
                    style={{ display: "block", maxWidth: 220, maxHeight: 180, borderRadius: 10, background: "#fff", border: "1px solid rgba(255,255,255,.4)", cursor: "zoom-in", marginBottom: hideText ? 0 : 8 }}
                  />
                )}
                {!hideText && (m.role === "tutor" ? <TutorContent text={m.text} /> : <MathText text={m.text} />)}
              </Bubble>
            );
          }
          return out;
        })()}
        {streaming && (
          <Bubble role="tutor">
            <TutorContent text={streaming} streaming />
          </Bubble>
        )}
        {busy && !streaming && (
          <Bubble role="tutor">
            <span className="typing-dot" /><span className="typing-dot" /><span className="typing-dot" />
          </Bubble>
        )}
        {attempt.solved && !busy && !streaming && (
          <div className="solved-banner" style={{ alignSelf: "center", display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", justifyContent: "center", background: "#e8f6ec", border: "1px solid #cde7d6", color: "#1a7f3c", borderRadius: 999, padding: "8px 18px", fontSize: 13, fontWeight: 700 }}>
            {t("🎉 Aufgabe gelöst – stark!", "🎉 Task solved – great job!")}
            <button onClick={makeVariant} disabled={variantBusy} style={{ border: "none", background: "transparent", color: "#1a7f3c", fontWeight: 700, fontSize: 13, textDecoration: "underline", cursor: "pointer", padding: 0 }}>
              {variantBusy ? t("erstelle Variante …", "creating variant …") : t("🔁 nochmal so eine", "🔁 another one like this")}
            </button>
            <button onClick={retry} style={{ border: "none", background: "transparent", color: "#1a7f3c", fontWeight: 700, fontSize: 13, textDecoration: "underline", cursor: "pointer", padding: 0 }}>
              {t("nochmal üben", "practice again")}
            </button>
            <button onClick={() => shell.openNewTask(exercise.topic_id ?? undefined)} style={{ border: "none", background: "transparent", color: "#1a7f3c", fontWeight: 700, fontSize: 13, textDecoration: "underline", cursor: "pointer", padding: 0 }}>
              {t("neue Aufgabe", "new task")}
            </button>
          </div>
        )}
      </div>

      <div style={{ padding: "12px 18px 14px", background: "#fff", borderTop: "1px solid #eef0f3" }}>
        {!busy && (
          <QuickReplies
            solved={attempt.solved}
            unlocked={attempt.hint_level >= 3 && attempt.own_attempts >= 2}
            onSend={(t) => send(t)}
            onNew={() => shell.openNewTask(exercise.topic_id ?? undefined)}
            onVariant={makeVariant}
            // Erst anbieten, wenn das Kind wirklich etwas gerechnet hat. Vorher
            // stand «✓ Ich bin fertig» ab der ersten Sekunde da – bevor
            // ueberhaupt eine Aufgabe angeschaut war.
            fertigMoeglich={attempt.own_attempts >= 1}
          />
        )}
        {inputLooksMathy && (
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, background: "#f8f8ff", border: "1px solid #e0e2fb", borderRadius: 12, padding: "7px 14px", marginBottom: 8, fontSize: 14, overflowX: "auto" }}>
            <span style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: ".06em", color: "#9aa0ab", flex: "0 0 auto" }}>{t("SO SIEHT'S AUS", "THIS IS HOW IT LOOKS")}</span>
            <MathText text={input} />
          </div>
        )}
        <div style={{ display: "flex", gap: 6, overflowX: "auto", paddingBottom: 8, WebkitOverflowScrolling: "touch" }}>
          {/* «½» und «÷» fügten beide denselben Schrägstrich ein – zwei Knöpfe
              für dieselbe Taste. Geblieben ist das Zeichen, das ein Kind aus
              der Schule kennt. */}
          {[
            ["x²", "^2"],
            ["√", "sqrt()", 5],
            ["×", "*"],
            ["÷", "/"],
            ["( )", "()", 1],
            ["=", "="],
            ["π", "pi"],
          ].map(([label, snippet, offset]) => (
            <button
              key={label}
              type="button"
              onMouseDown={(e) => e.preventDefault() /* Fokus bleibt im Eingabefeld */}
              onClick={() => insertSymbol(snippet, offset)}
              style={{ flex: "0 0 auto", minWidth: 40, borderRadius: 10, padding: "7px 10px", fontSize: 14, fontWeight: 600, border: "1px solid #e7e8ee", background: "#fbfbfd", color: "#1a1c22", cursor: "pointer" }}
            >
              {label}
            </button>
          ))}
        </div>
        {pendingImage && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, background: "#f8f8ff", border: "1px solid #e0e2fb", borderRadius: 12, padding: "6px 10px" }}>
            <img
              src={`${api.base}${pendingImage}`}
              alt={t("Bild-Anhang", "Image attachment")}
              onClick={() => setLightbox(pendingImage)}
              style={{ height: 48, maxWidth: 90, objectFit: "cover", borderRadius: 8, border: "1px solid #e0e2fb", cursor: "zoom-in", background: "#fff" }}
            />
            <span style={{ fontSize: 12.5, color: "#6b7280", flex: 1 }}>{t("Bild hängt an deiner nächsten Nachricht", "Image attached to your next message")}</span>
            <button onClick={() => setPendingImage(null)} aria-label={t("Bild entfernen", "Remove image")} style={{ border: "none", background: "transparent", color: "#9aa0ab", fontSize: 15, cursor: "pointer" }}>✕</button>
          </div>
        )}
        <input ref={fileRef} type="file" accept="image/*" onChange={attachPhoto} style={{ display: "none" }} />
        <div style={{ display: "flex", alignItems: "center", gap: 8, border: "1px solid #d2d4dd", borderRadius: 24, padding: "7px 8px 7px 14px" }}>
          <span onClick={() => !uploadBusy && fileRef.current?.click()} title={t("Foto anhängen", "Attach photo")} style={{ color: "#b6bcc6", fontSize: 15, cursor: "pointer", opacity: uploadBusy ? 0.5 : 1 }}>{uploadBusy ? "⏳" : "📷"}</span>
          <span onClick={() => setDrawOpen(true)} title={t("Mit dem Stift schreiben oder zeichnen", "Write or draw with a pen")} style={{ color: "#b6bcc6", fontSize: 15, cursor: "pointer" }}>✍️</span>
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder={t("Schreib deinen nächsten Schritt …", "Write your next step …")}
            style={{ flex: 1, border: "none", outline: "none", fontSize: 13, color: "#1a1c22", background: "transparent", paddingLeft: 4 }}
          />
          <button onClick={send} disabled={busy} style={{ width: 34, height: 34, borderRadius: "50%", background: "#6366f1", color: "#fff", border: "none", display: "grid", placeItems: "center", fontSize: 15, boxShadow: "0 2px 8px rgba(99,102,241,.35)", opacity: busy ? 0.6 : 1 }}>↑</button>
        </div>
      </div>

      {drawOpen && (
        <DrawPad
          onClose={() => setDrawOpen(false)}
          onResult={({ text, imagePath }) => {
            const clean = stripFigureNotes(text);
            if (clean && looksMeaningful(clean)) setInput((prev) => (prev.trim() ? `${prev.trim()} ${clean}` : clean));
            if (imagePath) setPendingImage(imagePath); // Zeichnung haengt als Bild an
          }}
        />
      )}

      {lightbox && (
        <div
          onClick={() => setLightbox(null)}
          onKeyDown={(e) => e.key === "Escape" && setLightbox(null)}
          tabIndex={-1}
          ref={(el) => el?.focus()}
          style={{ position: "fixed", inset: 0, background: "rgba(15,15,30,.82)", zIndex: 60, display: "grid", placeItems: "center", padding: 20, cursor: "zoom-out" }}
        >
          <img
            src={`${api.base}${lightbox}`}
            alt={t("Bild gross", "Image enlarged")}
            style={{ maxWidth: "92vw", maxHeight: "88vh", borderRadius: 14, boxShadow: "0 20px 60px rgba(0,0,0,.5)", background: "#fff" }}
          />
          <button
            onClick={() => setLightbox(null)}
            aria-label={t("Schliessen", "Close")}
            style={{ position: "fixed", top: 18, right: 18, width: 38, height: 38, borderRadius: "50%", border: "none", background: "rgba(255,255,255,.92)", color: "#1a1c22", fontSize: 17, fontWeight: 700, cursor: "pointer" }}
          >
            ✕
          </button>
        </div>
      )}
    </div>
  );
}
