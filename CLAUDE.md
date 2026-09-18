# Kniff – Arbeitsanweisung

KI-Mathe-Tutor für die Schweizer Mittelstufe, Oberstufe und das Gymnasium.
Live: https://schrittweise-2-0.vercel.app · Repository: `mueddi/KNIFF` (bis 9.9.
`mueddi/Schrittweise-2.0`; GitHub leitet den alten Namen weiter)

Der Betreiber ist **kein Programmierer**. Erkläre auf Deutsch, in ganzen Sätzen,
ohne Fachjargon – und wenn Fachbegriffe unvermeidlich sind, erkläre sie beim
ersten Mal. Er trifft die Entscheidungen; du lieferst Belege, keine Vermutungen.

## Die Regeln, die nicht verhandelbar sind

1. **Keine Geheimnisse ins Repository und keine in den Chat.** Weder
   `api/runtime-env.json` noch `.env` noch Token, Schlüssel oder Passwörter –
   auch nicht als Ausschnitt. Schlüssel*namen* sind in Ordnung, Werte nie.
2. **NIEMALS auf `main` pushen, mergen oder rebasen.** Nicht nach einem «ok»,
   nicht nach einer Ankündigung, nicht «weil es fertig ist». Arbeit geht
   ausschliesslich auf einen Zweig und wird dorthin gepusht. Der Zusammenführer
   ist **immer der Betreiber**, von Hand auf github.com. Am 31.07. habe ich
   zweimal nach einem «ok» selbst gemergt – er wollte das nicht. Es gibt keinen
   Fall, in dem dieser Punkt zur Diskussion steht.
3. **Nie ungefragt einen Pull Request anlegen.** Nur wenn er ausdrücklich
   darum bittet.
4. **Riskantes zuerst in die Vorschau.** Alles, was das Startverhalten, die
   Datenbank oder die Konfiguration betrifft, geht auf einen Zweig und wird
   dort geprüft, bevor es `main` sieht.
5. **Ein Commit, ein Thema.** Am 31.07. musste eine Änderung zurückgerollt
   werden und riss zwei fertige, geprüfte Aufräumungen mit. Riskantes und
   Harmloses gehören nicht zusammen.
6. **Messen statt vermuten.** Produktions-Datenbank (Supabase), Vercel-Laufzeit-
   protokolle und GitHub-Actions-Läufe sind zugänglich. Eine Behauptung ohne
   Beleg ist keine Antwort. Der Betreiber hat ausdrücklich erlaubt, die
   gespeicherten Chats in der Datenbank zu lesen.

## Wie eine Änderung live geht

```
Zweig  →  Vercel baut automatisch eine Vorschau  →  er schaut sie an
       →  Pull Request  →  303 Tests  →  sein Merge-Klick  →  live
```

* **Produktion ausschliesslich über `.github/workflows/deploy.yml`** (Test →
  Deploy → Smoke-Test). `vercel.json` setzt `git.deploymentEnabled {"main":
  false}`, damit Vercel `main` nicht an den Tests vorbei deployt – genau das
  hat am 31.07. einen fünfminütigen Ausfall verursacht.
* **In Vercel niemals «Promote to Production»** benutzen. Das umgeht die Tests.
* **Vorschau-Umgebung** (Vercel → Environment Variables, Umgebung *Preview*):
  `JWT_SECRET` (ein **anderer** als in Produktion – gleicher Wert hiesse, ein
  Ausweis aus der Vorschau gälte auch live), `DATABASE_URL` auf das eigene
  Supabase-Projekt **kniff-vorschau** (`fdgbeicshpttcqnhinso`, leer, eigene
  Tabellen) und `ANTHROPIC_API_KEY` (eigener Schlüssel, damit die Testkosten
  getrennt sichtbar sind – jede Testantwort kostet echtes Geld).
  E-Mail-Bestätigung ist dort abgeschaltet (`app/plattform.vorschau_defaults`),
  sonst käme man nicht hinein.
  **Vorher lief die Vorschau auf SQLite in `/tmp`** – die gehört jeweils nur
  einer Serverless-Instanz, also warf sie einen nach dem Anmelden sofort wieder
  raus. Nicht dorthin zurück.
* Vorschau-Adressen liegen hinter dem Vercel-Login. Aus einer Cloud-Sitzung
  sind sie oft nur per GET erreichbar oder gar nicht – dann den Betreiber
  bitten, die Zeile zu kopieren, statt zu raten.

## Tests

```
cd backend && python -m pytest -q          # 303 Tests, müssen alle grün sein
cd frontend && npm run build               # enthält die Browser-Dialog-Bremse
```

Bei reinen Streichungen darf **kein** bestehender Test angepasst werden müssen –
muss doch einer angefasst werden, war der Code nicht tot.

Fehlen die Abhängigkeiten im Container: `uv venv /tmp/kniff-venv` und
`uv pip install --python /tmp/kniff-venv/bin/python -r backend/requirements.txt pytest`.

## Wo was liegt

| Bereich | Datei |
|---|---|
| Anweisung an den Tutor (deutscher Fliesstext) | `backend/app/services/tutor.py` |
| Mathe-Prüfung | `backend/app/services/sympy_verifier.py` |
| Chat-Bildschirm | `frontend/src/screens/Lernen.jsx` |
| Aufgaben-Bibliothek (Aufgaben, nicht PDFs; Start im Tutor, KI-Vorschau) | `backend/app/routers/library.py`, `frontend/src/screens/Bibliothek.jsx` |
| Störungen mit Einordnung «handeln / prüfen / keine» | `backend/app/services/stoerungen.py` |
| App-Dialoge (nie `window.confirm`!) | `frontend/src/lib/dialog.jsx` |
| Preise, Kontingent | `backend/app/config.py` |
| Farben, Schriften | `frontend/src/styles/theme.css` |
| Serverless-Einstieg (Vercel) | `api/index.py` |

Browser-Dialoge (`alert`, `confirm`, `prompt`) sind verboten und werden vom
Build abgewiesen (`frontend/scripts/keine-browser-dialoge.mjs`). Stattdessen
`useDialog()` aus `lib/dialog.jsx`.

## Offen (Stand 7. September 2026)

Pull Request 2 (25 Commits: Tutor-Reparatur, Sonnet-Fehler, Kosten- und
Störungsseite, Bibliothek, «Problem melden», Foto-Bestätigung) ist am 7.9.
gemergt und live; Deploy-Lauf grün, `/api/health` ok, alle Migrationen in der
Produktion angelegt. Die 17 Startaufgaben der Bibliothek liegen in der
Produktion. Launch-Checkliste des Betreibers:
https://claude.ai/code/artifact/67bdea5a-096e-439f-83f6-067727e5424b

* ~~Die wöchentliche Sicherung ist noch nie gelaufen~~ – **erledigt 7.9.**:
  Secrets `DATABASE_URL` (Session-Pooler der Produktion) und `BACKUP_PASSWORD`
  angelegt, erster Lauf grün, Artefakt 3 MB, 90 Tage aufbewahrt. Läuft jetzt
  jeden Sonntag 03:00 UTC. Vorher: neun Fehlläufe seit dem 19.07.
* ~~Kein Zweig-Schutz auf `main`~~ – **erledigt 7.9.**: Ruleset «main-schutz»
  (aktiv): Pull Request Pflicht, Status-Checks `backend-tests` und
  `frontend-build`, keine Force-Pushes, kein Löschen.
* **Keine Überwachung von aussen.** Zwei Ausfälle blieben unbemerkt, bis er
  zufällig hinschaute. Er muss UptimeRobot einrichten – Typ «Keyword», Adresse
  `…/api/health`, Stichwort `"status":"ok"`, Alarm wenn es FEHLT.
  Die Gegenstelle dafür steht: `main.py:health()` fasst die Datenbank an und
  antwortet bei einem Ausfall mit **503** und ohne das Wort `ok`.
* **Vercel läuft auf `hobby`** – dieser Tarif ist laut Vercels Bedingungen für
  nicht-kommerzielle Projekte. Vor dem Verkauf von Tokens klären. Der
  Betreiber will beim ersten Käufer wechseln.
* **Supabase seit 7.9. auf Pro**, aber nur für die Produktion: in der
  Pro-Organisation «mueddi's Org» liegen nur `schrittweise` (läuft, durch die
  Compute-Gutschrift gedeckt) und `Rayner Sales` (pausiert). Jedes weitere
  AKTIVE Projekt in einer Pro-Organisation kostet ~10 USD/Monat, und das ist
  vom Spend Cap ausgenommen. `kniff-vorschau` und `quitta` liegen deshalb in
  einer zweiten, kostenlosen Organisation (verschoben 7.9.; die
  Projekt-Nummer bleibt gleich, `DATABASE_URL` unverändert). Der MCP-Zugang
  dieser Sitzungen sieht nur «mueddi's Org»; die Vorschau-Datenbank ist per
  SQL trotzdem erreichbar. Gratis-Limit: zwei laufende Projekte pro KONTO.
  **Pausieren geht nur im Gratis-Tarif** («Project is not free-tier»,
  getestet 7.9.). Dort pausiert
  `.github/workflows/vorschau-datenbank.yml` sie nachts, wenn 24 h kein Push
  auf einen Zweig kam, und weckt sie bei jedem Push (Secret
  `SUPABASE_ACCESS_TOKEN`, angelegt 7.9.). Nach dem Wecken dauert es etwa
  eine Minute, bis die Vorschau eine Datenbank hat.
* **Die Zahlung wurde nie durchgeführt:** im Live-Stripe-Konto stehen
  0 Checkout-Sitzungen. Vor dem Start einmal echt kaufen und nachzählen.
* **Impressum ohne Postadresse** (`frontend/src/screens/Rechtliches.jsx`) –
  nur Name und E-Mail. Für ein kommerzielles Schweizer Angebot zu wenig.

## Bekannte Schwächen (belegt, nicht behoben)

* **Bilderkennung – Befund vom 7.9., nach Sichtung der Bilder selbst:** alle
  124 gespeicherten Bilder sind Stift-Zeichnungen aus der App, kein einziges
  echtes Foto. Der Foto-Weg ist in der Produktion nie benutzt worden. Von den
  letzten vier Zeichnungen wurden drei korrekt gelesen; `Fg=` war ein
  Gekritzel, das auch ein Mensch nicht lesen kann. Das eigentliche Loch: der
  erkannte Text ist vor dem Start kaum sichtbar, und bei «nichts erkannt» darf
  man trotzdem starten. Erst das ändern, dann mit zehn echten Fotos messen.
* **Die Mathe-Prüfung urteilt selten:** 94 % der Antworten kommen als «nicht
  prüfbar» zurück, weil nur 15 von 52 Aufgaben einen Prüfausdruck haben.
  Symbolische Antworten (`x = 7y/3`) kann sie ohnehin nicht beurteilen.
* **Kosten – wo sie herkommen (gemessen 7.9., Produktion seit 11.7.):**
  Das Foto ist der teuerste Einzelposten: eine Erkennung (Sonnet, ~1700 Token
  Eingabe) kostet ~0.45 Rp., eine Chat-Runde mit Haiku und warmem Cache
  0.15–0.25 Rp., der erste Turn einer Aufgabe ~1.2 Rp. (schreibt ~6700 Token
  in den 1-Stunden-Cache). 58 von 116 Erkennungen kamen von EINEM Schul-Plan-
  Konto (Nr. 2), das nie eine Aufgabe angelegt hat. Bis August lag der
  Tutor-Prompt unter Haikus Cache-Schwelle (4096 Token) – seit dem Umbau vom
  6.9. liegt er bei ~6300 und der Cache greift auch über Aufgaben hinweg.
  Noch offen: nach 6 Chat-Runden schneidet `HISTORY_LIMIT = 12` den Verlauf
  jeden Turn neu zu, und der Verlaufs-Cache trifft nicht mehr (in der
  Vorschau belegt: Lesen bleibt bei 7964, Schreiben 650–830 pro Turn).
* **`attempts.status` und `exams.model`** sehen tot aus, sind aber `NOT NULL`
  ohne Standardwert in der Produktion. Werden sie aus dem Modell entfernt,
  schlagen Einfügungen fehl. **Nicht anfassen.**
