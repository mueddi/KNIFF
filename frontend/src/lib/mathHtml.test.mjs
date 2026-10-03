// Schnelle Tests der Formel-Darstellung, ohne Browser:
//   node --test src/lib/      (laeuft in CI im Job frontend-build)
// Jeder Fall ist ein Fehler, der am 3.10.2026 im Browser belegt wurde.
import { test } from "node:test";
import assert from "node:assert/strict";
import { buildHtml, linearToLatex } from "./mathHtml.js";

const pfade = (html) => [...html.matchAll(/<path d="([^"]*)"/g)].map((m) => m[1]);

test("Wurzelzeichen bleibt ganz (SVG-Pfad nie zerschnitten)", () => {
  for (const text of [
    "Rechne 11 ± sqrt(121+840)",
    "$\\sqrt{16} = 4$",
    "Erste Zeile\n$$x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}$$\nletzte Zeile",
    "$\\overrightarrow{AB}$ und $\\left(\\frac{1}{2}\\right)$",
  ]) {
    const html = buildHtml(text);
    const d = pfade(html);
    assert.ok(d.length > 0, `kein SVG-Pfad in: ${text}`);
    for (const p of d) assert.ok(!p.includes("<br"), `Pfad zerschnitten in: ${text}`);
  }
});

test("mehrzeilige Formel bleibt eine Formel, «- » darin wird keine Aufzaehlung", () => {
  const html = buildHtml("$$\\begin{aligned} x &= 1 \\\\\n- y &= 2 \\end{aligned}$$");
  assert.ok(!html.includes("mt-li"));
  assert.ok(!html.includes("katex-error"));
  assert.ok(html.includes("katex-display"));
});

test("Exponenten mit mehreren Zeichen werden ganz hochgestellt", () => {
  assert.equal(linearToLatex("2^10"), "2^{10}");
  assert.equal(linearToLatex("x^(n+1)"), "x^{n+1}");
  assert.equal(linearToLatex("e^-x"), "e^{-x}");
  assert.equal(linearToLatex("x^2"), "x^{2}");
  assert.ok(buildHtml("2^10 = 1024").includes("2^{10}"));
});

test("abgesetzte Formel: keine Leerzeile danach, kein verirrtes Leerzeichen", () => {
  const html = buildHtml("Also:\n$$x = 5$$\n Fertig.");
  assert.ok(!/katex-display">[\s\S]*?<\/span><\/span>(?:<br\/>)/.test(html.split("Fertig")[0].slice(-40)));
  assert.match(html, /<\/span>Fertig\.$/);
});

test("Bisheriges bleibt: Aufzaehlung, fett, nackte Gleichung, normaler Text", () => {
  const html = buildHtml("**Tipp:**\n- erster Punkt\n- zweiter\nLöse 3x + 5 = 20 auf Seite 3-4.");
  assert.equal((html.match(/mt-li/g) || []).length, 2);
  assert.ok(html.includes("<strong>Tipp:</strong>"));
  assert.ok(html.includes('class="katex"'), "3x + 5 = 20 wird als Formel gesetzt");
  assert.ok(html.includes("Seite 3-4"), "Seitenzahlen bleiben Text");
});

test("kein HTML aus Eingaben, Platzhalter-Zeichen im Text sind wirkungslos", () => {
  const html = buildHtml('<img src=x onerror=alert(1)> $<b>x</b>$ \u00000\u0000 \u00011\u0001');
  assert.ok(!html.includes("<img"));
  assert.ok(!html.includes("<b>"));
  assert.ok(!html.includes("\u0000") && !html.includes("\u0001"));
});
