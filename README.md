# Kniff

**KI-Mathe-Tutor für die Schweizer Mittelstufe, Oberstufe und das Gymnasium** — Mathe verstehen, nicht abschreiben.

Live: **https://kniff.app**

Kniff ist ein Lern-Tutor für die Mittelstufe (4.–6. Klasse), die Oberstufe
(Lehrplan 21) und das Gymnasium bis zur Matura,
der die Lösung nie direkt verrät. Stattdessen führt eine **Hinweis-Leiter** in vier
Stufen zum eigenen Denken:

1. Aktivierende Frage
2. Kleiner Tipp
3. Teilschritt vorgemacht
4. Volle Lösung — erst nach mindestens zwei echten eigenen Versuchen

Die Leiter wird vom Backend als Zustandsmaschine erzwungen und gilt auch dann,
wenn Schüler:innen um die Lösung betteln.

## Prinzipien

- **Nie die Lösung verraten.** Die Hinweis-Leiter ist im System-Prompt und im
  Backend verankert.
- **Privacy by Design.** Eltern sehen nur Aggregate (Selbständigkeit %, gelöste
  Aufgaben, aktive Tage, Themen-Trends) — nie Transkripte. Die Aggregate liegen
  in einer separaten Tabelle; aus der Eltern-Rolle gibt es technisch keinen
  Zugriff auf Nachrichten.
- **SymPy prüft Mathe, das LLM macht Pädagogik.** Jede Antwort wird
  deterministisch verifiziert; das Ergebnis geht als Kontext ans LLM.
- **Themen sind manuelle Container** — keine automatische Klassifikation.

## Features

- Hinweis-Leiter-Chat mit Streaming und KaTeX-Formeldarstellung
- Foto-Upload von Aufgaben mit OCR-Preview
- Themen-Verwaltung mit Fortschrittsanzeige
- Eltern-Dashboard (Verknüpfung per Code, nur Aggregate)
- Einfacher Login mit E-Mail + Passwort, Gratis-Kontingent + Preisseite
- Mock-Tutor ohne API-Key — die App ist auch ohne Anthropic-Key voll testbar

## Tech-Stack

| Bereich | Wahl |
|---|---|
| Frontend | React + Vite, Formeln via KaTeX |
| Backend | Python + FastAPI |
| Mathe-Verifikation | SymPy |
| KI | Anthropic API (Haiku als Standard, Sonnet für komplexe Aufgaben, Prompt-Caching) |
| Datenbank | Supabase Postgres (lokal SQLite) via SQLAlchemy |
| Auth | E-Mail + Passwort (scrypt) + JWT; Magic-Link-Flows als Alternative im Code |
| Deployment | Vercel (Serverless + Static Build), ausgelöst über GitHub Actions nach den Tests |

## Schnellstart

**Mit einem Befehl** (richtet beim ersten Lauf Venv, npm-Pakete und `.env` ein):

- Mac/Linux: `./start.sh`
- Windows: `start.bat`

Danach läuft die App auf http://localhost:5173. Voraussetzungen:
[Python 3.11+](https://python.org) (Produktion und CI: 3.14) und [Node.js 18+](https://nodejs.org).

**Manuell:**

```bash
# Backend (Terminal 1)
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # ANTHROPIC_API_KEY eintragen (optional, sonst Mock)
uvicorn app.main:app --reload --port 8000

# Frontend (Terminal 2)
cd frontend
npm install
npm run dev
```

Login ist E-Mail + Passwort. Lokal darf die E-Mail erfunden sein; «Passwort
vergessen» gibt den Link im Dev-Modus direkt zurück — kein Mailserver nötig.

## Projektstruktur

```
backend/          FastAPI-App
  app/models.py   Datenmodell (users, topics, exercises, attempts, messages,
                  progress_aggregates, parent_links, magic_links)
  app/routers/    auth, topics, exercises, attempts, exams, grades, parents,
                  quota, library, pay, feedback, admin
  app/services/   SymPy-Verifikation, OCR, Tutor (LLM), Aggregate
frontend/         React + Vite
  src/screens/    Landing, Login, Lernen, Themen, Bibliothek, Eltern, Preise,
                  Einstellungen, Admin (Kosten, Nutzer, Störungen)
design/referenz.html   Visueller Massstab
api/index.py      Vercel-Serverless-Einstieg
vercel.json       Vercel Build & Routing
```

## Deployment & Launch

Ausführliche Anleitungen (Vercel, Supabase-Postgres, SMTP,
Launch-Checkliste, Sicherheits-Guards) stehen in
[KNIFF.md](KNIFF.md).

Wichtig: Secrets (`ANTHROPIC_API_KEY`, `JWT_SECRET`, `SMTP_*`, `DATABASE_URL`)
werden **nie committet** — nur als Umgebungsvariablen im Hosting-Dashboard
gesetzt. Die `.gitignore` schliesst `.env`-Dateien und `api/runtime-env.json`
aus. In Produktion verweigert die App den Start, wenn `JWT_SECRET` noch der
Platzhalter ist.
