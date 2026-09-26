# Datenbank-Backup & Wiederherstellung

## Was passiert automatisch?

Jeden Sonntag um 03:00 UTC sichert der GitHub-Actions-Workflow
**«Backup (Datenbank)»** die komplette Supabase-Datenbank (Nutzer, Guthaben,
Zahlungen, Aufgaben, Chats, Bibliothek) und legt sie als Artefakt im Repo ab.
Artefakte bleiben **90 Tage** erhalten – es sind also immer rund 12 Stände da.

Manuell auslösen: GitHub → Actions → «Backup (Datenbank)» → «Run workflow».

## Einmalige Einrichtung (2 Secrets)

GitHub → Settings → Secrets and variables → Actions → «New repository secret»:

1. **`DATABASE_URL`** – der Supabase «Session pooler»-Connection-String
   (Supabase-Dashboard → Project Settings → Database → Connection string).
   Derselbe Wert steht bereits in deinem `RUNTIME_ENV_JSON` unter
   `DATABASE_URL`.
2. **`BACKUP_PASSWORD`** *(empfohlen)* – ein langes, selbst gewähltes
   Passwort. Damit wird das Backup zusätzlich verschlüsselt.
   **Bewahre es z.B. im Passwort-Manager auf – ohne dieses Passwort ist ein
   verschlüsseltes Backup wertlos.**

## Wiederherstellung (Notfall)

1. Backup herunterladen: GitHub → Actions → letzter «Backup»-Lauf →
   Artefakt `db-backup-…` herunterladen und entpacken.
2. Falls verschlüsselt (`.enc`), entschlüsseln:

   ```bash
   openssl enc -d -aes-256-cbc -pbkdf2 -in schrittweise.dump.enc -out schrittweise.dump
   # fragt nach dem BACKUP_PASSWORD
   ```

3. In die (neue oder geleerte) Datenbank einspielen:

   ```bash
   docker run --rm -i -e DATABASE_URL="<Supabase-Session-Pooler-URL>" postgres:17 \
     sh -c 'pg_restore --clean --if-exists --no-owner --no-privileges -d "$DATABASE_URL"' \
     < schrittweise.dump
   ```

4. App testen: anmelden, eine Aufgabe öffnen, Admin → Nutzer prüfen
   (Guthaben da?).

## Automatische Rückspiel-Probe (jede Woche)

Direkt nach jeder Sicherung spielt der Job **«probe»** im selben Lauf genau
diese Sicherung in eine leere Postgres-17-Datenbank zurück (nur das Schema
`public` mit den App-Tabellen) und zählt nach: `users`, `payments`,
`exercises` und `messages` müssen mindestens so viele Zeilen haben wie kurz
vor der Sicherung in der Produktion. Ist der Lauf grün, ist bewiesen, dass
sich die Sicherung zurückspielen lässt – nicht nur, dass es sie gibt. Ist
«probe» rot, ist das Backup dieser Woche unbrauchbar: Protokoll ansehen.

## Probelauf (empfohlen nach der Einrichtung)

Einmal «Run workflow» klicken und prüfen, dass der Lauf grün ist und ein
Artefakt mit plausibler Grösse (> 10 KB) entstanden ist. Damit ist bewiesen,
dass der Zugang stimmt – nicht erst im Notfall herausfinden.
