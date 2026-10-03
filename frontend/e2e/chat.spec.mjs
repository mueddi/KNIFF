// Der Chat selbst: Formeln, Eingabe, Handy-Ansicht.
import { execFileSync } from "node:child_process";
import { angemeldet, expect, konto, test } from "./hilfen.mjs";

const API = "http://localhost:8000";

async function aufgabe(request, k, text = "Löse 3x + 5 = 20") {
  const ex = await (await request.post(`${API}/api/exercises`, { headers: k.headers, data: { text } })).json();
  const st = await (await request.post(`${API}/api/exercises/${ex.id}/attempts`, { headers: k.headers })).json();
  return st.attempt.id;
}

test("Wurzel und Exponenten im Chat: richtig gesetzt, kein Darstellungsfehler", async ({ page, request, fehler }) => {
  // Bis 3.10. verschwand jedes Wurzelzeichen (KaTeX-SVG zerschnitten, console.error
  // «attribute d: Expected path command») – die Fehler-Falle in hilfen.mjs faengt das.
  const k = await konto(request);
  const id = await aufgabe(request, k);
  await angemeldet(page, k);
  await page.goto(`/app/lernen/${id}`);
  const eingabe = page.getByPlaceholder("Schreib deinen nächsten Schritt …");
  await eingabe.fill("x = sqrt(25) und 2^10");
  await eingabe.press("Enter");
  await expect(eingabe).toHaveValue("");
  const wurzel = page.locator(".katex svg path").first();
  await expect(wurzel).toBeAttached();
  expect(await wurzel.getAttribute("d")).not.toContain("<br");
  // 2^10: die ganze 10 steht hoch, nicht «2¹0»
  await expect(page.locator(".katex .msupsub", { hasText: "10" }).first()).toBeAttached();
});

test("Handy: lange Formel und langes Wort schieben den Chat nicht seitlich weg", async ({ page, request, fehler }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const k = await konto(request);
  const id = await aufgabe(request, k);
  await angemeldet(page, k);
  await page.goto(`/app/lernen/${id}`);
  const eingabe = page.getByPlaceholder("Schreib deinen nächsten Schritt …");
  await eingabe.fill("$$x = 1 + 2 + 3 + 4 + 5 + 6 + 7 + 8 + 9 + 10 + 11 + 12 + 13 + 14 + 15 + 16 + 17 + 18 + 19 + 20$$ Donaudampfschifffahrtsgesellschaftskapitänsmütze");
  await eingabe.press("Enter");
  await expect(page.locator(".katex-display").first()).toBeAttached();
  const masse = await page.evaluate(() => {
    const v = document.querySelector(".chat-verlauf");
    return { verlauf: v.scrollWidth - v.clientWidth, seite: document.documentElement.scrollWidth - window.innerWidth };
  });
  expect(masse.verlauf, "Chat scrollt seitlich").toBeLessThanOrEqual(1);
  expect(masse.seite, "Seite scrollt seitlich").toBeLessThanOrEqual(1);
});

test("Handy: Knöpfe in Fingergrösse, Eingabe 16 px, mit Tastatur bleibt Chat sichtbar", async ({ page, request, fehler }) => {
  await page.setViewportSize({ width: 390, height: 640 }); // ungefaehr: Handy mit offener Tastatur
  const k = await konto(request);
  const id = await aufgabe(request, k);
  await angemeldet(page, k);
  await page.goto(`/app/lernen/${id}`);
  for (const name of ["Senden", "Foto anhängen", "Mit dem Stift schreiben"]) {
    const box = await page.getByRole("button", { name }).boundingBox();
    expect(box.width, name).toBeGreaterThanOrEqual(40);
    expect(box.height, name).toBeGreaterThanOrEqual(40);
  }
  const eingabe = page.getByPlaceholder("Schreib deinen nächsten Schritt …");
  expect(await eingabe.evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(16);
  const hoehe = await page.evaluate(() => document.querySelector(".chat-verlauf").clientHeight);
  console.log("sichtbare Chat-Hoehe bei 390x640:", hoehe);
  expect(hoehe).toBeGreaterThanOrEqual(200); // vorher 163 px (gemessen 3.10.)
});

// Schuelernachricht direkt in die Test-Datenbank: so sieht ein Gespraech aus,
// dessen Antwort unterwegs verloren ging (Server abgestuerzt, Funkloch).
function verwaisteFrage(attemptId, text) {
  execFileSync(process.env.E2E_PYTHON || "python3", ["-c", `
import sqlite3, datetime
db = sqlite3.connect("e2e.db")
db.execute("insert into messages (attempt_id, role, text, created_at) values (?, 'student', ?, ?)",
           (${Number(attemptId)}, ${JSON.stringify(text)}, str(datetime.datetime.utcnow())))
db.commit()
`], { cwd: new URL("../../backend", import.meta.url).pathname });
}

async function gespraech(request, k, id, n) {
  for (let i = 0; i < n; i++) {
    const r = await request.post(`${API}/api/attempts/${id}/chat`, { headers: k.headers, data: { text: `x = ${i + 1}` } });
    expect(r.status()).toBe(200);
  }
}

test("Wer hochgescrollt hat, wird am Ende der Antwort nicht nach unten gerissen", async ({ page, request, fehler }) => {
  await page.setViewportSize({ width: 1280, height: 700 });
  const k = await konto(request);
  const id = await aufgabe(request, k);
  await gespraech(request, k, id, 6);
  await angemeldet(page, k);
  await page.goto(`/app/lernen/${id}`);
  await page.route("**/api/attempts/*/chat", async (route) => {
    await new Promise((r) => setTimeout(r, 1500));
    await route.continue();
  });
  const eingabe = page.getByPlaceholder("Schreib deinen nächsten Schritt …");
  await eingabe.fill("x = 5");
  await eingabe.press("Enter");
  await page.waitForTimeout(300);
  await page.evaluate(() => { document.querySelector(".chat-verlauf").scrollTop = 0; });
  await expect(page.getByRole("button", { name: "Senden" })).toBeEnabled({ timeout: 15_000 });
  await page.waitForTimeout(400);
  expect(await page.evaluate(() => document.querySelector(".chat-verlauf").scrollTop)).toBeLessThan(60);
});

test("Antwort ging verloren: nach dem Warten «Nochmal fragen» statt stiller Punkte", async ({ page, request, fehler }) => {
  const k = await konto(request);
  const id = await aufgabe(request, k);
  verwaisteFrage(id, "Stimmt meine Lösung so?");
  await angemeldet(page, k);
  await page.clock.install();
  await page.goto(`/app/lernen/${id}`);
  await expect(page.getByText("Stimmt meine Lösung so?")).toBeVisible();
  const hinweis = page.getByText("Auf deine letzte Nachricht ist keine Antwort angekommen.");
  // 15 Runden à 3 s: die Uhr vorspulen, zwischendurch die Netz-Antworten
  // abwarten (jede Runde wartet erst auf ihre Anfrage, dann auf den Wecker)
  for (let i = 0; i < 80 && !(await hinweis.isVisible()); i++) {
    await page.clock.fastForward(3100);
    await page.waitForTimeout(200);
  }
  await expect(hinweis).toBeVisible();
  await page.getByRole("button", { name: "Nochmal fragen" }).click();
  await expect(hinweis).toHaveCount(0);
  await expect(page.getByText("Ich warte noch auf deine Antwort.")).toBeVisible();
});

test("Verbindung bricht mitten in der Antwort ab: der angekommene Teil bleibt stehen", async ({ page, request, fehler }) => {
  const k = await konto(request);
  const id = await aufgabe(request, k);
  await angemeldet(page, k);
  await page.addInitScript(() => {
    const echt = window.fetch;
    window.fetch = (url, opts) => {
      if (!String(url).endsWith("/chat")) return echt(url, opts);
      const body = new ReadableStream({
        start(c) {
          c.enqueue(new TextEncoder().encode("Erster Teil der Antwort"));
          setTimeout(() => c.error(new TypeError("Verbindung weg")), 80);
        },
      });
      return Promise.resolve(new Response(body, { status: 200 }));
    };
  });
  await page.goto(`/app/lernen/${id}`);
  const eingabe = page.getByPlaceholder("Schreib deinen nächsten Schritt …");
  await eingabe.fill("Ich glaube es ist fünf");
  await eingabe.press("Enter");
  await expect(page.getByText(/Die Verbindung ist abgebrochen/)).toBeVisible();
  await expect(page.getByText("Erster Teil der Antwort")).toBeVisible();
  await expect(page.getByText("Ich glaube es ist fünf")).toBeVisible(); // die eigene Frage bleibt
  await expect(page.getByText(/Ups, da ging etwas schief/)).toHaveCount(0);
});

test("Zweimal Enter im selben Augenblick schickt nur eine Nachricht", async ({ page, request, fehler }) => {
  const k = await konto(request);
  const id = await aufgabe(request, k);
  await angemeldet(page, k);
  await page.goto(`/app/lernen/${id}`);
  let anfragen = 0;
  page.on("request", (r) => { if (r.url().endsWith("/chat") && r.method() === "POST") anfragen += 1; });
  const eingabe = page.getByPlaceholder("Schreib deinen nächsten Schritt …");
  await eingabe.fill("x = 5");
  await eingabe.evaluate((el) => {
    for (let i = 0; i < 2; i++) el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  });
  await expect(page.getByRole("button", { name: "Senden" })).toBeEnabled({ timeout: 15_000 });
  expect(anfragen).toBe(1);
});

test("Mehrzeilig: Shift+Enter macht eine neue Zeile, Enter schickt alles zusammen", async ({ page, request, fehler }) => {
  const k = await konto(request);
  const id = await aufgabe(request, k);
  await angemeldet(page, k);
  await page.goto(`/app/lernen/${id}`);
  let anfragen = [];
  page.on("request", (r) => { if (r.url().endsWith("/chat") && r.method() === "POST") anfragen.push(r.postDataJSON().text); });
  const eingabe = page.getByPlaceholder("Schreib deinen nächsten Schritt …");
  await eingabe.click();
  await eingabe.pressSequentially("Zuerst minus fünf");
  await eingabe.press("Shift+Enter");
  await eingabe.pressSequentially("dann durch drei");
  expect(anfragen).toHaveLength(0);
  // Enter waehrend eine Eingabehilfe (IME) noch tippt: nicht senden
  await eingabe.evaluate((el) => el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", isComposing: true, bubbles: true })));
  expect(anfragen).toHaveLength(0);
  await eingabe.press("Enter");
  await expect(eingabe).toHaveValue("");
  expect(anfragen).toEqual(["Zuerst minus fünf\ndann durch drei"]);
  await expect(page.getByText("dann durch drei")).toBeVisible();
});

test("Handy: «Anders erklären» zeigt die Wege sichtbar, «Problem melden» schliesst mit Escape", async ({ page, request, fehler }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const k = await konto(request);
  const id = await aufgabe(request, k);
  await angemeldet(page, k);
  await page.goto(`/app/lernen/${id}`);
  await page.getByRole("button", { name: "🔄 Anders erklären" }).click();
  const zurueck = page.getByRole("button", { name: "← zurück" });
  await expect(zurueck).toBeVisible();
  // die Wege stehen jetzt vorne in der Reihe, nicht rechts ausserhalb des Bildschirms
  const knoepfe = zurueck.locator("xpath=..").getByRole("button");
  const zweiter = await knoepfe.nth(1).boundingBox();
  expect(zweiter.x + zweiter.width).toBeLessThanOrEqual(390);
  await zurueck.click();
  await expect(page.getByRole("button", { name: "🔄 Anders erklären" })).toBeVisible();

  await page.getByRole("button", { name: /Problem melden/ }).click();
  await expect(page.getByText("Was ist passiert?", { exact: false })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByText("Was ist passiert?", { exact: false })).toHaveCount(0);
});
