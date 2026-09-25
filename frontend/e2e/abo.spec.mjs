// Kniff Plus aus Sicht der Kundschaft: zwei Token-Toepfe, und das Abo ist
// zu sehen, bevor die Probe zu Ende ist.
import { angemeldet, expect, keinAbsturzBildschirm, konto, mitAbo, test } from "./hilfen.mjs";

test("Laufendes Abo: Abo-Tokens und gekaufte Tokens getrennt, mit Verfall", async ({ page, request, fehler }) => {
  const k = await konto(request, { name: "Lia" });
  mitAbo(k.email, { tage: 20, gekauft: 40 });
  await angemeldet(page, k);
  await page.goto("/app/einstellungen?tab=abo");
  await expect(page.getByText("Abo-Tokens diesen Monat: 600 von 600")).toBeVisible();
  await expect(page.getByText(/gibt es wieder 600\. Was bis dann übrig ist, verfällt\./)).toBeVisible();
  await expect(page.getByText("Gekaufte Tokens: 40")).toBeVisible();
  await expect(page.getByText(/Verfallen nie/)).toBeVisible();
  // Seitenleiste: beide Toepfe zusammen
  await expect(page.getByText("✨ Kniff Plus · 640 Tokens")).toBeVisible();
  await keinAbsturzBildschirm(page);
});
