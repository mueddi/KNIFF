// Fehlerfaelle der Oberflaeche: Doppelklicks, gescheiterte Anfragen,
// Wegklicken mitten in einer Antwort. Jeder Fall war einmal still kaputt.
import { angemeldet, expect, keinAbsturzBildschirm, konto, test } from "./hilfen.mjs";

const API = "http://localhost:8000";

test("Thema: Enter und Klick legen es nur einmal an", async ({ page, request, fehler }) => {
  const k = await konto(request);
  await angemeldet(page, k);
  await page.goto("/app/themen");
  await page.getByText(/Neues Thema|\+ Thema/).first().click();
  const feld = page.getByPlaceholder("Themen-Name, z.B. Bruchrechnen");
  await feld.fill("Doppelt e2e");
  // Enter und Klick im selben Augenblick – bevor React neu zeichnet
  await page.evaluate(() => {
    const input = document.querySelector('input[placeholder="Themen-Name, z.B. Bruchrechnen"]');
    const knopf = [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Anlegen");
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    knopf.click();
  });
  await expect(page.getByText("Doppelt e2e").first()).toBeVisible();
  const themen = await (await request.get(`${API}/api/topics`, { headers: k.headers })).json();
  expect(themen.filter((x) => x.name === "Doppelt e2e")).toHaveLength(1);
});

test("Lernziele: scheitert das Speichern, steht es da", async ({ page, request, fehler }) => {
  const k = await konto(request);
  const thema = await (await request.post(`${API}/api/topics`, { headers: k.headers, data: { name: "Ziele e2e" } })).json();
  await angemeldet(page, k);
  await page.route(`**/api/topics/${thema.id}`, (route) =>
    route.request().method() === "PATCH"
      ? route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ detail: "Speichern abgelehnt (Test)" }) })
      : route.continue());
  await page.goto(`/app/themen/${thema.id}`);
  await page.getByRole("button", { name: /Ziele erfassen/ }).click();
  await page.locator("textarea").first().fill("Kürzen");
  await page.getByRole("button", { name: /Speichern/ }).click();
  await expect(page.getByText("Speichern abgelehnt (Test)")).toBeVisible();
});

test("Einladungscode: scheitert das Kopieren, sagt die App es", async ({ page, request, fehler }) => {
  const k = await konto(request);
  await angemeldet(page, k);
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: () => Promise.reject(new Error("verboten")) }, configurable: true,
    });
  });
  await page.goto("/app/eltern");
  await page.getByRole("button", { name: "Code kopieren" }).click();
  await expect(page.getByRole("button", { name: "Bitte von Hand abschreiben" })).toBeVisible();
  await expect(page.getByRole("button", { name: "kopiert ✓" })).toHaveCount(0);
});

test("Einladungscode: Kopieren klappt und meldet es", async ({ page, context, request, fehler }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const k = await konto(request);
  await angemeldet(page, k);
  await page.goto("/app/eltern");
  await page.getByRole("button", { name: "Code kopieren" }).click();
  await expect(page.getByRole("button", { name: "kopiert ✓" })).toBeVisible();
});

test("Mitten in der Antwort wegklicken: kein Absturz, keine Fehler", async ({ page, request, fehler }) => {
  const k = await konto(request);
  const ex = await (await request.post(`${API}/api/exercises`, { headers: k.headers, data: { text: "3x + 5 = 20" } })).json();
  const st = await (await request.post(`${API}/api/exercises/${ex.id}/attempts`, { headers: k.headers })).json();
  await angemeldet(page, k);
  // Die Antwort kuenstlich verzoegern, damit das Wegklicken sicher mittendrin passiert
  await page.route("**/api/attempts/*/chat", async (route) => {
    await new Promise((r) => setTimeout(r, 1500));
    await route.continue();
  });
  await page.goto(`/app/lernen/${st.attempt.id}`);
  const eingabe = page.getByPlaceholder("Schreib deinen nächsten Schritt …");
  await eingabe.fill("x = 5");
  await eingabe.press("Enter");
  await page.goto("/app/themen");
  await page.waitForTimeout(3000); // hier kam frueher die Antwort in einen toten Bildschirm
  await keinAbsturzBildschirm(page);
  // Zurueck: das Gespraech ist da, die App steht
  await page.goto(`/app/lernen/${st.attempt.id}`);
  await expect(eingabe).toBeVisible();
});
