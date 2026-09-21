import { Link, useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { useLang } from "../lib/i18n.jsx";

// Impressum & Datenschutzerklärung – öffentlich erreichbar, im Design-Look.
// Zweisprachig: grosse Prosa-Blöcke werden je nach lang komplett DE oder EN gerendert.

function Shell({ title, children }) {
  const { t } = useLang();
  return (
    <div style={{ minHeight: "100vh", background: "#fbfbfd" }}>
      <nav style={{ display: "flex", alignItems: "center", gap: 10, padding: "20px 40px", maxWidth: 860, margin: "0 auto" }}>
        <Link to="/" style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ width: 26, height: 26, borderRadius: 8, background: "#6366f1" }} />
          <span style={{ fontWeight: 800, fontSize: 19, color: "#4f46e5", letterSpacing: "-.02em" }}>Kniff</span>
        </Link>
        <Link to="/" style={{ marginLeft: "auto", fontSize: 13, fontWeight: 600, color: "#4f46e5" }}>{t("← zur Startseite", "← back to home")}</Link>
      </nav>
      <div style={{ maxWidth: 760, margin: "0 auto", padding: "16px 40px 80px" }}>
        <h1 style={{ fontSize: 32, fontWeight: 900, letterSpacing: "-.03em", marginBottom: 24 }}>{title}</h1>
        <div style={{ background: "#fff", border: "1px solid #e7e8ee", borderRadius: 18, padding: "28px 32px", fontSize: 14.5, lineHeight: 1.65, color: "#1a1c22" }}>
          {children}
        </div>
      </div>
    </div>
  );
}

const H = ({ children }) => <h2 style={{ fontSize: 17, fontWeight: 800, margin: "26px 0 8px", letterSpacing: "-.01em" }}>{children}</h2>;
const P = ({ children }) => <p style={{ margin: "0 0 12px", color: "#3a3d46" }}>{children}</p>;
// Dezenter Hinweis in der englischen Fassung (courtesy translation)
const Note = ({ children }) => <p style={{ margin: "0 0 16px", color: "#8a8f9a", fontStyle: "italic", fontSize: 13.5 }}>{children}</p>;

const Mail = () => <a href="mailto:mahmmouds62@gmail.com" style={{ color: "#4f46e5" }}>mahmmouds62@gmail.com</a>;

export function Impressum() {
  const { t, lang } = useLang();
  return (
    <Shell title={t("Impressum", "Legal Notice")}>
      {lang === "en" ? (
        <>
          <H>Operator</H>
          <P>
            Mahmmoud Said<br />
            St. Georgen-Strasse 84<br />
            9000 St.Gallen, Switzerland
          </P>
          <H>Contact</H>
          <P>
            E-mail: <Mail />
          </P>
          <H>Responsible for the content</H>
          <P>Mahmmoud Said</P>
          <H>Disclaimer</H>
          <P>
            Kniff is a learning tool and does not replace classroom teaching. Despite
            careful review, we accept no liability for the factual accuracy of individual
            AI-generated hints. The operators of external links are solely responsible for
            their content.
          </P>
        </>
      ) : (
        <>
          <H>Betreiber</H>
          <P>
            Mahmmoud Said<br />
            St. Georgen-Strasse 84<br />
            9000 St.Gallen, Schweiz
          </P>
          <H>Kontakt</H>
          <P>
            E-Mail: <Mail />
          </P>
          <H>Verantwortlich für den Inhalt</H>
          <P>Mahmmoud Said</P>
          <H>Haftungsausschluss</H>
          <P>
            Kniff ist ein Lernwerkzeug und ersetzt keinen Unterricht. Trotz sorgfältiger
            Prüfung übernehmen wir keine Gewähr für die fachliche Richtigkeit einzelner
            KI-generierter Hinweise. Für Inhalte externer Links sind ausschliesslich deren
            Betreiber verantwortlich.
          </P>
        </>
      )}
    </Shell>
  );
}

export function Datenschutz() {
  const { t, lang } = useLang();
  return (
    <Shell title={t("Datenschutzerklärung", "Privacy Policy")}>
      {lang === "en" ? (
        <>
          <Note>This is a courtesy translation. The German version is legally binding.</Note>
          <P>
            This privacy policy explains which personal data Kniff processes – in
            accordance with the Swiss Federal Act on Data Protection (revFADP). Last
            updated: September 2026.
          </P>

          <H>1. Controller</H>
          <P>
            Mahmmoud Said, St. Georgen-Strasse 84, 9000 St.Gallen, Switzerland<br />
            E-mail: <Mail />
          </P>

          <H>2. What data we process</H>
          <P>
            <b>Account:</b> e-mail address, a password (stored only as a cryptographic
            hash) and a freely chosen display name (deliberately, no real name is
            required), optionally the grade level.<br />
            <b>Learning content:</b> tasks that are typed in, photographed or written
            with the pen, and the chat history with the tutor.<br />
            <b>Learning progress:</b> coarse aggregates computed from this (tasks
            solved, independence rate, active days, topic trends).<br />
            <b>Purchases and subscription:</b> amount and time of a purchase, the term
            of a subscription and the customer and subscription identifiers assigned by
            the payment provider (no payment data, see section 7).
          </P>

          <H>3. Purpose</H>
          <P>
            Exclusively for operating the learning tutor: signing in with e-mail and
            password (via a one-time e-mail link if the password is forgotten),
            pedagogical hints along the hint ladder, the progress display and – only
            with explicit consent – the aggregated parent view.
          </P>

          <H>4. Privacy by design: what parents see (and what they do not)</H>
          <P>
            Linked parents only see aggregated weekly progress, never chat transcripts.
            Chat messages are technically not retrievable by parents; the aggregates are
            stored in a separate database table. Sharing can be revoked at any time in
            the settings.
          </P>

          <H>5. AI processing (data processors)</H>
          <P>
            To generate the tutor's responses, the task text and chat history are
            transmitted to the Anthropic API (Anthropic PBC, USA). Uploaded task photos
            and pen input are also transmitted to Anthropic to recognise what was
            written. Under Anthropic's API terms, this data is not used to train AI
            models.
          </P>

          <H>6. Hosting and storage location</H>
          <P>
            The application runs on Vercel Inc. (USA); the database with account and
            learning data is hosted by Supabase (data centre in Frankfurt, EU). Part of
            the processing therefore takes place in the USA. The privacy policies of
            these providers additionally apply.
          </P>

          <H>7. Payment processing</H>
          <P>
            Purchases and subscriptions are processed via Stripe Payments Europe Ltd.
            Card or TWINT data are processed directly by Stripe and never reach our
            servers; we only store the amount, the time of the purchase, the term of a
            subscription and the identifiers assigned by Stripe. Minors need the consent
            of their legal guardians for purchases.
          </P>

          <H>8. Retention &amp; deletion</H>
          <P>
            Account and learning data remain stored for as long as the account exists.
            You can delete your account together with all associated data yourself at
            any time (Settings → Privacy → "Delete account") – or by request to the
            address above. Payment records remain with the payment provider Stripe for
            accounting reasons. E-mail login links (forgotten password) are valid for 30
            minutes and can be used once.
          </P>

          <H>9. Your rights</H>
          <P>
            Access, rectification, deletion and data portability – a simple e-mail to
            the controller is sufficient. For minors, these rights may be exercised by
            their legal guardians.
          </P>

          <H>10. No advertising, no tracking</H>
          <P>
            Kniff does not use advertising or tracking cookies. Only a
            technically necessary login token is stored in the browser.
          </P>
        </>
      ) : (
        <>
          <P>
            Diese Datenschutzerklärung informiert darüber, welche Personendaten Kniff
            bearbeitet – gemäss dem Schweizer Datenschutzgesetz (revDSG). Stand: September 2026.
          </P>

          <H>1. Verantwortliche Stelle</H>
          <P>
            Mahmmoud Said, St. Georgen-Strasse 84, 9000 St.Gallen, Schweiz<br />
            E-Mail: <Mail />
          </P>

          <H>2. Welche Daten wir bearbeiten</H>
          <P>
            <b>Konto:</b> E-Mail-Adresse, ein Passwort (nur als kryptografischer Hash
            gespeichert) und ein frei wählbarer Anzeigename (bewusst kein Klarname nötig),
            optional die Klassenstufe.<br />
            <b>Lerninhalte:</b> eingegebene, fotografierte oder mit dem Stift geschriebene
            Aufgaben und der Chat-Verlauf mit dem Tutor.<br />
            <b>Lernfortschritt:</b> daraus berechnete grobe Aggregate (gelöste Aufgaben,
            Selbständigkeits-Quote, aktive Tage, Themen-Trends).<br />
            <b>Käufe und Abo:</b> Betrag und Zeitpunkt eines Kaufs, die Laufzeit eines
            Abos sowie die vom Zahlungsanbieter vergebenen Kunden- und Abo-Kennungen
            (keine Zahlungsdaten, siehe Ziffer 7).
          </P>

          <H>3. Wofür (Zweck)</H>
          <P>
            Ausschliesslich für den Betrieb des Lern-Tutors: Anmeldung mit E-Mail und
            Passwort (bei vergessenem Passwort per einmaligem E-Mail-Link), pädagogische
            Hinweise entlang der Hinweis-Leiter, Fortschrittsanzeige und – nur mit
            ausdrücklicher Freigabe – die aggregierte Elternansicht.
          </P>

          <H>4. Privacy by Design: Was Eltern sehen (und was nicht)</H>
          <P>
            Verknüpfte Eltern sehen ausschliesslich grobe Wochen-Aggregate. Chat-Nachrichten
            sind für Eltern technisch nicht abrufbar; die Aggregate liegen in einer separaten
            Datenbank-Tabelle. Die Freigabe kann in den Einstellungen jederzeit widerrufen werden.
          </P>

          <H>5. KI-Verarbeitung (Auftragsbearbeiter)</H>
          <P>
            Zur Erzeugung der Tutor-Antworten werden Aufgabentext und Chat-Verlauf an die
            Anthropic API (Anthropic PBC, USA) übermittelt. Auch hochgeladene Aufgabenfotos
            und Stift-Eingaben werden zur Erkennung des Geschriebenen an Anthropic
            übermittelt. Gemäss den API-Bedingungen von Anthropic werden diese Daten nicht
            zum Training von KI-Modellen verwendet.
          </P>

          <H>6. Hosting und Speicherort</H>
          <P>
            Die Anwendung läuft bei Vercel Inc. (USA); die Datenbank mit Konto- und
            Lerndaten liegt bei Supabase (Rechenzentrum in Frankfurt, EU). Ein Teil der
            Verarbeitung findet damit in den USA statt. Es gelten zusätzlich die
            Datenschutzbestimmungen dieser Anbieter.
          </P>

          <H>7. Zahlungsabwicklung</H>
          <P>
            Käufe und Abos werden über Stripe Payments Europe Ltd. abgewickelt. Karten-
            oder TWINT-Daten werden direkt von Stripe verarbeitet und erreichen unsere
            Server nie; wir speichern nur Betrag, Zeitpunkt, Laufzeit eines Abos und die
            von Stripe vergebenen Kennungen.
            Minderjährige benötigen für Käufe das Einverständnis ihrer
            Erziehungsberechtigten.
          </P>

          <H>8. Aufbewahrung &amp; Löschung</H>
          <P>
            Konto- und Lerndaten bleiben gespeichert, solange das Konto besteht. Du kannst
            dein Konto samt aller zugehörigen Daten jederzeit selbst löschen (Einstellungen
            → Privatsphäre → «Konto löschen») – oder per Anfrage an die oben genannte
            Adresse. Zahlungsbelege verbleiben aus buchhalterischen Gründen beim
            Zahlungsanbieter Stripe. E-Mail-Login-Links (Passwort vergessen) sind 30
            Minuten gültig und einmalig verwendbar.
          </P>

          <H>9. Deine Rechte</H>
          <P>
            Auskunft, Berichtigung, Löschung und Datenherausgabe – Anfrage genügt per E-Mail
            an die verantwortliche Stelle. Bei Minderjährigen können die
            Erziehungsberechtigten diese Rechte ausüben.
          </P>

          <H>10. Keine Werbung, kein Tracking</H>
          <P>
            Kniff setzt keine Werbe- oder Tracking-Cookies ein. Es wird nur ein
            technisch notwendiges Login-Token im Browser gespeichert.
          </P>
        </>
      )}
    </Shell>
  );
}

export function Agb() {
  const { t, lang } = useLang();
  // Welches Modell gilt, sagt der Server (ABO_ENABLED): mit Schalter Kniff
  // Plus, ohne ihn die Token-Pakete. Bis die Auskunft da ist, gilt Kniff Plus.
  const [preise, setPreise] = useState(null);
  useEffect(() => {
    api.get("/api/pay/preise").then(setPreise).catch(() => setPreise(null));
  }, []);
  const abo = preise ? preise.abo_enabled : true;
  const plusName = preise?.plus_name || "Kniff Plus";
  const probe = preise?.trial_tasks ?? 10;
  const monat = ((preise?.monat_rappen ?? 990) / 100).toFixed(2);
  const jahr = Math.round((preise?.jahr_rappen ?? 8900) / 100);
  return (
    <Shell title={t("AGB", "Terms of Use")}>
      {lang === "en" ? (
        <>
          <Note>This is a courtesy translation. The German version is legally binding.</Note>
          <P>
            General terms and conditions (contract of use) for Kniff, operated by
            Mahmmoud Said, St. Georgen-Strasse 84, 9000 St.Gallen, Switzerland
            (<Mail />).
            Last updated: September 2026.
          </P>

          {abo ? (
            <>
              <H>1. Service</H>
              <P>
                Kniff is an AI-powered maths tutor for middle school, secondary school
                and high school (Gymnasium). Every account can practise its first {probe}{" "}
                tasks free of charge (trial, once per account, no payment details).
                After that, {plusName} is required: one subscription per child that
                allows practising as much as the child wants – photo, pen, task
                collection and mock exams included. Fair use: with exceptionally heavy
                use far beyond everyday learning, the account may pause until the start
                of the next month. Token balances bought earlier remain usable after the
                trial and are deducted as before.
              </P>

              <H>2. Prices</H>
              <P>
                {plusName}: CHF {monat} per month or CHF {jahr}.– per year, per child.
                All prices in Swiss francs; no VAT is charged. School and class plans on
                request. Price changes are announced by e-mail at least 30 days in
                advance and apply from the next renewal; until then the subscription can
                be cancelled.
              </P>

              <H>3. Payment and term</H>
              <P>
                Payment is processed via Stripe (card or TWINT). The subscription renews
                automatically for the chosen term (month or year) until it is cancelled.
                It can be cancelled at any time in the app (Settings → Subscription) with
                effect from the end of the paid term; until then {plusName} remains
                active. Parents can take out the subscription for a linked child; the
                invoice goes to the parent's e-mail address.
              </P>
            </>
          ) : (
            <>
          <H>1. Service</H>
          <P>
            Kniff is an AI-powered maths tutor for middle school, secondary school
            and high school (Gymnasium). Every account receives 50 free tokens per
            calendar month. In addition, one-time token packages can be purchased. 1
            token = 1 Swiss centime (Rappen) of AI computation: each tutor response
            deducts tokens according to its computational cost – a normal response
            usually costs 1 token, a response with photo analysis or complex geometry
            about 3–5 tokens. Handwriting/photo recognition when capturing a task is
            billed the same way. Tokens are not a subscription, do not renew
            automatically and do not expire.
          </P>

          <H>2. Prices</H>
          <P>
            Trial package: CHF 2.– (200 tokens) · Starter package: CHF 9.– (900 tokens) ·
            Power package: CHF 19.– (1900 tokens). All prices in Swiss francs, one-time.
          </P>

          <H>3. Payment</H>
          <P>
            Payment is processed via Stripe (card or TWINT). Tokens are credited to the
            account automatically after receipt of payment – usually within seconds.
          </P>
            </>
          )}

          <H>4. Minors</H>
          <P>
            Purchases by minors require the consent of their legal guardians. By
            purchasing, you confirm that this consent has been given.
          </P>

          <H>5. Refunds</H>
          {abo ? (
            <P>
              Within 14 days of the first subscription, the full amount is refunded on
              request by e-mail to the address above. After that, cancelling does not
              refund the remainder of the paid term; {plusName} simply stays active until
              the end of that term. Token balances bought earlier: unused tokens can be
              returned within 14 days of purchase (pro-rata refund); for tokens already
              used, the service has been provided.
            </P>
          ) : (
            <P>
              Unused tokens can be returned within 14 days of purchase by e-mail to the
              address above (pro-rata refund). For tokens already used, the service has
              been provided – no refund is given for those.
            </P>
          )}

          <H>6. Availability and warranty</H>
          <P>
            Kniff is a learning tool and does not replace classroom teaching.
            AI-generated hints may occasionally be incorrect; no warranty is given for
            them. Uninterrupted availability is aimed for but not guaranteed. In the
            event of longer outages, {abo ? "the subscription term is extended on request" : "affected tokens will be replaced on request"}.
          </P>

          <H>7. Account and misuse</H>
          <P>
            One account per person. In the event of misuse (e.g. automated requests,
            resale of access), the account may be blocked.
          </P>

          <H>8. Governing law</H>
          <P>
            Swiss law applies. The place of jurisdiction is St.Gallen; mandatory
            statutory places of jurisdiction remain reserved.
          </P>
        </>
      ) : (
        <>
          <P>
            Allgemeine Geschäftsbedingungen für die Nutzung von Kniff, betrieben von
            Mahmmoud Said, St. Georgen-Strasse 84, 9000 St.Gallen, Schweiz
            (<Mail />).
            Stand: September 2026.
          </P>

          {abo ? (
            <>
              <H>1. Leistung</H>
              <P>
                Kniff ist ein KI-gestützter Mathe-Lern-Tutor für Mittelstufe, Oberstufe
                und Gymnasium. Jedes Konto kann die ersten {probe} Aufgaben gratis üben
                (Probe, einmalig pro Konto, ohne Zahlungsangaben). Danach braucht es{" "}
                {plusName}: ein Abo pro Kind, mit dem so viel geübt werden kann, wie das
                Kind will – Foto, Stift, Aufgabensammlung und Probeprüfungen inbegriffen.
                Fair Use: Bei aussergewöhnlich hoher Nutzung weit über einem normalen
                Lernalltag kann das Konto bis zum Monatsanfang pausieren. Früher gekaufte
                Token-Guthaben bleiben nach der Probe nutzbar und werden wie bisher
                abgebucht.
              </P>

              <H>2. Preise</H>
              <P>
                {plusName}: CHF {monat} pro Monat oder CHF {jahr}.– pro Jahr, jeweils pro
                Kind. Alle Preise in Schweizer Franken; es wird keine Mehrwertsteuer
                erhoben. Schul- und Klassenpläne auf Anfrage. Preisänderungen werden
                mindestens 30 Tage im Voraus per E-Mail angekündigt und gelten ab der
                nächsten Verlängerung; bis dahin kann gekündigt werden.
              </P>

              <H>3. Zahlung und Laufzeit</H>
              <P>
                Die Zahlung erfolgt über Stripe (Karte oder TWINT). Das Abo verlängert
                sich automatisch um die gewählte Laufzeit (Monat oder Jahr), bis es
                gekündigt wird. Kündigen geht jederzeit in der App (Einstellungen → Abo)
                mit Wirkung auf das Ende der bezahlten Laufzeit; bis dahin bleibt{" "}
                {plusName} aktiv. Eltern können das Abo für ein verknüpftes Kind
                abschliessen; die Rechnung geht an die E-Mail-Adresse der Eltern.
              </P>
            </>
          ) : (
            <>
          <H>1. Leistung</H>
          <P>
            Kniff ist ein KI-gestützter Mathe-Lern-Tutor für Mittelstufe, Oberstufe
            und Gymnasium. Jedes
            Konto erhält 50 Gratis-Tokens pro Kalendermonat. Zusätzlich können einmalige
            Token-Pakete gekauft werden. 1 Token entspricht 1 Rappen KI-Leistung: Jede
            Tutor-Antwort bucht Tokens entsprechend ihrem Rechenaufwand ab – eine normale
            Antwort kostet in der Regel 1 Token, eine Antwort mit Foto-Auswertung oder
            aufwändiger Geometrie ca. 3–5 Tokens. Auch die Handschrift-/Foto-Erkennung
            beim Erfassen einer Aufgabe wird so abgerechnet. Tokens sind kein Abo,
            verlängern sich nicht automatisch und laufen nicht ab.
          </P>

          <H>2. Preise</H>
          <P>
            Schnupper-Paket: CHF 2.– (200 Tokens) · Starter-Paket: CHF 9.– (900 Tokens) ·
            Power-Paket: CHF 19.– (1900 Tokens). Alle Preise in Schweizer Franken, einmalig.
          </P>

          <H>3. Zahlung</H>
          <P>
            Die Zahlung erfolgt über Stripe (Karte oder TWINT). Die Tokens werden nach
            Zahlungseingang automatisch dem Konto gutgeschrieben – in der Regel innert
            Sekunden.
          </P>
            </>
          )}

          <H>4. Minderjährige</H>
          <P>
            Für Käufe durch Minderjährige ist das Einverständnis der Erziehungsberechtigten
            erforderlich. Mit dem Kauf bestätigst du, dass dieses Einverständnis vorliegt.
          </P>

          <H>5. Rückerstattung</H>
          {abo ? (
            <P>
              Innert 14 Tagen nach dem ersten Abschluss erstatten wir auf Anfrage per
              E-Mail an die oben genannte Adresse den vollen Betrag. Danach wird bei einer
              Kündigung der Rest der bezahlten Laufzeit nicht erstattet; {plusName} bleibt
              einfach bis zum Ende dieser Laufzeit aktiv. Früher gekaufte Token-Guthaben:
              ungenutzte Tokens können innert 14 Tagen nach dem Kauf zurückgegeben werden
              (anteilige Rückerstattung); für verbrauchte Tokens ist die Leistung erbracht.
            </P>
          ) : (
            <P>
              Ungenutzte Tokens können innert 14 Tagen nach dem Kauf per E-Mail an die oben
              genannte Adresse zurückgegeben werden (anteilige Rückerstattung). Für bereits
              verbrauchte Tokens ist die Leistung erbracht – dafür gibt es keine Rückerstattung.
            </P>
          )}

          <H>6. Verfügbarkeit und Gewähr</H>
          <P>
            Kniff ist ein Lernwerkzeug und ersetzt keinen Unterricht. KI-generierte
            Hinweise können im Einzelfall fehlerhaft sein; dafür wird keine Gewähr
            übernommen. Eine ununterbrochene Verfügbarkeit wird angestrebt, aber nicht
            garantiert. Bei längeren Ausfällen {abo ? "wird die Abo-Laufzeit auf Anfrage verlängert" : "werden betroffene Tokens auf Anfrage ersetzt"}.
          </P>

          <H>7. Konto und Missbrauch</H>
          <P>
            Pro Person ein Konto. Bei Missbrauch (z.B. automatisierte Anfragen,
            Weiterverkauf von Zugängen) kann das Konto gesperrt werden.
          </P>

          <H>8. Anwendbares Recht</H>
          <P>
            Es gilt Schweizer Recht. Gerichtsstand ist St.Gallen, zwingende gesetzliche
            Gerichtsstände bleiben vorbehalten.
          </P>
        </>
      )}
    </Shell>
  );
}

export default function Rechtliches() {
  const { pathname } = useLocation();
  if (pathname.includes("agb")) return <Agb />;
  return pathname.includes("datenschutz") ? <Datenschutz /> : <Impressum />;
}
