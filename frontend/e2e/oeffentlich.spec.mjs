// Oeffentliche Seiten: was jede Besucherin ohne Konto sieht.
import { expect, keinAbsturzBildschirm, test } from "./hilfen.mjs";

test("Startseite laedt und zeigt Kniff Plus mit den Zahlen vom Server", async ({ page, fehler }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Mathe verstehen");
  await expect(page.getByText("Gratis probieren. Dann weiterüben mit Kniff Plus.")).toBeVisible();
  await expect(page.getByText(/600 Tokens im Monat/).first()).toBeVisible();
  await expect(page.getByText("CHF 9.90", { exact: true })).toBeVisible();
  await keinAbsturzBildschirm(page);
});

test("Probier-Chat laesst sich bis zur Loesung durchklicken und neu starten", async ({ page, fehler }) => {
  await page.goto("/");
  const chat = page.locator(".landing-chip");
  for (let i = 0; i < 8; i += 1) {
    if (await page.getByRole("button", { name: /Nochmal/ }).isVisible()) break;
    await chat.first().click();
    await page.waitForTimeout(1100); // Kniff "tippt"
  }
  await expect(page.getByText("x = 5 – richtig.")).toBeVisible();
  await expect(page.getByRole("link", { name: /Jetzt selbst üben/ })).toBeVisible();
  await page.getByRole("button", { name: /Nochmal/ }).click();
  await expect(page.getByText("Wo würdest du anfangen?")).toBeVisible();
  // Betteln bringt eine Frage, keine Loesung
  await page.getByRole("button", { name: "sag mir einfach die lösung" }).click();
  await expect(page.getByText(/Netter Versuch/)).toBeVisible();
  await expect(page.getByText("x = 5 – richtig.")).toHaveCount(0);
});

test("Stufen-Reiter und Monat/Jahr-Umschalter reagieren", async ({ page, fehler }) => {
  await page.goto("/");
  await page.getByRole("tab", { name: /Gymnasium/ }).click();
  await expect(page.getByText(/Extremstellen/)).toBeVisible();
  await page.getByRole("tab", { name: /Mittelstufe/ }).click();
  await expect(page.getByText(/Sackgeld/).first()).toBeVisible();
  await page.getByRole("button", { name: "Jährlich" }).click();
  await expect(page.getByText("CHF 89.–")).toBeVisible();
  await expect(page.getByText(/gespart/)).toBeVisible();
  await page.getByText("Was kostet Kniff?").click();
  await expect(page.getByText(/unverbrauchte Tokens bleiben/).first()).toBeVisible();
});

test("Englisch umschalten uebersetzt die Startseite", async ({ page, fehler }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "EN", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Understand maths");
  await page.getByRole("button", { name: "DE", exact: true }).click();
});

for (const [pfad, titel] of [["/agb", "AGB"], ["/datenschutz", "Datenschutzerklärung"], ["/impressum", "Impressum"]]) {
  test(`Rechtliches: ${pfad} ist erreichbar`, async ({ page, fehler }) => {
    await page.goto(pfad);
    await expect(page.getByText(titel).first()).toBeVisible();
    await keinAbsturzBildschirm(page);
  });
}

test("AGB beschreiben das Abo mit Tokens und Paketen", async ({ page, fehler }) => {
  await page.goto("/agb");
  await expect(page.getByText(/Kniff Plus: CHF 9.90 pro Monat/)).toBeVisible();
  await expect(page.getByText(/600 Tokens pro Monat/)).toBeVisible();
});

test("Unbekannte Adresse zeigt eine Seite statt eines Absturzes", async ({ page, fehler }) => {
  await page.goto("/gibt-es-nicht");
  await keinAbsturzBildschirm(page);
  await expect(page.locator("body")).not.toBeEmpty();
});

test("Anmeldeseite: falsches Passwort zeigt eine Meldung", async ({ page, fehler }) => {
  await page.goto("/login");
  await page.getByPlaceholder("du@schule.ch").fill("niemand@test.ch");
  await page.getByPlaceholder("dein Passwort").fill("falsch-falsch-1");
  await page.getByRole("button", { name: "Anmelden", exact: true }).last().click();
  await expect(page.getByText(/falsch/i).first()).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
});
