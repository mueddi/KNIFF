import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../lib/api.js";
import { useLang } from "../lib/i18n.jsx";

// Startseite. Sie muss drei Fragen beantworten, bevor jemand auf «Anmelden»
// drueckt: Was macht Kniff anders? Fuer wen ist es? Was kostet es – und ist
// es sicher fuer mein Kind?
//
// Sie zeigt IMMER Kniff Plus (Probe in Aufgaben, Abo pro Kind mit Tokens im
// Monat, Pakete dazu) – das ist das entschiedene Modell. Die Zahlen kommen
// von /api/pay/preise (config.py), damit hier nie etwas anderes steht als in
// der App; bis die Auskunft da ist, gelten die Standardwerte.
//
// Interaktiv statt Standbild: der Chat im Hero laesst sich durchspielen
// (Antworten anklicken, die Hilfe-Leiter fuellt sich), die Stufen sind
// Reiter, die Preise haben einen Monat/Jahr-Umschalter.
// Alles ohne KI-Aufruf und ohne Konto – kostet nichts.

const INDIGO = "#4f46e5";
const TEXT_2 = "#4b5563";
const TEXT_3 = "#6b7280";
const TEXT_4 = "#9aa0ab";
const TOKENS_PRO_AUFGABE = 16; // gemessen in der Produktion (KNIFF.md)

function Badge({ children, color = TEXT_3 }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 13.5, color }}>
      <span style={{ color: "#1a7f3c", fontWeight: 700 }}>✓</span>
      {children}
    </span>
  );
}

function Dot({ filled }) {
  return (
    <span className={filled ? "landing-dot landing-dot-filled" : "landing-dot"} style={{ width: 8, height: 8, borderRadius: "50%", background: filled ? INDIGO : "#fff", border: filled ? "none" : "1.5px solid #c9ccf6", display: "inline-block" }} />
  );
}

function Eyebrow({ children }) {
  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600, color: INDIGO, background: "#eef0fe", borderRadius: 999, padding: "7px 14px", marginBottom: 18 }}>
      {children}
    </div>
  );
}

function H2({ children }) {
  return (
    <h2 style={{ margin: "0 0 14px", fontSize: "clamp(28px, 3.4vw, 38px)", lineHeight: 1.12, fontWeight: 900, letterSpacing: "-.03em", textWrap: "balance" }}>
      {children}
    </h2>
  );
}

function Lead({ children }) {
  return <p style={{ margin: "0 0 28px", fontSize: 16.5, lineHeight: 1.6, color: TEXT_2, maxWidth: "58ch" }}>{children}</p>;
}

// Ein Abschnitt in voller Breite, Inhalt auf 1180px begrenzt; blendet beim
// Scrollen ein (Klasse landing-reveal, siehe theme.css).
function Section({ children, tinted = false, id }) {
  return (
    <section id={id} style={{ background: tinted ? "#fbfbfd" : "#fff", borderTop: tinted ? "1px solid #eef0f3" : "none", borderBottom: tinted ? "1px solid #eef0f3" : "none" }}>
      <div style={{ maxWidth: 1180, margin: "0 auto", padding: "64px 40px" }} className="landing-section landing-reveal">
        {children}
      </div>
    </section>
  );
}

const card = { background: "#fff", border: "1px solid #e7e8ee", borderRadius: 18, padding: "22px 22px 20px" };

// ---------------------------------------------------------------------------
// Spielbarer Chat: ein festes Drehbuch zur Aufgabe 3x + 5 = 20. Der Besucher
// waehlt eine Antwort, der «Tutor» reagiert wie Kniff – Frage statt Loesung,
// Betteln bringt nichts, nach zwei eigenen Schritten ist es geloest.
// ---------------------------------------------------------------------------
function DemoChat() {
  const { t, lang } = useLang();
  const en = lang === "en";
  const DREHBUCH = {
    start: {
      tutor: en ? <>Solve for x: <i style={{ fontFamily: "Georgia,serif", fontSize: 17 }}>3x + 5 = 20</i>. Where would you start?</> : <>Löse nach x auf: <i style={{ fontFamily: "Georgia,serif", fontSize: 17 }}>3x + 5 = 20</i>. Wo würdest du anfangen?</>,
      stufe: 0,
      wahl: [
        { text: t("ich weiss nöd wie afange", "i don't know how to start"), ziel: "frage" },
        { text: t("sag mir einfach die lösung", "just tell me the answer"), ziel: "betteln" },
        { text: t("−5 auf beiden Seiten", "−5 on both sides"), ziel: "minus" },
      ],
    },
    frage: {
      tutor: en ? <>No stress 🙂 Look at the left side: what is standing in the way next to the <b>3x</b>?</> : <>Kein Stress 🙂 Schau auf die linke Seite: Was steht da neben dem <b>3x</b> im Weg?</>,
      stufe: 1,
      wahl: [
        { text: t("die +5?", "the +5?"), ziel: "tipp" },
        { text: t("sag mir einfach die lösung", "just tell me the answer"), ziel: "betteln" },
      ],
    },
    betteln: {
      tutor: en ? <>Nice try 😄 That's exactly what I don't do. But I'll help you get there: what would have to disappear from the left side so that only <b>3x</b> remains?</> : <>Netter Versuch 😄 Genau das mache ich nicht. Aber ich helfe dir hin: Was müsste links verschwinden, damit nur noch <b>3x</b> dasteht?</>,
      stufe: 1,
      wahl: [
        { text: t("die +5", "the +5"), ziel: "tipp" },
        { text: t("keine ahnung", "no idea"), ziel: "tipp2" },
      ],
    },
    tipp: {
      tutor: en ? <>Exactly. And whatever you do on one side, you have to do on the other side too. So?</> : <>Genau. Und was du auf der einen Seite machst, musst du auch auf der anderen machen. Also?</>,
      stufe: 2,
      wahl: [
        { text: t("−5 auf beiden Seiten → 3x = 15", "−5 on both sides → 3x = 15"), ziel: "minus" },
        { text: t("+5 auf beiden Seiten?", "+5 on both sides?"), ziel: "falsch" },
      ],
    },
    tipp2: {
      tutor: en ? <>Then I'll show you the first step: −5 on both sides. What is left now?</> : <>Dann mache ich den ersten Schritt vor: −5 auf beiden Seiten. Was steht jetzt da?</>,
      stufe: 3,
      wahl: [
        { text: "3x = 15", ziel: "minus" },
        { text: "3x = 25", ziel: "falsch2" },
      ],
    },
    falsch: {
      tutor: en ? <>Hmm, then you'd get 3x + 10 = 25 – the 5 is still there. Try the opposite.</> : <>Hmm, dann hättest du 3x + 10 = 25 – die 5 ist immer noch da. Probier das Gegenteil.</>,
      stufe: 2,
      wahl: [{ text: t("−5 auf beiden Seiten → 3x = 15", "−5 on both sides → 3x = 15"), ziel: "minus" }],
    },
    falsch2: {
      tutor: en ? <>Check again: 20 − 5 is …?</> : <>Rechne nochmal nach: 20 − 5 ist …?</>,
      stufe: 3,
      wahl: [{ text: "15, also 3x = 15", ziel: "minus" }],
    },
    minus: {
      tutor: en ? <><span style={{ color: "#1a7f3c", fontWeight: 700 }}>✓ Checked.</span> Strong – the minus on both sides worked. Now the <b>x</b> is still stuck to the 3 – what do you do with that?</> : <><span style={{ color: "#1a7f3c", fontWeight: 700 }}>✓ Nachgerechnet.</span> Stark, das Minus auf beiden Seiten hat gesessen. Jetzt klebt das <b>x</b> noch an der 3 – was machst du damit?</>,
      stufe: 2,
      wahl: [
        { text: t("durch 3 teilen → x = 5", "divide by 3 → x = 5"), ziel: "geloest" },
        { text: t("−3 → x = 12?", "−3 → x = 12?"), ziel: "falsch3" },
      ],
    },
    falsch3: {
      tutor: en ? <>Careful: 3x means 3 <i>times</i> x. What undoes a multiplication?</> : <>Vorsicht: 3x heisst 3 <i>mal</i> x. Was macht ein Malnehmen rückgängig?</>,
      stufe: 2,
      wahl: [{ text: t("teilen! x = 5", "dividing! x = 5"), ziel: "geloest" }],
    },
    geloest: {
      tutor: en ? <><span style={{ color: "#1a7f3c", fontWeight: 700 }}>✓ x = 5 – correct.</span> Check: 3·5 + 5 = 20 ✓. You did that yourself – I only asked questions.</> : <><span style={{ color: "#1a7f3c", fontWeight: 700 }}>✓ x = 5 – richtig.</span> Probe: 3·5 + 5 = 20 ✓. Das hast du selbst gerechnet – ich habe nur gefragt.</>,
      stufe: 2,
      wahl: [],
      ende: true,
    },
  };

  const [verlauf, setVerlauf] = useState([{ rolle: "tutor", knoten: "start" }]);
  const [tippt, setTippt] = useState(false);
  const [stufe, setStufe] = useState(0);
  const listeRef = useRef(null);
  // Die Antwortknoepfe haengen am letzten TUTOR-Eintrag. Waehrend Kniff
  // «tippt», ist der letzte Eintrag die eigene Antwort ohne Kapitel – das
  // stuerzte beim ersten Klick ab.
  const letzterTutor = [...verlauf].reverse().find((e) => e.rolle === "tutor");
  const aktuell = DREHBUCH[letzterTutor?.knoten] || DREHBUCH.start;
  const fertig = !tippt && aktuell.ende;

  useEffect(() => {
    // beim Sprachwechsel von vorn, sonst mischen sich die Sprachen
    setVerlauf([{ rolle: "tutor", knoten: "start" }]);
    setStufe(0);
    setTippt(false);
  }, [lang]);

  useEffect(() => {
    const el = listeRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [verlauf, tippt]);

  function antworten(w) {
    if (tippt) return;
    setVerlauf((v) => [...v, { rolle: "kind", text: w.text }]);
    setTippt(true);
    const dauer = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? 150 : 900;
    setTimeout(() => {
      setVerlauf((v) => [...v, { rolle: "tutor", knoten: w.ziel }]);
      setStufe(Math.max(stufe, DREHBUCH[w.ziel].stufe));
      setTippt(false);
    }, dauer);
  }

  function nochmal() {
    setVerlauf([{ rolle: "tutor", knoten: "start" }]);
    setStufe(0);
    setTippt(false);
  }

  const bubbleTutor = { alignSelf: "flex-start", background: "#fff", border: "1px solid #e7e8ee", borderRadius: 16, borderBottomLeftRadius: 5, boxShadow: "0 6px 16px rgba(40,40,90,.06)", padding: "11px 15px", fontSize: 13.5, maxWidth: "88%", lineHeight: 1.5 };
  const bubbleKind = { alignSelf: "flex-end", background: "#6366f1", color: "#fff", borderRadius: 16, borderBottomRightRadius: 5, padding: "10px 15px", fontSize: 13.5, maxWidth: "84%" };

  return (
    <div style={{ position: "relative", zIndex: 1 }}>
      <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 22, boxShadow: "0 2px 6px rgba(40,40,90,.06),0 30px 60px rgba(40,40,90,.16)", overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "15px 18px", borderBottom: "1px solid #eef0f3" }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700 }}>{t("Probier's aus", "Try it")}</div>
            <div style={{ fontSize: 11.5, color: TEXT_4 }}>{t("Lineare Gleichungen · ohne Konto, ohne KI-Kosten", "Linear equations · no account, no AI costs")}</div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 9, background: "#eef0fe", borderRadius: 999, padding: "6px 12px" }} title={t("Hilfe-Leiter: so viel Hilfe war bisher nötig", "Help ladder: how much help was needed so far")}>
            <span style={{ fontSize: 10.5, fontWeight: 700, color: INDIGO }}>{t("HILFE", "HELP")}</span>
            <span style={{ display: "flex", gap: 4 }}>{[1, 2, 3, 4].map((i) => <Dot key={i} filled={i <= stufe} />)}</span>
          </div>
        </div>
        <div ref={listeRef} style={{ background: "#f6f7fb", padding: 20, display: "flex", flexDirection: "column", gap: 12, height: 300, overflowY: "auto", scrollBehavior: "smooth" }}>
          {verlauf.map((e, i) => (
            <div key={i} className="popin" style={e.rolle === "tutor" ? bubbleTutor : bubbleKind}>
              {e.rolle === "tutor" ? DREHBUCH[e.knoten].tutor : e.text}
            </div>
          ))}
          {tippt && (
            <div style={{ ...bubbleTutor, padding: "12px 16px" }} aria-label={t("Kniff schreibt", "Kniff is typing")}>
              <span className="landing-typing"><i /><i /><i /></span>
            </div>
          )}
        </div>
        <div style={{ padding: "12px 14px", borderTop: "1px solid #eef0f3", display: "flex", gap: 8, flexWrap: "wrap", minHeight: 58, alignItems: "center" }}>
          {fertig ? (
            <>
              <Link to="/login" className="btn-primary" style={{ fontSize: 13.5, padding: "10px 16px", borderRadius: 11, textDecoration: "none" }}>{t("Jetzt selbst üben →", "Practise yourself now →")}</Link>
              <button onClick={nochmal} className="landing-chip" type="button">↺ {t("Nochmal", "Again")}</button>
            </>
          ) : (
            <>
              <span style={{ fontSize: 11.5, color: TEXT_4, width: "100%" }}>{t("Deine Antwort:", "Your reply:")}</span>
              {aktuell.wahl.map((w) => (
                <button key={w.text} onClick={() => antworten(w)} disabled={tippt} className="landing-chip" type="button">{w.text}</button>
              ))}
            </>
          )}
        </div>
      </div>
      <div style={{ fontSize: 12.5, color: TEXT_4, textAlign: "center", marginTop: 12 }}>
        {t("Echter Ablauf, festes Drehbuch. In der App antwortet die KI auf das, was du wirklich schreibst.", "Real flow, fixed script. In the app the AI responds to what you actually write.")}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Preise: Monat/Jahr-Umschalter mit Ersparnis
// ---------------------------------------------------------------------------
function PreisKarte({ preise, probe, plusName }) {
  const { t } = useLang();
  const nav = useNavigate();
  const [jaehrlich, setJaehrlich] = useState(false);
  const monat = ((preise?.monat_rappen ?? 990) / 100).toFixed(2);
  const jahr = Math.round((preise?.jahr_rappen ?? 8900) / 100);
  const jahrProMonat = ((preise?.jahr_rappen ?? 8900) / 12 / 100).toFixed(2);
  const tokensMonat = preise?.plus_tokens_monat ?? 600;
  const pakete = preise?.pakete || [{ key: "schnupper", tokens: 200, rappen: 200 }, { key: "starter", tokens: 900, rappen: 900 }, { key: "power", tokens: 1900, rappen: 1900 }];
  const ersparnis = Math.round(((preise?.monat_rappen ?? 990) * 12 - (preise?.jahr_rappen ?? 8900)) / 100);

  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1.4fr", gap: 16, alignItems: "stretch" }} className="landing-hero">
        <div style={{ ...card, background: "#f8f8ff", border: "1px solid #e0e2fb" }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: INDIGO, letterSpacing: ".06em", marginBottom: 6 }}>{t("PROBE", "TRIAL")}</div>
          <div style={{ fontSize: 34, fontWeight: 900, letterSpacing: "-.03em", lineHeight: 1 }}>CHF 0.–</div>
          <div style={{ fontSize: 14, color: TEXT_3, margin: "6px 0 14px" }}>{t("einmalig, ohne Zahlungsangaben", "once, no payment details")}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <Badge>{t(`${probe} Aufgaben – jede so lange, wie du brauchst`, `${probe} tasks – each for as long as you need`)}</Badge>
            <Badge>{t("Alle Funktionen: Foto, Stift, Aufgabensammlung, Elternansicht", "All features: photo, pen, task collection, parent view")}</Badge>
            <Badge>{t("Kein Klarname, keine Kreditkarte", "No real name, no credit card")}</Badge>
          </div>
          <button onClick={() => nav("/login")} className="btn-primary" style={{ marginTop: 18, fontSize: 14, padding: "12px 20px", borderRadius: 11 }}>{t("Gratis probieren", "Try for free")}</button>
        </div>

        <div style={{ ...card, background: "#1a1c22", border: "1px solid #1a1c22", color: "#fff" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: "#c9ccf6", letterSpacing: ".06em" }}>{plusName.toUpperCase()} · {t("PRO KIND", "PER CHILD")}</div>
            <div role="group" aria-label={t("Laufzeit", "Term")} style={{ marginLeft: "auto", display: "flex", gap: 4, background: "#2a2d38", borderRadius: 999, padding: 3 }}>
              {[[false, t("Monatlich", "Monthly")], [true, t("Jährlich", "Yearly")]].map(([j, label]) => (
                <button key={label} type="button" onClick={() => setJaehrlich(j)} aria-pressed={jaehrlich === j}
                  style={{ border: "none", borderRadius: 999, padding: "6px 12px", fontSize: 12.5, fontWeight: 700, cursor: "pointer", background: jaehrlich === j ? "#fff" : "transparent", color: jaehrlich === j ? "#1a1c22" : "#c5c9d2", transition: "background .15s" }}>
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontSize: 40, fontWeight: 900, letterSpacing: "-.03em", lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>CHF {jaehrlich ? `${jahr}.–` : monat}</span>
            <span style={{ fontSize: 13.5, color: "#c5c9d2" }}>{jaehrlich ? t("im Jahr", "per year") : t("im Monat", "per month")}</span>
            {jaehrlich && ersparnis > 0 && (
              <span className="popin" style={{ fontSize: 11.5, fontWeight: 700, color: "#1a1c22", background: "#8be0a4", borderRadius: 999, padding: "4px 9px" }}>
                {t(`${ersparnis}.– gespart`, `save ${ersparnis}.–`)}
              </span>
            )}
          </div>
          <div style={{ fontSize: 12.5, color: TEXT_4, margin: "6px 0 16px", minHeight: 17 }}>
            {jaehrlich ? t(`entspricht ${jahrProMonat} im Monat · zwei Monate geschenkt`, `equals ${jahrProMonat} a month · two months free`) : t(`oder CHF ${jahr}.– im Jahr`, `or CHF ${jahr}.– a year`)}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <Badge color="#e5e7ef">{t(`${tokensMonat} Tokens im Monat – rund 35 bis 40 Aufgaben, unverbrauchte bleiben`, `${tokensMonat} tokens a month – around 35 to 40 tasks, unused ones carry over`)}</Badge>
            <Badge color="#e5e7ef">{t(`Mehr üben? Token-Pakete dazu, ab CHF ${(pakete[0].rappen / 100).toFixed(0)}.–`, `Practise more? Add token packages from CHF ${(pakete[0].rappen / 100).toFixed(0)}.–`)}</Badge>
            <Badge color="#e5e7ef">{t("Foto, Stift, Aufgabensammlung, Probeprüfungen", "Photo, pen, task collection, mock exams")}</Badge>
            <Badge color="#e5e7ef">{t("Jederzeit kündbar · Eltern schliessen ab: Stripe, Karte oder TWINT", "Cancel anytime · parents subscribe: Stripe, card or TWINT")}</Badge>
          </div>
          <button onClick={() => nav("/login")} className="btn-primary" style={{ marginTop: 18, fontSize: 14, padding: "12px 20px", borderRadius: 11, width: "100%" }}>
            {t(`Mit der Probe starten – ${plusName} kommt danach`, `Start with the trial – ${plusName} comes after`)}
          </button>
        </div>
      </div>

    </>
  );
}

export default function Landing() {
  const nav = useNavigate();
  const { t, lang, setLang } = useLang();
  const [preise, setPreise] = useState(null);
  const [gescrollt, setGescrollt] = useState(false);
  const [stufeTab, setStufeTab] = useState(1);

  useEffect(() => {
    api.get("/api/pay/preise").then(setPreise).catch(() => setPreise(null));
  }, []);

  // Kopfzeile bekommt beim Scrollen einen Hintergrund; Abschnitte blenden ein.
  useEffect(() => {
    const onScroll = () => setGescrollt(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    const reduziert = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const ziele = Array.from(document.querySelectorAll(".landing-reveal"));
    let beobachter = null;
    let notbremse = null;
    if (reduziert || !("IntersectionObserver" in window)) {
      ziele.forEach((el) => el.classList.add("is-visible"));
    } else {
      // Was beim Laden schon im Bild ist, sofort zeigen – nicht auf den
      // Beobachter warten. Und nach 1.5 s alles, falls er nie feuert
      // (Vorschau-Werkzeuge, alte Browser): unsichtbarer Inhalt ist schlimmer
      // als ein fehlender Effekt.
      const hoehe = window.innerHeight || 800;
      ziele.forEach((el) => {
        if (el.getBoundingClientRect().top < hoehe) el.classList.add("is-visible");
      });
      beobachter = new IntersectionObserver((eintraege) => {
        eintraege.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("is-visible");
            beobachter.unobserve(e.target);
          }
        });
      }, { rootMargin: "0px 0px -10% 0px", threshold: 0.08 });
      ziele.forEach((el) => beobachter.observe(el));
      notbremse = setTimeout(() => ziele.forEach((el) => el.classList.add("is-visible")), 1500);
    }
    return () => {
      window.removeEventListener("scroll", onScroll);
      beobachter?.disconnect();
      if (notbremse) clearTimeout(notbremse);
    };
  }, []);

  const plusName = preise?.plus_name || "Kniff Plus";
  const probe = preise?.trial_tasks ?? 10;
  const tokensMonat = preise?.plus_tokens_monat ?? 600;
  const monat = ((preise?.monat_rappen ?? 990) / 100).toFixed(2);
  const jahr = Math.round((preise?.jahr_rappen ?? 8900) / 100);
  const abProMonat = ((preise?.jahr_rappen ?? 8900) / 12 / 100).toFixed(2); // Jahresabo, pro Monat gerechnet

  const langBtn = (l) => ({ border: "none", background: "transparent", fontSize: 13, fontWeight: 700, cursor: "pointer", color: lang === l ? INDIGO : TEXT_4, padding: "2px 4px" });

  const SCHRITTE = [
    { icon: "📷", titel: t("Aufgabe hereinholen", "Bring in the task"),
      text: t("Fotografiere die Hausaufgabe, schreib sie mit dem Stift oder tipp sie ein. Oder nimm eine aus der Aufgabensammlung.", "Photograph the homework, write it with the pen or type it in. Or pick one from the task collection.") },
    { icon: "💬", titel: t("Kniff fragt zurück", "Kniff asks back"),
      text: t("Statt der Lösung kommt eine Frage, die zum ersten Schritt führt. Erst wenn du zweimal selbst probiert hast, zeigt Kniff den ganzen Weg.", "Instead of the answer comes a question that leads to the first step. Only after two attempts of your own does Kniff show the whole way.") },
    { icon: "✅", titel: t("Du löst, Kniff prüft nach", "You solve, Kniff checks"),
      text: t("Jede Rechnung wird im Hintergrund nachgerechnet. Stimmt das Ergebnis, ist die Aufgabe abgehakt – und du weisst, warum.", "Every calculation is checked in the background. If the result is right, the task is ticked off – and you know why.") },
  ];

  const STUFEN = [
    { n: 1, titel: t("Frage", "Question"), bsp: t("«Was steht links neben dem 3x im Weg?»", "“What is in the way next to the 3x on the left?”") },
    { n: 2, titel: t("Tipp", "Hint"), bsp: t("«Was auf der einen Seite passiert, muss auch auf der anderen passieren.»", "“Whatever happens on one side must happen on the other too.”") },
    { n: 3, titel: t("Teilschritt", "Partial step"), bsp: t("«Ich mach den ersten Schritt vor: auf beiden Seiten −5. Was steht jetzt da?»", "“I'll do the first step: −5 on both sides. What's left now?”") },
    { n: 4, titel: t("Lösungsweg", "Full solution"), bsp: t("Erst nach zwei eigenen Versuchen – dann Schritt für Schritt bis zum Schluss.", "Only after two attempts of your own – then step by step to the end.") },
  ];

  const STUFEN_KARTEN = [
    { titel: t("Mittelstufe", "Middle school"), klassen: t("4.–6. Klasse", "Grades 4–6"),
      themen: t("Grundoperationen, Brüche, Prozente, einfache Geometrie. Kleine Schritte, Alltagsbilder, kein Fachwort ohne Erklärung.", "Basic operations, fractions, percentages, simple geometry. Small steps, everyday images, no jargon without explanation."),
      aufgabe: t("Lena hat 24 Fr. Sackgeld und gibt 3/8 davon für ein Buch aus. Wie viel bleibt?", "Lena has 24 francs of pocket money and spends 3/8 of it on a book. How much is left?"),
      frage: t("Kniff: «Wie viel ist denn 1/8 von 24? Teil die 24 mal in 8 gleich grosse Stücke.»", "Kniff: “What is 1/8 of 24? Split the 24 into 8 equal pieces.”") },
    { titel: t("Oberstufe", "Secondary school"), klassen: t("7.–9. Klasse · Sek I · Lehrplan 21", "Grades 7–9 · Lehrplan 21"),
      themen: t("Gleichungen, Terme, Prozent und Zins, Geometrie, Pythagoras, Funktionen. Genau der Stoff, der in der Sek I geprüft wird.", "Equations, terms, percent and interest, geometry, Pythagoras, functions. Exactly what is tested in lower secondary."),
      aufgabe: t("Ein Velo kostet nach 15 % Rabatt noch 680 Fr. Was war der Preis vorher?", "After a 15 % discount a bike still costs 680 francs. What was the price before?"),
      frage: t("Kniff: «680 Fr. sind also nicht 100 %. Wie viel Prozent sind es?»", "Kniff: “So 680 francs is not 100 %. What percentage is it?”") },
    { titel: t("Gymnasium", "Gymnasium"), klassen: t("bis zur Matura", "up to the Matura"),
      themen: t("Funktionen, Analysis, Vektoren, Stochastik. Präzise Fachsprache, zügigere Schritte – die Hilfe-Leiter gilt trotzdem.", "Functions, calculus, vectors, probability. Precise terminology, faster steps – the help ladder still applies."),
      aufgabe: t("Bestimme die Extremstellen von f(x) = x³ − 3x.", "Find the extrema of f(x) = x³ − 3x."),
      frage: t("Kniff: «Welche Bedingung muss die erste Ableitung an einer Extremstelle erfüllen?»", "Kniff: “What condition must the first derivative satisfy at an extremum?”") },
  ];

  const SICHER = [
    { icon: "🙈", titel: t("Kein Klarname nötig", "No real name needed"), text: t("Zum Üben reicht eine E-Mail-Adresse und ein Spitzname.", "An email address and a nickname are enough to practise.") },
    { icon: "🔒", titel: t("Eltern sehen keine Chats", "Parents don't see chats"), text: t("Nur den Wochen-Überblick – und nur, wenn das Kind es freigibt.", "Only the weekly overview – and only if the child allows it.") },
    { icon: "📵", titel: t("Keine Werbung, kein Tracking", "No ads, no tracking"), text: t("Kniff verdient an dem, was du bezahlst – nicht an deinen Daten. Es gibt keine Werbepartner.", "Kniff earns from what you pay – not from your data. There are no advertising partners.") },
    { icon: "🖼️", titel: t("Fotos trainieren keine KI", "Photos don't train any AI"), text: t("Bilder werden nur für die Erkennung deiner Aufgabe verwendet. Daten liegen in Frankfurt (EU).", "Images are used only to recognise your task. Data is stored in Frankfurt (EU).") },
  ];

  const FAQ = [
    { q: t("Ist das nicht Schummeln?", "Isn't this cheating?"),
      a: t("Nein – das ist der Punkt. Kniff verrät die Lösung nie von sich aus. Es stellt Fragen, gibt Tipps und macht höchstens einen Teilschritt vor. Den ganzen Lösungsweg zeigt es erst, wenn du zweimal selbst probiert hast. Wer abschreiben will, ist hier falsch.", "No – that's the point. Kniff never gives away the answer on its own. It asks questions, gives hints and at most shows one partial step. It shows the whole solution only after you've tried twice yourself. If you want to copy, this is the wrong place.") },
    { q: t("Versteht Kniff Schweizerdeutsch?", "Does Kniff understand Swiss German?"),
      a: t("Ja. «Ich verstahs nöd» oder «chasch mir helfe» versteht Kniff selbstverständlich. Geantwortet wird auf Schweizer Hochdeutsch – oder auf Englisch, wenn du die App auf Englisch stellst.", "Yes. Swiss German like “ich verstahs nöd” or “chasch mir helfe” is understood as a matter of course. Kniff replies in Swiss Standard German – or in English if you set the app to English.") },
    { q: t("Was kostet Kniff?", "What does Kniff cost?"),
      a: t(`Die ersten ${probe} Aufgaben sind geschenkt – ohne Zahlungsangaben. Danach kostet ${plusName} CHF ${monat} im Monat oder ${jahr}.– im Jahr pro Kind. Darin sind ${tokensMonat} Tokens im Monat enthalten, das reicht für rund 35 bis 40 Aufgaben; unverbrauchte Tokens bleiben, und wer mehr braucht, kauft ein Paket dazu. Jederzeit kündbar, das Abo läuft dann bis zum Ende der bezahlten Zeit.`,
           `The first ${probe} tasks are on us – no payment details. After that ${plusName} costs CHF ${monat} a month or ${jahr}.– a year per child. That includes ${tokensMonat} tokens a month, enough for around 35 to 40 tasks; unused tokens carry over, and if you need more you buy a package. Cancel anytime; the subscription then runs until the end of the paid period.`) },
    { q: t("Was ist ein Token?", "What is a token?"),
      a: t(`Ein Token ist ein Rappen KI-Leistung. Jede Antwort von Kniff kostet je nach Aufgabe ein bis vier Tokens, eine Foto-Erkennung etwa zwei – eine ganze Aufgabe mit allen Zwischenschritten im Schnitt ${TOKENS_PRO_AUFGABE}. Tokens verfallen nie.`,
           `A token is one Rappen of AI computation. Each answer from Kniff costs one to four tokens depending on the task, a photo recognition about two – a whole task with all steps about ${TOKENS_PRO_AUFGABE} on average. Tokens never expire.`) },
    { q: t("Braucht mein Kind eine Kreditkarte?", "Does my child need a credit card?"),
      a: t(`Nein. Die Probe braucht keine Zahlungsangaben. ${plusName} schliessen Eltern über eine sichere Stripe-Seite ab, mit Karte oder TWINT – direkt aus der Elternansicht für ihr Kind.`,
           `No. The trial needs no payment details. Parents subscribe to ${plusName} through a secure Stripe page with a card or TWINT – straight from the parent view for their child.`) },
    { q: t("Kann Kniff sich irren?", "Can Kniff be wrong?"),
      a: t("Ja, wie jede KI. Deshalb rechnet Kniff jede Antwort im Hintergrund mit einem Mathe-Programm nach und zeigt Korrekturen offen an. Stimmt trotzdem etwas nicht, meldest du es mit einem Klick direkt aus dem Chat – wir lesen jede Meldung.", "Yes, like any AI. That's why Kniff re-checks every answer in the background with a maths engine and shows corrections openly. If something is still wrong, you report it with one click straight from the chat – we read every report.") },
    { q: t("Gibt es Kniff für Schulen?", "Is there Kniff for schools?"),
      a: t("Ja, es gibt einen Schul-Plan mit unbegrenzten Aufgaben für ganze Klassen. Schreib uns an die Adresse im Impressum.", "Yes, there is a school plan with unlimited tasks for whole classes. Write to us at the address in the legal notice.") },
  ];

  const aktiveStufe = STUFEN_KARTEN[stufeTab];

  return (
    <div style={{ minHeight: "100vh", background: "#fff", overflowX: "hidden" }}>
      <nav className={gescrollt ? "landing-nav landing-nav-fest" : "landing-nav"}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "14px 40px", maxWidth: 1180, margin: "0 auto", minWidth: 0 }} className="landing-section">
          <a href="#top" style={{ display: "flex", alignItems: "center", gap: 10, textDecoration: "none" }}>
            <span style={{ width: 26, height: 26, borderRadius: 8, background: "#6366f1" }} />
            <span style={{ fontWeight: 800, fontSize: 19, color: INDIGO, letterSpacing: "-.02em" }}>Kniff</span>
          </a>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>
            <a href="#so" className="landing-navlink" style={{ fontSize: 14, fontWeight: 600, color: TEXT_3 }}>{t("So funktioniert's", "How it works")}</a>
            <a href="#preise" className="landing-navlink" style={{ fontSize: 14, fontWeight: 600, color: TEXT_3 }}>{t("Preise", "Pricing")}</a>
            <a href="#eltern" className="landing-navlink" style={{ fontSize: 14, fontWeight: 600, color: TEXT_3 }}>{t("Für Eltern", "For parents")}</a>
            <span>
              <button onClick={() => setLang("de")} style={langBtn("de")}>DE</button>
              <span style={{ color: "#d2d4dd", fontSize: 13 }}>|</span>
              <button onClick={() => setLang("en")} style={langBtn("en")}>EN</button>
            </span>
            <Link to="/login" style={{ fontSize: 14, fontWeight: 600, border: "1px solid #d2d4dd", borderRadius: 11, padding: "9px 18px", background: "#fff" }}>{t("Anmelden", "Sign in")}</Link>
          </div>
        </div>
      </nav>

      {/* ---- Hero ---- */}
      <div id="top" style={{ position: "relative", maxWidth: 1180, margin: "0 auto", padding: "28px 40px 56px", display: "grid", gridTemplateColumns: "1.05fr .95fr", gap: 52, alignItems: "center" }} className="landing-hero landing-section">
        <div style={{ position: "absolute", inset: 0, background: "radial-gradient(1000px 480px at 78% -10%, #eef0fe, transparent 70%)", pointerEvents: "none" }} />
        <div style={{ position: "relative", zIndex: 1 }} className="landing-reveal">
          <Eyebrow>
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#6366f1" }} />
            {t("Mathe-Tutor für die Schweiz · 4. Klasse bis Matura", "Maths tutor for Switzerland · grade 4 to Matura")}
          </Eyebrow>
          <h1 style={{ margin: "0 0 16px", fontSize: "clamp(36px, 5vw, 54px)", lineHeight: 1.05, fontWeight: 900, letterSpacing: "-.035em", textWrap: "balance" }}>
            {t("Mathe verstehen. Nicht abschreiben.", "Understand maths. Don't copy answers.")}
          </h1>
          <p style={{ margin: "0 0 26px", fontSize: 18, lineHeight: 1.55, color: TEXT_2, maxWidth: "46ch" }}>
            {t("Kniff ist ein KI-Tutor, der dir die Lösung nie einfach verrät. Er stellt die richtige Frage zur richtigen Zeit – bis du selber draufkommst. Foto, Stift oder Tippen, auf Schweizerdeutsch oder Hochdeutsch.",
               "Kniff is an AI tutor that never just tells you the answer. It asks the right question at the right time – until you work it out yourself. Photo, pen or typing, in Swiss German or standard German.")}
          </p>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24, flexWrap: "wrap" }}>
            <button onClick={() => nav("/login")} className="btn-primary" style={{ fontSize: 16, padding: "15px 26px", borderRadius: 13 }}>
              {t(`${probe} Aufgaben gratis probieren`, `Try ${probe} tasks for free`)}
            </button>
            <a href="#so" className="btn-ghost" style={{ fontSize: 15, padding: "14px 20px", borderRadius: 13, display: "inline-block" }}>{t("So funktioniert's ↓", "How it works ↓")}</a>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 18 }}>
            <Badge>{t("Keine Kreditkarte zum Start", "No credit card to start")}</Badge>
            <Badge>{t(`Danach ${plusName} ab CHF ${abProMonat} im Monat, jederzeit kündbar`, `Then ${plusName} from CHF ${abProMonat} a month, cancel anytime`)}</Badge>
            <Badge>{t("Kein Klarname nötig", "No real name needed")}</Badge>
          </div>
        </div>

        <DemoChat />
      </div>

      {/* ---- So funktioniert's ---- */}
      <Section tinted id="so">
        <Eyebrow>{t("So funktioniert's", "How it works")}</Eyebrow>
        <H2>{t("Drei Schritte, und die Lösung ist deine.", "Three steps, and the solution is yours.")}</H2>
        <Lead>{t("Kniff arbeitet wie eine gute Nachhilfe-Person: Es schaut, was du schon hast, und gibt genau so viel Hilfe, wie du gerade brauchst – nicht mehr.", "Kniff works like a good tutor: it looks at what you already have and gives exactly as much help as you need right now – no more.")}</Lead>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }} className="landing-grid-3">
          {SCHRITTE.map((s, i) => (
            <div key={s.titel} style={card} className="landing-card">
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                <span style={{ width: 40, height: 40, borderRadius: 12, background: "#eef0fe", display: "grid", placeItems: "center", fontSize: 19 }}>{s.icon}</span>
                <span style={{ fontSize: 12, fontWeight: 700, color: TEXT_4, letterSpacing: ".06em" }}>{t("SCHRITT", "STEP")} {i + 1}</span>
              </div>
              <div style={{ fontSize: 17, fontWeight: 800, letterSpacing: "-.01em", marginBottom: 6 }}>{s.titel}</div>
              <div style={{ fontSize: 14.5, lineHeight: 1.55, color: TEXT_2 }}>{s.text}</div>
            </div>
          ))}
        </div>
      </Section>

      {/* ---- Die Hilfe-Leiter ---- */}
      <Section>
        <Eyebrow>{t("Die Hilfe-Leiter", "The help ladder")}</Eyebrow>
        <H2>{t("Vier Stufen Hilfe. Die Lösung ist die letzte.", "Four levels of help. The solution is the last one.")}</H2>
        <Lead>{t("Das ist der Kniff an Kniff: Hilfe kommt in kleinen Stufen, und jede Stufe lässt dir so viel wie möglich selbst zu tun. Die Stufen siehst du im Chat als vier Punkte.", "This is the trick behind Kniff: help comes in small steps, and each step leaves as much as possible for you to do yourself. You see the levels in the chat as four dots.")}</Lead>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }} className="landing-grid-4">
          {STUFEN.map((s) => (
            <div key={s.n} style={{ ...card, borderTop: `4px solid ${s.n === 4 ? "#1a7f3c" : INDIGO}` }} className="landing-card">
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <span style={{ display: "flex", gap: 4 }}>{[1, 2, 3, 4].map((i) => <Dot key={i} filled={i <= s.n} />)}</span>
                <span style={{ fontSize: 12, fontWeight: 700, color: TEXT_4 }}>{t("STUFE", "LEVEL")} {s.n}</span>
              </div>
              <div style={{ fontSize: 17, fontWeight: 800, marginBottom: 6 }}>{s.titel}</div>
              <div style={{ fontSize: 14, lineHeight: 1.55, color: TEXT_2, fontStyle: s.n < 4 ? "italic" : "normal" }}>{s.bsp}</div>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 18, fontSize: 14, color: TEXT_3, maxWidth: "70ch", lineHeight: 1.6 }}>
          {t("Wer nur «sag mir die Lösung» schreibt, bekommt sie nicht – sondern eine Frage. Wer zweimal ehrlich probiert hat, bekommt den ganzen Weg erklärt, mit Probe. So bleibt hängen, was geübt wurde.", "Anyone who just writes “tell me the answer” doesn't get it – they get a question. Anyone who has honestly tried twice gets the whole way explained, with a check. That way, what was practised sticks.")}
        </div>
      </Section>

      {/* ---- Für wen: Reiter ---- */}
      <Section tinted>
        <Eyebrow>{t("Für wen", "Who it's for")}</Eyebrow>
        <H2>{t("Von der 4. Klasse bis zur Matura.", "From grade 4 to the Matura.")}</H2>
        <Lead>{t("Du stellst beim Anmelden deine Stufe ein. Kniff passt Sprache, Schrittgrösse und Beispiele daran an – Sackgeld und Pizza in der Mittelstufe, Fachsprache am Gymi. Klick dich durch:", "You set your level when you sign up. Kniff adapts language, step size and examples – pocket money and pizza in middle school, proper terminology at the Gymnasium. Click through:")}</Lead>
        <div role="tablist" aria-label={t("Schulstufe", "School level")} style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16 }}>
          {STUFEN_KARTEN.map((k, i) => (
            <button key={k.titel} role="tab" aria-selected={stufeTab === i} onClick={() => setStufeTab(i)} type="button"
              className={stufeTab === i ? "landing-tab landing-tab-aktiv" : "landing-tab"}>
              {k.titel} <span style={{ fontWeight: 500, opacity: .75 }}>· {k.klassen}</span>
            </button>
          ))}
        </div>
        <div key={stufeTab} role="tabpanel" className="popin landing-hero" style={{ display: "grid", gridTemplateColumns: "1fr 1.2fr", gap: 16 }}>
          <div style={card}>
            <div style={{ fontSize: 12, fontWeight: 700, color: INDIGO, letterSpacing: ".04em", marginBottom: 4 }}>{aktiveStufe.klassen}</div>
            <div style={{ fontSize: 19, fontWeight: 800, letterSpacing: "-.01em", marginBottom: 8 }}>{aktiveStufe.titel}</div>
            <div style={{ fontSize: 14.5, lineHeight: 1.55, color: TEXT_2 }}>{aktiveStufe.themen}</div>
          </div>
          <div style={{ ...card, background: "#f6f7fb" }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: TEXT_4, letterSpacing: ".06em", marginBottom: 8 }}>{t("SO KLINGT DAS", "WHAT IT SOUNDS LIKE")}</div>
            <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 14, borderBottomLeftRadius: 5, padding: "11px 15px", fontSize: 14, marginBottom: 10, lineHeight: 1.5 }}>{aktiveStufe.aufgabe}</div>
            <div style={{ background: "#eef0fe", borderRadius: 14, borderBottomLeftRadius: 5, padding: "11px 15px", fontSize: 14, lineHeight: 1.5, color: "#1a1c22" }}>{aktiveStufe.frage}</div>
          </div>
        </div>
      </Section>

      {/* ---- Preise ---- */}
      <Section id="preise">
        <Eyebrow>{t("Was es kostet", "What it costs")}</Eyebrow>
        <H2>{t("Gratis probieren. Dann weiterüben mit Kniff Plus.", "Try it for free. Then keep practising with Kniff Plus.")}</H2>
        <Lead>{t(`Die ersten ${probe} Aufgaben sind geschenkt. Danach kostet ${plusName} weniger als eine Nachhilfestunde im Monat – mit ${tokensMonat} Tokens im Monat, pro Kind, jederzeit kündbar.`,
                 `The first ${probe} tasks are on us. After that ${plusName} costs less than one tutoring lesson a month – with ${tokensMonat} tokens a month, per child, cancel anytime.`)}</Lead>
        <PreisKarte preise={preise} probe={probe} plusName={plusName} />
      </Section>

      {/* ---- Für Eltern ---- */}
      <Section tinted id="eltern">
        <div style={{ display: "grid", gridTemplateColumns: ".95fr 1.05fr", gap: 52, alignItems: "center" }} className="landing-hero">
          <div>
            <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 22, boxShadow: "0 2px 6px rgba(40,40,90,.06),0 26px 54px rgba(40,40,90,.13)", overflow: "hidden" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "15px 18px", borderBottom: "1px solid #eef0f3" }}>
                <span style={{ fontSize: 16 }}>👪</span>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 700 }}>{t("Elternansicht", "Parent view")}</div>
                  <div style={{ fontSize: 11.5, color: TEXT_4 }}>{t("Mia · Oberstufe · diese Woche", "Mia · secondary school · this week")}</div>
                </div>
              </div>
              <div style={{ padding: 18 }}>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginBottom: 14 }}>
                  {[["7", t("Aufgaben bearbeitet", "Tasks worked on")], ["19", t("Eigene Rechenschritte", "Own steps")], ["4", t("Tage aktiv", "Days active")]].map(([v, l]) => (
                    <div key={l} style={{ background: "#f8f8ff", border: "1px solid #e0e2fb", borderRadius: 12, padding: "12px 10px", textAlign: "center" }}>
                      <div style={{ fontSize: 20, fontWeight: 800, color: INDIGO, letterSpacing: "-.02em" }}>{v}</div>
                      <div style={{ fontSize: 10.5, color: TEXT_3 }}>{l}</div>
                    </div>
                  ))}
                </div>
                <div style={{ fontSize: 13, color: TEXT_2, background: "#f6f7fb", borderRadius: 10, padding: "10px 13px", marginBottom: 12 }}>
                  {t("Woran gearbeitet wurde: Gleichungen (3), Brüche (2, viel Hilfe), Prozente (2)", "Worked on: equations (3), fractions (2, lots of help), percentages (2)")}
                </div>
                <div style={{ fontSize: 12, color: TEXT_4, display: "flex", alignItems: "center", gap: 7 }}>
                  <span>🔒</span> {t("Chats sind für Eltern nicht einsehbar", "Chats are not visible to parents")}
                </div>
              </div>
            </div>
          </div>
          <div>
            <Eyebrow>{t("👪 Für Eltern", "👪 For parents")}</Eyebrow>
            <H2>{t("Sie sehen, woran gearbeitet wurde – nie die Chats.", "You see what was worked on – never the chats.")}</H2>
            <Lead>{t(`Ihr Kind gibt Ihnen aus der App einen Einladungscode. Damit erstellen Sie ein eigenes Eltern-Konto und sehen jede Woche: welche Aufgaben bearbeitet wurden, wo viel Hilfe nötig war, wie selbständig gerechnet wurde. Die Gespräche selbst bleiben beim Kind. ${plusName} schliessen Sie dort mit einem Klick für Ihr Kind ab – die Rechnung geht an Sie.`, `Your child gives you an invitation code from the app. With it you create your own parent account and see every week: which tasks were worked on, where a lot of help was needed, how independently your child calculated. The conversations themselves stay with the child. You subscribe to ${plusName} for your child there with one click – the invoice goes to you.`)}</Lead>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Badge>{t("Eigenes Eltern-Konto, verknüpft per Code vom Kind", "Your own parent account, linked via a code from your child")}</Badge>
              <Badge>{t("Wochen-Überblick mit den bearbeiteten Aufgaben", "Weekly overview with the tasks worked on")}</Badge>
              <Badge>{t("Freigabe liegt beim Kind – jederzeit widerrufbar", "Sharing is controlled by the child – revocable anytime")}</Badge>
              <Badge>{t("Abo und Token-Pakete direkt aus der Elternansicht", "Subscription and token packages straight from the parent view")}</Badge>
            </div>
          </div>
        </div>
      </Section>

      {/* ---- Sicher für Kinder ---- */}
      <Section>
        <Eyebrow>{t("Sicher für Kinder", "Safe for children")}</Eyebrow>
        <H2>{t("Gebaut für Kinder, nicht für Datensammler.", "Built for children, not for data collectors.")}</H2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginTop: 24 }} className="landing-grid-4">
          {SICHER.map((s) => (
            <div key={s.titel} style={card} className="landing-card">
              <div style={{ fontSize: 24, marginBottom: 8 }}>{s.icon}</div>
              <div style={{ fontSize: 16, fontWeight: 800, marginBottom: 6 }}>{s.titel}</div>
              <div style={{ fontSize: 14, lineHeight: 1.55, color: TEXT_2 }}>{s.text}</div>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 16, fontSize: 13.5, color: TEXT_4 }}>
          {t("Die Antworten schreibt ein KI-Modell von Anthropic. Was genau übertragen wird, steht offen in der", "The answers are written by an AI model from Anthropic. What exactly is transmitted is set out openly in the")}{" "}
          <Link to="/datenschutz" style={{ color: INDIGO, fontWeight: 600 }}>{t("Datenschutzerklärung", "privacy policy")}</Link>.
        </div>
      </Section>

      {/* ---- Fragen ---- */}
      <Section tinted>
        <Eyebrow>{t("Häufige Fragen", "Frequently asked")}</Eyebrow>
        <H2>{t("Was Eltern und Kinder uns fragen.", "What parents and children ask us.")}</H2>
        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 20, maxWidth: 820 }}>
          {FAQ.map((f) => (
            <details key={f.q} className="landing-faq" style={{ ...card, padding: "14px 20px" }}>
              <summary style={{ fontSize: 16, fontWeight: 700, cursor: "pointer", listStyle: "none", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
                {f.q}<span className="landing-faq-chevron" style={{ color: TEXT_4, fontSize: 18, flexShrink: 0 }}>+</span>
              </summary>
              <div style={{ fontSize: 14.5, lineHeight: 1.6, color: TEXT_2, marginTop: 10, maxWidth: "70ch" }}>{f.a}</div>
            </details>
          ))}
        </div>
      </Section>

      {/* ---- Footer ---- */}
      <div style={{ background: "#1a1c22", color: "#fff", padding: "40px 40px 22px", textAlign: "center" }}>
        <div style={{ maxWidth: 1180, margin: "0 auto" }}>
          <div style={{ fontSize: 26, fontWeight: 900, letterSpacing: "-.03em", marginBottom: 8, textWrap: "balance" }}>
            {t("Die nächste Hausaufgabe wartet nicht.", "The next homework isn't waiting.")}
          </div>
          <div style={{ fontSize: 15, color: "#c5c9d2", marginBottom: 18 }}>{t(`Konto in einer Minute, ${probe} Aufgaben geschenkt, keine Kreditkarte.`, `Account in a minute, ${probe} tasks on us, no credit card.`)}</div>
          <Link to="/login" style={{ display: "inline-block", fontSize: 15, fontWeight: 600, color: "#fff", background: "#6366f1", borderRadius: 11, padding: "12px 22px" }}>{t("Kostenlos loslegen →", "Start for free →")}</Link>
        </div>
        <div style={{ maxWidth: 1180, margin: "30px auto 0", paddingTop: 16, borderTop: "1px solid #2c2f38", display: "flex", gap: 18, flexWrap: "wrap", justifyContent: "center", fontSize: 12.5, color: "#8b909c" }}>
          <span>© {new Date().getFullYear()} Kniff · St. Gallen</span>
          <Link to="/impressum" style={{ color: "#aab0bd" }}>{t("Impressum", "Legal notice")}</Link>
          <Link to="/datenschutz" style={{ color: "#aab0bd" }}>{t("Datenschutz", "Privacy")}</Link>
          <Link to="/agb" style={{ color: "#aab0bd" }}>{t("AGB", "Terms")}</Link>
          <span>{t("Verschlüsselte Übertragung · Daten in der EU", "Encrypted connection · data in the EU")}</span>
        </div>
      </div>
    </div>
  );
}
