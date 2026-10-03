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
