import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../lib/api.js";
import { useLang } from "../lib/i18n.jsx";

// Startseite. Sie muss drei Fragen beantworten, bevor jemand auf «Anmelden»
// drueckt: Was macht Kniff anders? Fuer wen ist es? Was kostet es – und ist
// es sicher fuer mein Kind? Vorher standen hier nur das Versprechen und die
// Elternansicht; alles andere musste man durch Ausprobieren herausfinden.
//
// Preise und Modell kommen von /api/pay/preise (config.py), damit die
// Startseite nie etwas anderes verspricht als die App: mit dem Schalter
// ABO_ENABLED gilt Kniff Plus (Probe in Aufgaben, Abo pro Kind), ohne ihn
// das alte Modell (50 Gratis-Tokens im Monat, Einmal-Pakete). Solange die
// Auskunft noch laedt, zeigt die Seite Kniff Plus.

const INDIGO = "#4f46e5";
const TEXT_2 = "#4b5563";
const TEXT_3 = "#6b7280";
const TEXT_4 = "#9aa0ab";

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
    <span style={{ width: 8, height: 8, borderRadius: "50%", background: filled ? INDIGO : "#fff", border: filled ? "none" : "1.5px solid #c9ccf6" }} />
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

// Ein Abschnitt in voller Breite, Inhalt auf 1180px begrenzt
function Section({ children, tinted = false, id }) {
  return (
    <section id={id} style={{ background: tinted ? "#fbfbfd" : "#fff", borderTop: tinted ? "1px solid #eef0f3" : "none", borderBottom: tinted ? "1px solid #eef0f3" : "none" }}>
      <div style={{ maxWidth: 1180, margin: "0 auto", padding: "64px 40px" }} className="landing-section">
        {children}
      </div>
    </section>
  );
}

const card = { background: "#fff", border: "1px solid #e7e8ee", borderRadius: 18, padding: "22px 22px 20px" };

export default function Landing() {
  const nav = useNavigate();
  const { t, lang, setLang } = useLang();
  const [preise, setPreise] = useState(null);
  useEffect(() => {
    api.get("/api/pay/preise").then(setPreise).catch(() => setPreise(null));
  }, []);
  const abo = preise ? preise.abo_enabled : true;
  const plusName = preise?.plus_name || "Kniff Plus";
  const probe = preise?.trial_tasks ?? 10;
  const monat = ((preise?.monat_rappen ?? 990) / 100).toFixed(2);
  const jahr = Math.round((preise?.jahr_rappen ?? 8900) / 100);
  const jahrProMonat = ((preise?.jahr_rappen ?? 8900) / 12 / 100).toFixed(2);

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
      themen: t("Grundoperationen, Brüche, Prozente, einfache Geometrie. Kleine Schritte, Alltagsbilder, kein Fachwort ohne Erklärung.", "Basic operations, fractions, percentages, simple geometry. Small steps, everyday images, no jargon without explanation.") },
    { titel: t("Oberstufe", "Secondary school"), klassen: t("7.–9. Klasse · Sek I · Lehrplan 21", "Grades 7–9 · Lehrplan 21"),
      themen: t("Gleichungen, Terme, Prozent und Zins, Geometrie, Pythagoras, Funktionen. Genau der Stoff, der in der Sek I geprüft wird.", "Equations, terms, percent and interest, geometry, Pythagoras, functions. Exactly what is tested in lower secondary.") },
    { titel: t("Gymnasium", "Gymnasium"), klassen: t("bis zur Matura", "up to the Matura"),
      themen: t("Funktionen, Analysis, Vektoren, Stochastik. Präzise Fachsprache, zügigere Schritte – die Hilfe-Leiter gilt trotzdem.", "Functions, calculus, vectors, probability. Precise terminology, faster steps – the help ladder still applies.") },
  ];

  const PAKETE = [
    { name: t("Schnupper", "Taster"), tokens: 200, chf: "2.–" },
    { name: "Starter", tokens: 900, chf: "9.–" },
    { name: "Power", tokens: 1900, chf: "19.–" },
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
    ...(abo ? [
      { q: t("Was kostet Kniff?", "What does Kniff cost?"),
        a: t(`Die ersten ${probe} Aufgaben sind geschenkt – ohne Zahlungsangaben. Danach kostet ${plusName} CHF ${monat} im Monat oder ${jahr}.– im Jahr pro Kind, mit so vielen Aufgaben, wie dein Kind üben will. Jederzeit kündbar, das Abo läuft dann bis zum Ende der bezahlten Zeit.`,
             `The first ${probe} tasks are on us – no payment details. After that ${plusName} costs CHF ${monat} a month or ${jahr}.– a year per child, with as many tasks as your child wants to practise. Cancel anytime; the subscription then runs until the end of the paid period.`) },
      { q: t("Braucht mein Kind eine Kreditkarte?", "Does my child need a credit card?"),
        a: t(`Nein. Die Probe braucht keine Zahlungsangaben. ${plusName} schliessen Eltern über eine sichere Stripe-Seite ab, mit Karte oder TWINT – direkt aus der Elternansicht für ihr Kind.`,
             `No. The trial needs no payment details. Parents subscribe to ${plusName} through a secure Stripe page with a card or TWINT – straight from the parent view for their child.`) },
    ] : [
      { q: t("Was ist ein Token, und wie viele brauche ich?", "What is a token and how many do I need?"),
        a: t("Ein Token ist ein Rappen. Jede Antwort von Kniff kostet je nach Aufgabe ein bis vier Tokens, eine Foto-Erkennung etwa zwei. Mit den 50 Gratis-Tokens im Monat kommst du auf rund 20 bis 40 Antworten. Tokens laufen nie ab.", "A token is one Swiss centime (Rappen). Each answer from Kniff costs one to four tokens depending on the task, a photo recognition about two. The 50 free tokens a month give you roughly 20 to 40 answers. Tokens never expire.") },
      { q: t("Braucht mein Kind eine Kreditkarte?", "Does my child need a credit card?"),
        a: t("Nein. Das Gratis-Konto braucht keine Zahlungsangaben. Tokens kaufen können Eltern über eine sichere Stripe-Seite mit Karte oder TWINT – ohne Abo, ohne automatische Verlängerung.", "No. The free account needs no payment details. Parents can buy tokens through a secure Stripe page with a card or TWINT – no subscription, no automatic renewal.") },
    ]),
    { q: t("Kann Kniff sich irren?", "Can Kniff be wrong?"),
      a: t("Ja, wie jede KI. Deshalb rechnet Kniff jede Antwort im Hintergrund mit einem Mathe-Programm nach und zeigt Korrekturen offen an. Stimmt trotzdem etwas nicht, meldest du es mit einem Klick direkt aus dem Chat – wir lesen jede Meldung.", "Yes, like any AI. That's why Kniff re-checks every answer in the background with a maths engine and shows corrections openly. If something is still wrong, you report it with one click straight from the chat – we read every report.") },
    { q: t("Gibt es Kniff für Schulen?", "Is there Kniff for schools?"),
      a: t("Ja, es gibt einen Schul-Plan mit unbegrenzten Aufgaben für ganze Klassen. Schreib uns an die Adresse im Impressum.", "Yes, there is a school plan with unlimited tasks for whole classes. Write to us at the address in the legal notice.") },
  ];

  return (
    <div style={{ minHeight: "100vh", background: "#fff", overflowX: "hidden" }}>
      <nav style={{ display: "flex", alignItems: "center", gap: 24, padding: "20px 40px", maxWidth: 1180, margin: "0 auto" }} className="landing-section">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ width: 26, height: 26, borderRadius: 8, background: "#6366f1" }} />
          <span style={{ fontWeight: 800, fontSize: 19, color: INDIGO, letterSpacing: "-.02em" }}>Kniff</span>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 14 }}>
          <a href="#so" className="landing-navlink" style={{ fontSize: 14, fontWeight: 600, color: TEXT_3 }}>{t("So funktioniert's", "How it works")}</a>
          <a href="#preise" className="landing-navlink" style={{ fontSize: 14, fontWeight: 600, color: TEXT_3 }}>{t("Preise", "Pricing")}</a>
          <a href="#eltern" className="landing-navlink" style={{ fontSize: 14, fontWeight: 600, color: TEXT_3 }}>{t("Für Eltern", "For parents")}</a>
          <span>
            <button onClick={() => setLang("de")} style={langBtn("de")}>DE</button>
            <span style={{ color: "#d2d4dd", fontSize: 13 }}>|</span>
            <button onClick={() => setLang("en")} style={langBtn("en")}>EN</button>
          </span>
          <Link to="/login" style={{ fontSize: 14, fontWeight: 600, border: "1px solid #d2d4dd", borderRadius: 11, padding: "9px 18px" }}>{t("Anmelden", "Sign in")}</Link>
        </div>
      </nav>

      {/* ---- Hero ---- */}
      <div style={{ position: "relative", maxWidth: 1180, margin: "0 auto", padding: "28px 40px 56px", display: "grid", gridTemplateColumns: "1.05fr .95fr", gap: 52, alignItems: "center" }} className="landing-hero landing-section">
        <div style={{ position: "absolute", inset: 0, background: "radial-gradient(1000px 480px at 78% -10%, #eef0fe, transparent 70%)", pointerEvents: "none" }} />
        <div style={{ position: "relative", zIndex: 1 }}>
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
              {t("Kostenlos loslegen", "Start for free")}
            </button>
            <a href="#so" className="btn-ghost" style={{ fontSize: 15, padding: "14px 20px", borderRadius: 13, display: "inline-block" }}>{t("So funktioniert's ↓", "How it works ↓")}</a>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 18 }}>
            {abo ? (
              <>
                <Badge>{t(`${probe} Aufgaben gratis probieren`, `Try ${probe} tasks for free`)}</Badge>
                <Badge>{t("Keine Kreditkarte zum Start, jederzeit kündbar", "No credit card to start, cancel anytime")}</Badge>
              </>
            ) : (
              <>
                <Badge>{t("50 Gratis-Tokens jeden Monat", "50 free tokens every month")}</Badge>
                <Badge>{t("Kein Abo, keine Kreditkarte nötig", "No subscription, no credit card needed")}</Badge>
              </>
            )}
            <Badge>{t("Kein Klarname nötig", "No real name needed")}</Badge>
          </div>
        </div>

        {/* Chat-Vorschau mit Hilfe-Leiter */}
        <div style={{ position: "relative", zIndex: 1 }}>
          <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 22, boxShadow: "0 2px 6px rgba(40,40,90,.06),0 30px 60px rgba(40,40,90,.16)", overflow: "hidden" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "15px 18px", borderBottom: "1px solid #eef0f3" }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700 }}>{t("Lineare Gleichungen", "Linear equations")}</div>
                <div style={{ fontSize: 11.5, color: TEXT_4 }}>{t("Hausaufgabe · fotografiert", "Homework · photographed")}</div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 9, background: "#eef0fe", borderRadius: 999, padding: "6px 12px" }}>
                <span style={{ fontSize: 10.5, fontWeight: 700, color: INDIGO }}>{t("HILFE", "HELP")}</span>
                <span style={{ display: "flex", gap: 4 }}><Dot filled /><Dot filled /><Dot /><Dot /></span>
              </div>
            </div>
            <div style={{ background: "#f6f7fb", padding: 20, display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ alignSelf: "flex-start", background: "#fff", border: "1px solid #e7e8ee", borderRadius: 16, borderBottomLeftRadius: 5, boxShadow: "0 6px 16px rgba(40,40,90,.06)", padding: "11px 15px", fontSize: 13.5 }}>
                {t("Löse nach x auf:", "Solve for x:")}{" "}
                <span style={{ fontFamily: "Georgia,serif", fontStyle: "italic", fontSize: 18, display: "inline-block", marginTop: 5 }}>3x + 5 = 20</span>
              </div>
              <div style={{ alignSelf: "flex-end", background: "#6366f1", color: "#fff", borderRadius: 16, borderBottomRightRadius: 5, padding: "10px 15px", fontSize: 13.5, maxWidth: "84%" }}>
                {t("ich weiss nöd wie afange", "i don't know how to start")}
              </div>
              <div style={{ alignSelf: "flex-start", background: "#fff", border: "1px solid #e7e8ee", borderRadius: 16, borderBottomLeftRadius: 5, boxShadow: "0 6px 16px rgba(40,40,90,.06)", padding: "11px 15px", fontSize: 13.5 }}>
                {lang === "en"
                  ? <>No stress 🙂 Look at the left side: what is standing in the way next to the <b>3x</b>?</>
                  : <>Kein Stress 🙂 Schau auf die linke Seite: Was steht da neben dem <b>3x</b> im Weg?</>}
              </div>
              <div style={{ alignSelf: "flex-end", background: "#6366f1", color: "#fff", borderRadius: 16, borderBottomRightRadius: 5, padding: "10px 15px", fontSize: 13.5, maxWidth: "84%" }}>
                {t("die +5? also −5 auf beiden seiten → 3x = 15", "the +5? so −5 on both sides → 3x = 15")}
              </div>
              <div style={{ alignSelf: "flex-start", background: "#fff", border: "1px solid #cde7d6", borderRadius: 16, borderBottomLeftRadius: 5, boxShadow: "0 6px 16px rgba(40,40,90,.06)", padding: "11px 15px", fontSize: 13.5 }}>
                {lang === "en"
                  ? <><span style={{ color: "#1a7f3c", fontWeight: 700 }}>✓ Checked.</span> Strong – the minus on both sides worked. Now the <b>x</b> is still stuck to the 3 – what do you do with that?</>
                  : <><span style={{ color: "#1a7f3c", fontWeight: 700 }}>✓ Nachgerechnet.</span> Stark, das Minus auf beiden Seiten hat gesessen. Jetzt klebt das <b>x</b> noch an der 3 – was machst du damit?</>}
              </div>
            </div>
          </div>
          <div style={{ fontSize: 12.5, color: TEXT_4, textAlign: "center", marginTop: 12 }}>
            {t("Hilfe-Stufe 2 von 4 – der Lösungsweg kommt erst nach zwei eigenen Versuchen.", "Help level 2 of 4 – the full solution only comes after two attempts of your own.")}
          </div>
        </div>
      </div>

      {/* ---- So funktioniert's ---- */}
      <Section tinted id="so">
        <Eyebrow>{t("So funktioniert's", "How it works")}</Eyebrow>
        <H2>{t("Drei Schritte, und die Lösung ist deine.", "Three steps, and the solution is yours.")}</H2>
        <Lead>{t("Kniff arbeitet wie eine gute Nachhilfe-Person: Es schaut, was du schon hast, und gibt genau so viel Hilfe, wie du gerade brauchst – nicht mehr.", "Kniff works like a good tutor: it looks at what you already have and gives exactly as much help as you need right now – no more.")}</Lead>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }} className="landing-grid-3">
          {SCHRITTE.map((s, i) => (
            <div key={s.titel} style={card}>
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
            <div key={s.n} style={{ ...card, borderTop: `4px solid ${s.n === 4 ? "#1a7f3c" : INDIGO}` }}>
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

      {/* ---- Für wen ---- */}
      <Section tinted>
        <Eyebrow>{t("Für wen", "Who it's for")}</Eyebrow>
        <H2>{t("Von der 4. Klasse bis zur Matura.", "From grade 4 to the Matura.")}</H2>
        <Lead>{t("Du stellst beim Anmelden deine Stufe ein. Kniff passt Sprache, Schrittgrösse und Beispiele daran an – Sackgeld und Pizza in der Mittelstufe, Fachsprache am Gymi.", "You set your level when you sign up. Kniff adapts language, step size and examples – pocket money and pizza in middle school, proper terminology at the Gymnasium.")}</Lead>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }} className="landing-grid-3">
          {STUFEN_KARTEN.map((k) => (
            <div key={k.titel} style={card}>
              <div style={{ fontSize: 12, fontWeight: 700, color: INDIGO, letterSpacing: ".04em", marginBottom: 4 }}>{k.klassen}</div>
              <div style={{ fontSize: 19, fontWeight: 800, letterSpacing: "-.01em", marginBottom: 8 }}>{k.titel}</div>
              <div style={{ fontSize: 14.5, lineHeight: 1.55, color: TEXT_2 }}>{k.themen}</div>
            </div>
          ))}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 18, marginTop: 20 }}>
          <Badge>{t("Lehrplan 21", "Lehrplan 21 (Swiss curriculum)")}</Badge>
          <Badge>{t("Versteht Schweizerdeutsch", "Understands Swiss German")}</Badge>
          <Badge>{t("Deutsch oder Englisch", "German or English")}</Badge>
          <Badge>{t("Rechnet in Franken und Rappen", "Calculates in francs and centimes")}</Badge>
        </div>
      </Section>

      {/* ---- Preise ---- */}
      <Section id="preise">
        {abo ? (
          <>
        <Eyebrow>{t("Was es kostet", "What it costs")}</Eyebrow>
        <H2>{t("Gratis probieren. Dann so viel üben, wie du willst.", "Try it for free. Then practise as much as you like.")}</H2>
        <Lead>{t(`Die ersten ${probe} Aufgaben sind geschenkt. Danach kostet ${plusName} weniger als eine Nachhilfestunde im Monat – pro Kind, jederzeit kündbar.`,
                 `The first ${probe} tasks are on us. After that ${plusName} costs less than one tutoring lesson a month – per child, cancel anytime.`)}</Lead>
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
            <div style={{ fontSize: 12, fontWeight: 700, color: "#c9ccf6", letterSpacing: ".06em", marginBottom: 10 }}>{plusName.toUpperCase()} · {t("PRO KIND", "PER CHILD")}</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 10, marginBottom: 14 }} className="landing-grid-3-tight">
              <div style={{ border: "1px solid #3a3d49", borderRadius: 12, padding: "12px 12px", textAlign: "center" }}>
                <div style={{ fontSize: 12.5, fontWeight: 700, color: "#c5c9d2" }}>{t("Monatlich", "Monthly")}</div>
                <div style={{ fontSize: 22, fontWeight: 900, letterSpacing: "-.02em", margin: "4px 0 2px", fontVariantNumeric: "tabular-nums" }}>CHF {monat}</div>
                <div style={{ fontSize: 12.5, color: TEXT_4 }}>{t("im Monat", "per month")}</div>
              </div>
              <div style={{ border: "1px solid #3a3d49", borderRadius: 12, padding: "12px 12px", textAlign: "center" }}>
                <div style={{ fontSize: 12.5, fontWeight: 700, color: "#c5c9d2" }}>{t("Jährlich", "Yearly")}</div>
                <div style={{ fontSize: 22, fontWeight: 900, letterSpacing: "-.02em", margin: "4px 0 2px", fontVariantNumeric: "tabular-nums" }}>CHF {jahr}.–</div>
                <div style={{ fontSize: 12.5, color: TEXT_4 }}>{t(`${jahrProMonat} im Monat – zwei Monate geschenkt`, `${jahrProMonat} a month – two months free`)}</div>
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, color: "#e5e7ef" }}>
              <Badge color="#e5e7ef">{t("So viel üben, wie dein Kind will – Foto, Stift, Aufgabensammlung, Probeprüfungen", "Practise as much as your child wants – photo, pen, task collection, mock exams")}</Badge>
              <Badge color="#e5e7ef">{t("Jederzeit kündbar, läuft bis zum Ende der bezahlten Zeit", "Cancel anytime, runs until the end of the paid period")}</Badge>
              <Badge color="#e5e7ef">{t("Eltern schliessen ab: Stripe, Karte oder TWINT", "Parents subscribe: Stripe, card or TWINT")}</Badge>
              <Badge color="#e5e7ef">{t("Schulen: Klassen-Plan mit unbegrenzten Aufgaben auf Anfrage", "Schools: class plan with unlimited tasks on request")}</Badge>
            </div>
          </div>
        </div>
          </>
        ) : (
          <>
        <Eyebrow>{t("Was es kostet", "What it costs")}</Eyebrow>
        <H2>{t("Gratis anfangen. Nur zahlen, was du brauchst.", "Start for free. Pay only for what you use.")}</H2>
        <Lead>{t("Kein Abo, keine Mindestlaufzeit. Ein Token ist ein Rappen, und jede Antwort von Kniff kostet je nach Aufgabe ein bis vier Tokens. Tokens laufen nie ab.", "No subscription, no minimum term. A token is one Rappen, and each answer from Kniff costs one to four tokens depending on the task. Tokens never expire.")}</Lead>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1.4fr", gap: 16, alignItems: "stretch" }} className="landing-hero">
          <div style={{ ...card, background: "#f8f8ff", border: "1px solid #e0e2fb" }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: INDIGO, letterSpacing: ".06em", marginBottom: 6 }}>{t("GRATIS", "FREE")}</div>
            <div style={{ fontSize: 34, fontWeight: 900, letterSpacing: "-.03em", lineHeight: 1 }}>CHF 0.–</div>
            <div style={{ fontSize: 14, color: TEXT_3, margin: "6px 0 14px" }}>{t("jeden Monat, ohne Zahlungsangaben", "every month, no payment details")}</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <Badge>{t("50 Tokens pro Monat – rund 20 bis 40 Antworten", "50 tokens per month – roughly 20 to 40 answers")}</Badge>
              <Badge>{t("Alle Funktionen: Foto, Stift, Aufgabensammlung, Elternansicht", "All features: photo, pen, task collection, parent view")}</Badge>
              <Badge>{t("Kein Klarname, keine Kreditkarte", "No real name, no credit card")}</Badge>
            </div>
            <button onClick={() => nav("/login")} className="btn-primary" style={{ marginTop: 18, fontSize: 14, padding: "12px 20px", borderRadius: 11 }}>{t("Gratis-Konto erstellen", "Create a free account")}</button>
          </div>
          <div style={card}>
            <div style={{ fontSize: 12, fontWeight: 700, color: TEXT_4, letterSpacing: ".06em", marginBottom: 10 }}>{t("MEHR ÜBEN? TOKENS NACHLADEN", "PRACTISE MORE? TOP UP TOKENS")}</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginBottom: 14 }} className="landing-grid-3-tight">
              {PAKETE.map((p) => (
                <div key={p.name} style={{ border: "1px solid #e7e8ee", borderRadius: 12, padding: "12px 12px", textAlign: "center" }}>
                  <div style={{ fontSize: 12.5, fontWeight: 700, color: TEXT_3 }}>{p.name}</div>
                  <div style={{ fontSize: 22, fontWeight: 900, letterSpacing: "-.02em", margin: "4px 0 2px", fontVariantNumeric: "tabular-nums" }}>CHF {p.chf}</div>
                  <div style={{ fontSize: 12.5, color: TEXT_4, fontVariantNumeric: "tabular-nums" }}>{p.tokens} Tokens</div>
                </div>
              ))}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <Badge>{t("Einmalig kaufen – nichts verlängert sich von selbst", "Buy once – nothing renews by itself")}</Badge>
              <Badge>{t("Bezahlung über Stripe: Karte oder TWINT", "Payment via Stripe: card or TWINT")}</Badge>
              <Badge>{t("Schulen: Klassen-Plan mit unbegrenzten Aufgaben auf Anfrage", "Schools: class plan with unlimited tasks on request")}</Badge>
            </div>
          </div>
        </div>
          </>
        )}
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
            <Lead>{t("Ihr Kind gibt Ihnen aus der App einen Einladungscode. Damit erstellen Sie ein eigenes Eltern-Konto und sehen jede Woche: welche Aufgaben bearbeitet wurden, wo viel Hilfe nötig war, wie selbständig gerechnet wurde. Die Gespräche selbst bleiben beim Kind.", "Your child gives you an invitation code from the app. With it you create your own parent account and see every week: which tasks were worked on, where a lot of help was needed, how independently your child calculated. The conversations themselves stay with the child.")}</Lead>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Badge>{t("Eigenes Eltern-Konto, verknüpft per Code vom Kind", "Your own parent account, linked via a code from your child")}</Badge>
              <Badge>{t("Wochen-Überblick mit den bearbeiteten Aufgaben", "Weekly overview with the tasks worked on")}</Badge>
              <Badge>{t("Freigabe liegt beim Kind – jederzeit widerrufbar", "Sharing is controlled by the child – revocable anytime")}</Badge>
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
            <div key={s.titel} style={card}>
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
          <div style={{ fontSize: 15, color: "#c5c9d2", marginBottom: 18 }}>{abo ? t(`Konto in einer Minute, ${probe} Aufgaben geschenkt, keine Kreditkarte.`, `Account in a minute, ${probe} tasks on us, no credit card.`) : t("Konto in einer Minute, 50 Tokens geschenkt, keine Kreditkarte.", "Account in a minute, 50 tokens on us, no credit card.")}</div>
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
