// Gemeinsame Hilfen fuer die Browser-Tests.
import { execFileSync } from "node:child_process";
import { expect, test as basis } from "@playwright/test";

const API = "http://localhost:8000";
let zaehler = 0;

// Jede Seite sammelt Fehler mit. Am Ende eines Tests muss die Liste leer sein:
// ein JavaScript-Absturz, ein console.error oder eine 5xx-Antwort unserer
// eigenen Schnittstellen macht den Test rot – auch wenn die Seite "aussieht".
export const test = basis.extend({
  fehler: async ({ page }, use) => {
    const fehler = [];
    // Externe Dienste (Schriften, Vercel-Toolbar) im Test gar nicht erst laden
    await page.route(/^https?:\/\/(?!localhost)/, (route) => route.abort());
    page.on("pageerror", (e) => fehler.push(`JS-Absturz: ${e.message}`));
    page.on("console", (m) => {
      if (m.type() !== "error") return;
      const text = m.text();
      // Laden von Ressourcen: nur eigene Server-Fehler zaehlen (unten ueber
      // "response"); abgebrochene Fremd-Anfragen und bewusste 4xx sind keine Fehler.
      if (text.startsWith("Failed to load resource")) return;
      fehler.push(`console.error: ${text}`);
    });
    page.on("response", (r) => {
      if (r.url().startsWith("http://localhost") && r.status() >= 500 && r.status() !== 503) {
        fehler.push(`Server ${r.status()}: ${r.request().method()} ${r.url()}`);
      }
    });
    await use(fehler);
    expect(fehler, "Fehler im Browser").toEqual([]);
  },
});
export { expect };

// Konto direkt ueber die Schnittstelle anlegen (schneller als das Formular).
// Eigene X-Forwarded-For je Konto, sonst greift die Registrier-Bremse (15/Tag/IP).
export async function konto(request, { rolle = "student", name = "Test" } = {}) {
  zaehler += 1;
  const email = `e2e-${Date.now()}-${zaehler}@test.ch`;
  const r = await request.post(`${API}/api/auth/register`, {
    headers: { "X-Forwarded-For": `10.9.${zaehler % 250}.${(Date.now() % 250) + 1}` },
    data: { email, password: "e2e-passwort-123", display_name: name, role: rolle, terms_accepted: true, grade_level: "oberstufe" },
  });
  expect(r.status(), await r.text()).toBe(200);
  const { access_token } = await r.json();
  return { email, token: access_token, headers: { Authorization: `Bearer ${access_token}` } };
}

// Die Seite mit gesetzter Anmeldung oeffnen.
export async function angemeldet(page, k) {
  await page.addInitScript((t) => {
    localStorage.setItem("sw_token", t);
    localStorage.setItem("sw_lang", "de");
  }, k.token);
}

// Konto zum Admin machen – direkt in der Test-Datenbank.
export function zumAdmin(email) {
  const python = process.env.E2E_PYTHON || "python3";
  execFileSync(python, ["-c", `
import sqlite3
db = sqlite3.connect("e2e.db")
db.execute("update users set is_admin = 1 where email = ?", (${JSON.stringify(email)},))
db.commit()
`], { cwd: new URL("../../backend", import.meta.url).pathname });
}

// Die Fehlergrenze der App (main.jsx) darf nie erscheinen.
export async function keinAbsturzBildschirm(page) {
  await expect(page.getByText("Ups, da ist etwas schiefgelaufen")).toHaveCount(0);
}
