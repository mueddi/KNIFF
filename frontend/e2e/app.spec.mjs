// Die App fuer Angemeldete: Registrieren, ueben, jede Seite, Admin, Eltern.
import { angemeldet, expect, keinAbsturzBildschirm, konto, test, zumAdmin } from "./hilfen.mjs";

test("Registrieren ueber das Formular, Aufgabe anlegen, im Chat antworten", async ({ page, fehler }) => {
  const email = `e2e-formular-${Date.now()}@test.ch`;
  await page.goto("/login");
  await page.getByRole("button", { name: "Neu hier" }).click();
  await page.getByPlaceholder("z.B. Mia").fill("Mia");
  await page.getByRole("button", { name: /Oberstufe/ }).first().click();
  await page.getByPlaceholder("du@schule.ch").fill(email);
  await page.getByPlaceholder("mindestens 8 Zeichen").fill("e2e-passwort-123");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Konto erstellen" }).click();
  await expect(page).toHaveURL(/\/app\/lernen/);
  // steht in der Seitenleiste und auf der Karte des Startbildschirms
  await expect(page.getByText(/10 von 10 Gratis-Aufgaben|Noch 10 von 10/).first()).toBeVisible();

  await page.getByRole("button", { name: "+ Neue Aufgabe" }).or(page.getByText("+ Neue Aufgabe")).first().click();
  await page.getByPlaceholder("z.B. Löse nach x auf: 3x + 5 = 20").fill("Löse nach x auf: 3x + 5 = 20");
  await page.getByRole("button", { name: /Loslegen/ }).click();

  const eingabe = page.getByPlaceholder("Schreib deinen nächsten Schritt …");
  await expect(eingabe).toBeVisible();
  await expect(page.getByText("Noch 9 von 10", { exact: false })).toBeVisible();
  const vorher = await page.locator("body").innerText();
  await eingabe.fill("x = 5");
  await eingabe.press("Enter");
  // Die eigene Nachricht erscheint (als Formel gesetzt) und das Feld ist leer
  await expect(eingabe).toHaveValue("");
  // Der (Mock-)Tutor antwortet – die Seite waechst um eine Antwort
  await expect.poll(async () => (await page.locator("body").innerText()).length, { timeout: 15_000 })
    .toBeGreaterThan(vorher.length + 10);
  await keinAbsturzBildschirm(page);
});

const SCHUELER_SEITEN = [
  "/app/lernen", "/app/themen", "/app/bibliothek", "/app/eltern",
  "/app/preise", "/app/einstellungen", "/app/einstellungen?tab=abo",
];

test("Jede Schueler-Seite laedt ohne Fehler", async ({ page, request, fehler }) => {
  const k = await konto(request, { name: "Leo" });
  await angemeldet(page, k);
  for (const pfad of SCHUELER_SEITEN) {
    await page.goto(pfad);
    await page.waitForLoadState("networkidle");
    await keinAbsturzBildschirm(page);
    await expect(page.getByText("Leo").first(), `Seitenleiste fehlt auf ${pfad}`).toBeVisible();
  }
});

test("Preise nach Rueckkehr von Stripe: keine Endlosschleife", async ({ page, request, fehler }) => {
  // Regression vom 21.9.: ?zahlung=ok lud das Kontingent alle 2.5 s neu, ewig.
  const k = await konto(request);
  await angemeldet(page, k);
  let anfragen = 0;
  page.on("request", (r) => { if (r.url().includes("/api/quota")) anfragen += 1; });
  await page.goto("/app/preise?zahlung=ok");
  await expect(page.getByText(/Zahlung erhalten/)).toBeVisible();
  await page.waitForTimeout(10_000);
  // Normal: 1× beim Laden + 2× nachgeladen (nach 2.5 s und 8 s) = 3
  expect(anfragen, "zu viele /api/quota-Anfragen").toBeLessThanOrEqual(3);
});

test("Thema anlegen und wiederfinden", async ({ page, request, fehler }) => {
  const k = await konto(request);
  const r = await request.post("http://localhost:8000/api/topics", {
    headers: k.headers, data: { name: "Brüche e2e", learning_goals: "Kürzen\nErweitern" },
  });
  expect(r.status()).toBeLessThan(300);
  await angemeldet(page, k);
  await page.goto("/app/themen");
  await expect(page.getByText("Brüche e2e").first()).toBeVisible();
  await page.getByText("Brüche e2e").first().click();
  await keinAbsturzBildschirm(page);
});

test("Probe aufgebraucht: die App bietet Kniff Plus an statt abzustuerzen", async ({ page, request, fehler }) => {
  const k = await konto(request);
  for (let i = 0; i < 10; i += 1) {
    const ex = await (await request.post("http://localhost:8000/api/exercises", {
      headers: k.headers, data: { text: `${i + 2}x = ${2 * (i + 2)}` },
    })).json();
    await request.post(`http://localhost:8000/api/exercises/${ex.id}/attempts`, { headers: k.headers });
  }
  await angemeldet(page, k);
  await page.goto("/app/lernen");
  await expect(page.getByText(/Probe aufgebraucht/)).toBeVisible();
  await page.getByText("+ Neue Aufgabe").first().click();
  await page.getByPlaceholder("z.B. Löse nach x auf: 3x + 5 = 20").fill("2x = 8");
  await page.getByRole("button", { name: /Loslegen/ }).click();
  await expect(page.getByText(/Gratis-Aufgaben sind aufgebraucht/).first()).toBeVisible();
  await expect(page.getByRole("button", { name: /Kniff Plus aktivieren/ }).first()).toBeVisible();
});

test("Admin sieht alle Admin-Seiten ohne Fehler", async ({ page, request, fehler }) => {
  const k = await konto(request, { name: "Chef" });
  zumAdmin(k.email);
  await request.post("http://localhost:8000/api/feedback", { headers: k.headers, data: { text: "Bitte mehr Geometrie" } });
  await angemeldet(page, k);
  for (const pfad of ["/app/kosten", "/app/stoerungen", "/app/rueckmeldungen", "/app/nutzer", "/app/elternansicht"]) {
    await page.goto(pfad);
    await page.waitForLoadState("networkidle");
    await keinAbsturzBildschirm(page);
  }
  await page.goto("/app/rueckmeldungen");
  await expect(page.getByText("«Bitte mehr Geometrie»")).toBeVisible();
});

test("Schueler kommt nicht in den Admin-Bereich", async ({ page, request, fehler }) => {
  const k = await konto(request);
  await angemeldet(page, k);
  await page.goto("/app/kosten");
  await expect(page).toHaveURL(/\/app\/lernen/);
});

test("Eltern: Kind verknuepfen und Stand sehen", async ({ page, request, fehler }) => {
  const kind = await konto(request, { name: "Nina" });
  const eltern = await konto(request, { rolle: "parent", name: "Mami" });
  const code = (await (await request.get("http://localhost:8000/api/parents/invite", { headers: kind.headers })).json()).invite_code;
  expect(code).toBeTruthy();
  await angemeldet(page, eltern);
  await page.goto("/eltern");
  await page.waitForLoadState("networkidle");
  await keinAbsturzBildschirm(page);
  const feld = page.locator("input").first();
  await feld.fill(code);
  await feld.press("Enter");
  await expect(page.getByText("Nina").first()).toBeVisible();
  await expect(page.getByText(/Gratis-Aufgaben/).first()).toBeVisible();
});

test("Abmelden fuehrt zur Anmeldung und schuetzt die App", async ({ page, request, fehler }) => {
  const k = await konto(request, { name: "Tim" });
  await angemeldet(page, k);
  await page.goto("/app/einstellungen");
  await page.getByRole("button", { name: /Abmelden/ }).or(page.getByText(/Abmelden/)).first().click();
  await expect(page).toHaveURL(/\/login/);
});
