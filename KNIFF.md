# Kniff – KI-Mathe-Tutor für Mittelstufe, Oberstufe & Gymnasium

> **Mathe verstehen. Nicht abschreiben.** Ein Tutor, der die Lösung nie direkt
> verrät, sondern über eine **Hinweis-Leiter** (4 Stufen) zum eigenen Denken führt.
> Für Mittelstufe (4.–6. Klasse), Oberstufe (Lehrplan 21) und Gymnasium bis zur
> Matura. Die App ist zweisprachig (Deutsch/Englisch): Browser-Sprache wird beim
> ersten Besuch erkannt, manuell umstellbar (Landing/Login/Einstellungen); der
> Tutor antwortet in der gewählten Sprache.

Live: **https://schrittweise-2-0.vercel.app** · Der visuelle Massstab ist
`design/referenz.html` (im Browser öffnen).

## Der Name

**Kniff** ist der clevere Handgriff, die Technik, die man beherrscht. «Den Kniff
raushaben» heisst, etwas selbst zu können – nicht, die Lösung serviert zu
bekommen. Der Name trägt das Produktversprechen also schon in sich. Dazu die
Wortfamilie: Aufgaben sind **knifflig** – die App gibt dir den **Kniff**.

**Markenstory.** Jeder kennt den Moment: Man sitzt vor einer Aufgabe und kommt
nicht weiter. Die einen schreiben ab – und lernen nichts. Die anderen haben
jemanden, der die richtige Frage stellt, einen kleinen Tipp gibt, geduldig
bleibt. Kniff ist dieser Jemand. Wer den Kniff einmal selbst gefunden hat,
vergisst ihn nicht mehr.

**Tonalität.** Gegenüber Schüler:innen wie ein älterer Bruder, der Mathe kann:
kumpelhaft, geduldig, nie belehrend, nie überwachend (steht so im
`SYSTEM_PROMPT`, `backend/app/services/tutor.py`). Gegenüber Eltern
seriös-kompetent, aber warm und klar – kein Bildungsjargon, keine KI-Buzzwords.

> **Noch auf den alten Namen:** die Live-Adresse (`schrittweise-2-0.vercel.app`),
> das Vercel-Projekt, die Backup-Dateinamen und die
> Absender-Domain in `smtp_from`. Das sind Infrastruktur-Bezeichner – sie zu
> ändern bricht Deploy und Backups und gehört in einen eigenen, bewussten
> Schritt (siehe unten «Umbenennen: was noch offen ist»).

## Prinzipien (nicht verhandelbar)

- **Nie die Lösung verraten.** Hinweis-Leiter: (1) aktivierende Frage, (2) kleiner
  Tipp, (3) Teilschritt vorgemacht, (4) volle Lösung – erst nach ≥ 2 echten
  eigenen Versuchen. Der System-Prompt erzwingt das (auch bei Betteln).
- **Privacy by Design.** Eltern sehen nur **Aggregate** (Selbständigkeit %,
  gelöste Aufgaben, aktive Tage, Themen-Trends) – nie Transkripte. Aggregate
  liegen in einer separaten Tabelle; aus der Eltern-Rolle gibt es technisch
  keinen Zugriff auf Nachrichten.
- **Themen sind manuelle Container** – keine automatische Klassifikation.
- **SymPy prüft Mathe, das LLM macht Pädagogik.** Jede Antwort wird deterministisch
  verifiziert; das Ergebnis geht als Kontext ans LLM.

## Tech-Stack

| Bereich | Wahl |
|---|---|
| Frontend | React + Vite, Formeln via **KaTeX**, deterministische Skizzen (SVG) |
| Backend | Python + **FastAPI** |
| Mathe | **SymPy** |
| KI | Anthropic API – `claude-haiku-4-5` (Standard), `claude-sonnet-5` (Foto/Geometrie), Prompt-Caching (System + Aufgaben-Bild) |
| Handschrift/Foto | **Claude Vision** (liest Stift-Eingabe und Fotos; ohne API-Key: einfacher lokaler Fallback) |
| DB | **Supabase Postgres** (lokal SQLite) via SQLAlchemy |
| Auth | **E-Mail + Passwort** (scrypt) + JWT; Mail-Link nur für «Passwort vergessen» |
| Zahlung | **Stripe Checkout** (Karte/TWINT), signierter Webhook |
| Deployment | **Vercel** über GitHub Actions (Push auf `main` → Test → Deploy → Smoke-Test) |

## 💰 Preismodell (nutzungsbasiert)

**1 Token = 1 Rappen verrechnete KI-Leistung.** Jede Tutor-Antwort bucht
`max(1, aufgerundet(echte Kosten × USD_CHF_RATE × BILLING_MARGIN))` Tokens ab –
eine normale Antwort ≈ 1 Token, eine Foto-/Geometrie-Antwort ≈ 3–5. Auch die
Handschrift-Erkennung wird so abgerechnet; die KI-Suche der Bibliothek ist
gratis (gedrosselt).

- **Gratis:** 50 Tokens pro Konto und Monat (`FREE_MONTHLY_TOKENS`).
- **Pakete:** Schnupper CHF 2 → 200 Tokens · Starter CHF 9 → 900 · Power
  CHF 19 → 1900 (definiert in `backend/app/routers/pay.py`).
- **Marge:** `BILLING_MARGIN=3.0` – Schüler zahlen das Dreifache der echten
  Anthropic-Kosten; du kannst nie draufzahlen.
- **Qualitäts-Option:** `ANTHROPIC_MODEL_DEFAULT=claude-sonnet-5` im
  `RUNTIME_ENV_JSON` hebt auch den Text-Chat aufs starke Modell (bis
  31.08.2026 Einführungspreis ≈ 2× Haiku; dank Caching kaum Mehrkosten).
  Jederzeit rückgängig – Wirkung unter Admin → Kosten vergleichen.
- Admin- und Schul-Konten sind unbegrenzt und gratis.

## 🔧 Admin-Bereich (nur Betreiber-Konto)

In der Sidebar sichtbar, sobald `users.is_admin = TRUE`:

- **📊 Kosten** – echte KI-Kosten (Ø/Min/Max pro Aufgabe, nach Typ/Modell),
  verrechnete Tokens (Einnahmen-Deckung) und «Letzte Störungen»
  (KI-/OCR-/Webhook-Ausfälle, zusätzlich per Mail bei konfiguriertem SMTP).
- **👥 Nutzer** – Suche, Guthaben/Verbrauch, manuelle Token-Gutschrift oder
  -Korrektur mit Pflicht-Grund (jede Buchung protokolliert). Dein Werkzeug für
  Kulanz, Rückerstattungen und verpasste Webhooks.
- **💬 Feedback** – eingegangene Nutzer-Rückmeldungen.
- **📚 Bibliothek** – Arbeitsblätter hochladen/verwalten.

## 🚀 Deployment (Vercel über GitHub Actions)

**Der einzige Deploy-Weg in die Produktion:** Push auf `main` →
`.github/workflows/deploy.yml` läuft automatisch (Backend-Tests +
Frontend-Build → Vercel-Deploy → Smoke-Test gegen die Live-App).

Die Vercel-Git-Verbindung bleibt bewusst bestehen, deployt aber **nicht** die
Produktion: `vercel.json` setzt `git.deploymentEnabled: {"main": false}`.
Grund: Vercels eigener Deploy überspringt die Tests **und** bekommt das
Secrets-Sidecar `api/runtime-env.json` nicht – am 31.07.2026 hat genau das die
API für fünf Minuten lahmgelegt (`FUNCTION_INVOCATION_FAILED`, fehlendes
`JWT_SECRET`). Die Aufgabenteilung ist deshalb:

| Weg | Zuständig für | Tests davor |
|---|---|---|
| Vercel-Git-Verbindung | **Vorschau-Deploys** je Branch (alles ausser `main`) | – |
| GitHub Actions | **Produktion** (`main`) | ja |

Vorschau-Deploys bekommen das Sidecar nicht (das schreibt nur der GitHub-Ablauf)
und brauchen deshalb **genau eine** Variable unter **Vercel → Settings →
Environment Variables**, Umgebung **nur Preview**:

| Variable | warum |
|---|---|
| `JWT_SECRET` | irgendein langer Zufallswert; ohne ihn verweigert `_check_production_config()` den Start (`VERCEL` gesetzt ⇒ `is_production`) |

Bewusst **nicht** gesetzt: `DATABASE_URL` – dann fällt `api/index.py:56` auf eine
leere Wegwerf-Datenbank (SQLite in `/tmp`) zurück und ein Testlauf kann die
echten Schülerdaten nicht berühren. Ebenso `ANTHROPIC_API_KEY` – ohne Schlüssel
antwortet der deterministische Mock, was für einen Start-Test genügt und nichts
kostet.

Für **Production** in Vercel bewusst **nichts** eintragen: die Werte kommen dort
weiterhin aus dem Sidecar. (Falls doch einmal nötig – in Vercel gesetzte
Variablen gewinnen über das Sidecar, weil `api/index.py` `os.environ.setdefault`
benutzt.)

**GitHub-Secrets** (Settings → Secrets and variables → Actions):

| Secret | Zweck |
|---|---|
| `VERCEL_TOKEN` | Deploy-Berechtigung |
| `RUNTIME_ENV_JSON` | JSON mit den Laufzeit-Variablen (siehe unten) – wird als Sidecar-Datei deployt, landet nie im Git |
| `ANTHROPIC_API_KEY` | überschreibt den Wert im JSON (einzeiliger Klartext, weniger Einfüge-Fehler) |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | schalten die Zahlung frei (optional bis zum Stripe-Go-live) |
| `DATABASE_URL` + `BACKUP_PASSWORD` | fürs wöchentliche DB-Backup (`backup.yml`, siehe `docs/BACKUP.md`) |

**Wichtige Laufzeit-Variablen** (im `RUNTIME_ENV_JSON`; vollständige Liste mit
Kommentaren in `backend/.env.example`):

| Variable | Zweck |
|---|---|
| `JWT_SECRET` | langer Zufallswert – Platzhalter verweigert den Start |
| `DATABASE_URL` | Supabase **Session pooler**-URL |
| `ANTHROPIC_API_KEY` | echter Tutor (ohne Key: deterministischer Mock) |
| `SUPABASE_URL` + `SUPABASE_ANON_KEY` | «Passwort vergessen»-Mails über Supabase Auth |
| `FRONTEND_BASE_URL` | `https://schrittweise-2-0.vercel.app` |
| `FREE_MONTHLY_TOKENS`, `BILLING_MARGIN`, `USD_CHF_RATE` | Preismodell (Defaults 50 / 3.0 / 0.90) |
| `REQUIRE_EMAIL_VERIFICATION` | E-Mail-Bestätigungs-Pflicht – **erst aktivieren, wenn der Mailversand nachweislich läuft** |
| `SMTP_*` + `ALERT_EMAIL` | eigener Mailversand; schaltet auch Betreiber-Alarm-Mails frei |

Supabase-Hinweise: Unter **Authentication → URL Configuration** die Site-URL
auf die Vercel-Domain und `…/login/verify` als Redirect eintragen. Der
eingebaute Supabase-Mailer ist gedrosselt (wenige Mails/Stunde) – für den
echten Betrieb unter **Authentication → SMTP Settings** einen eigenen Absender
(z. B. Brevo, gratis bis 300 Mails/Tag) hinterlegen.

Sicherheits-Guards ab Werk: Produktion bricht den Start hart ab bei
Platzhalter-`JWT_SECRET` oder aktivem Dev-Login; Registrierung mit IP-Limit +
Honeypot + AGB-Pflicht; Login-/Link-Rate-Limits; Chat-/OCR-Frequenzbremsen;
Passwort-Änderung invalidiert alle alten Tokens; Magic-Link-Tokens nur gehasht.

## 🗄️ Backup & Störungen

- **Backup:** `backup.yml` sichert die DB jeden Sonntag als (optional
  verschlüsseltes) GitHub-Artefakt, 90 Tage Aufbewahrung. Einrichtung und
  Wiederherstellung: **`docs/BACKUP.md`**.
- **Störungen:** KI-/OCR-/Webhook-Fehler erscheinen unter Admin → Kosten
  («Letzte Störungen») und gehen per Mail an `ALERT_EMAIL`, sobald SMTP
  konfiguriert ist. Für Ausfall-Überwachung von aussen: Gratis-Monitor
  (z. B. UptimeRobot) auf `https://schrittweise-2-0.vercel.app/api/health`.

## Projektstruktur

```
backend/          FastAPI-App
  app/
    models.py     Datenmodell (users, topics, exercises, attempts, messages,
                  api_usage, payments, token_adjustments, alerts, …)
    routers/      auth, topics, exercises, attempts, parents, quota,
                  library, pay, feedback, admin
    services/     sympy-Verifikation, OCR (Claude Vision), Tutor (LLM),
                  quota (Token-Abrechnung), usage (Kosten), alert, Aggregate
  tests/          pytest-Suite (läuft als Deploy-Gate in der Pipeline)
frontend/         React + Vite
  src/screens/    Landing, Login, Lernen, Themen, Bibliothek, Eltern, Preise,
                  Einstellungen, Kosten (Admin), Nutzer (Admin), Rechtliches
  src/components/ AppShell, NewTaskModal, DrawPad, MathFigure, FeedbackModal
docs/BACKUP.md    Backup einrichten & wiederherstellen
design/referenz.html   Visueller Massstab
```

## Lokal starten mit einem Befehl

- **Mac/Linux:** `./start.sh`
- **Windows:** Doppelklick auf `start.bat`

Das Skript richtet beim ersten Lauf alles ein (Python-Venv, npm-Pakete,
`.env`), startet beide Server und öffnet http://localhost:5173.
Voraussetzungen: [Python 3.11+](https://python.org) und [Node.js 18+](https://nodejs.org).

Registrieren im Tab **«Neu hier»** (E-Mail + Passwort + AGB-Häkchen – lokal
darf die E-Mail erfunden sein). Ohne `ANTHROPIC_API_KEY` antwortet ein
deterministischer Übungs-Mock; «Passwort vergessen» gibt lokal den Link direkt
zurück (`MAGIC_LINK_DEV_RETURN=true` in der `.env`).

## Lokal starten (manuell)

**Backend** (Terminal 1):

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # ANTHROPIC_API_KEY eintragen (für den echten Chat)
uvicorn app.main:app --reload --port 8000
# API-Docs: http://localhost:8000/docs
```

**Frontend** (Terminal 2):

```bash
cd frontend
npm install
npm run dev
# App: http://localhost:5173  (Vite proxyt /api ans Backend)
```

## 🚀 Launch-Checkliste (Betreiber)

Rechtsseiten (Impressum/Datenschutz/AGB) sind ausgefüllt und decken das
Token-Modell ab; Tests, Backups, Alarme und Härtung sind eingebaut. Offen:

1. **Stripe scharfschalten** (Reihenfolge einhalten, ~15 Minuten):
   1. Stripe-Dashboard → **Entwickler → API-Schlüssel** → «Geheimer
      Schlüssel» kopieren (Testmodus: beginnt mit `sk_test_`).
   2. Stripe-Dashboard → **Entwickler → Webhooks → Endpunkt hinzufügen**:
      URL `https://schrittweise-2-0.vercel.app/api/pay/webhook`, Event
      **nur** `checkout.session.completed`. Danach das
      **Signaturgeheimnis** des Endpunkts kopieren (`whsec_…`).
   3. GitHub → Repo → **Settings → Secrets and variables → Actions →
      New repository secret**: `STRIPE_SECRET_KEY` (Schritt 1) und
      `STRIPE_WEBHOOK_SECRET` (Schritt 2). Beide Werte gehören **nur**
      dorthin – nie in den Code, nie in einen Chat.
   4. Deploy auslösen (beliebiger Push auf `main` oder Actions →
      «Deploy (Vercel)» → «Run workflow»). Die Schlüssel landen über den
      Sidecar in der Laufzeit-Konfiguration.
   5. **Prüfen:** `https://schrittweise-2-0.vercel.app/api/health` muss
      `"zahlung": true` zeigen. Dann auf der Preise-Seite mit der
      Stripe-Testkarte `4242 4242 4242 4242` (beliebiges künftiges
      Datum, CVC 123) kaufen → Tokens erscheinen innerhalb von Sekunden;
      in Stripe steht der Webhook auf «Erfolgreich».
   6. **TWINT** (die Preise-Seite bewirbt es): Stripe-Dashboard →
      **Einstellungen → Zahlungsmethoden → TWINT aktivieren**. Braucht
      ein Schweizer Stripe-Konto und CHF – beides ist gegeben.
   7. Zum Echtbetrieb: Live-Modus einschalten, Schritte 1–3 mit den
      Live-Werten (`sk_live_…`, neuer Webhook + neues `whsec_…`)
      wiederholen. Solange Schlüssel fehlen, sind die Kauf-Knöpfe
      automatisch gesperrt («bald») – niemand läuft in einen Fehler.
2. **Backup aktivieren:** GitHub-Secrets `DATABASE_URL` + `BACKUP_PASSWORD`
   setzen, einmal manuell laufen lassen (`docs/BACKUP.md`).
3. **Uptime-Monitor:** z. B. UptimeRobot auf `/api/health`.
4. **Eigener Mailversand:** Brevo-SMTP im Supabase-Dashboard hinterlegen
   (oder `SMTP_*` in `RUNTIME_ENV_JSON`); danach
   `REQUIRE_EMAIL_VERIFICATION=true` setzen – ab dann brauchen neue Konten
   die E-Mail-Bestätigung für KI-Nutzung und Käufe.
5. **Bibliothek füllen** (10–15 Arbeitsblätter) und optional eigene Domain
   (z. B. kniff.ch) in Vercel verbinden.

## Umbenennen: was noch offen ist

Der Produktname heisst überall **Kniff** – Seitentitel, Logo, Landing, Login,
Eltern-Ansicht, Rechtliches (AGB/Impressum/Datenschutz), Feedback, Mail-Betreff
und -Signatur, Stripe-Paketnamen, Favicon («K») und der Tutor selbst.

Bewusst **nicht** angefasst, weil es laufende Technik bricht – jeder Punkt ist
eine eigene, bewusste Umstellung:

| Was | Heute | Warum offen |
|---|---|---|
| Live-Adresse | `schrittweise-2-0.vercel.app` | Umbenennen des Vercel-Projekts ändert die URL – erst eine eigene Domain (z. B. `kniff.ch`) verbinden, dann umstellen |
| ~~GitHub-Repo~~ | `mueddi/KNIFF` seit 9.9. | Erledigt. Der Deploy brach dabei wie vorhergesagt (Vercel-CLI riet den Projektnamen aus dem Ordner «KNIFF»); seither stehen `VERCEL_ORG_ID`/`VERCEL_PROJECT_ID` fest in `deploy.yml`. Alte Klone und Links funktionieren über GitHubs Weiterleitung |
| Absender der Mails | `no-reply@schrittweise.ch` | Die Domain muss zuerst existieren und im Mailversand freigegeben sein, sonst landen Mails im Spam |
| Backup-Dateinamen, Log-Namen, `sw_token` im Browser | `schrittweise…` | Rein intern; ein Wechsel würde alte Backups schwerer auffindbar machen und alle Nutzer ausloggen |

Hinweis Supabase free: Projekte pausieren nach ~1 Woche ohne Zugriff – bei
täglich genutzter App passiert das nicht.
