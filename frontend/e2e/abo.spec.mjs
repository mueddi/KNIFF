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

test("Waehrend der Probe ist Kniff Plus zu sehen, nicht erst danach", async ({ page, request, fehler }) => {
  const k = await konto(request);
  await angemeldet(page, k);
  await page.goto("/app/lernen");
  // Startbildschirm: Karte mit Stand der Probe, Preis und Weg zum Abo
  const karte = page.getByText("🎁 Noch 10 von 10 Gratis-Aufgaben").last();
  await expect(karte).toBeVisible();
  await expect(page.getByText(/Danach geht es mit Kniff Plus weiter: 600 Tokens jeden Monat/)).toBeVisible();
  await expect(page.getByText(/CHF 9\.90 im Monat/)).toBeVisible();
  // Seitenleiste: eigener Eintrag und Knopf unter dem Zaehler
  await expect(page.getByRole("button", { name: "✨ Kniff Plus ansehen" })).toBeVisible();
  await expect(page.getByText("✨ Kniff Plus", { exact: false }).first()).toBeVisible();
  await page.getByRole("button", { name: "Kniff Plus ansehen →" }).click();
  await expect(page).toHaveURL(/\/app\/preise/);
  await keinAbsturzBildschirm(page);
});

test("Handy: Kniff Plus steht oben, ohne das Menue zu oeffnen", async ({ page, request, fehler }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  const k = await konto(request);
  await angemeldet(page, k);
  await page.goto("/app/lernen");
  const chip = page.getByRole("button", { name: "🎁 10 gratis · ✨ Kniff Plus" });
  await expect(chip).toBeVisible();
  await chip.click();
  await expect(page).toHaveURL(/\/app\/preise/);
});

test("Mit laufendem Abo keine Werbung fuers Abo", async ({ page, request, fehler }) => {
  const k = await konto(request);
  mitAbo(k.email);
  await angemeldet(page, k);
  await page.goto("/app/lernen");
  await expect(page.getByText("✨ Kniff Plus · 600 Tokens")).toBeVisible();
  await expect(page.getByText(/Gratis-Aufgaben/)).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Kniff Plus ansehen/ })).toHaveCount(0);
});
