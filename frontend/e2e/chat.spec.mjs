// Der Chat selbst: Formeln, Eingabe, Handy-Ansicht.
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
