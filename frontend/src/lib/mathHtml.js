// Formeln und Text -> sicheres HTML. Ohne React und ohne CSS, damit es auch
// ausserhalb des Browsers testbar ist: node --test src/lib/ (mathHtml.test.mjs).
import katex from "katex";

const escapeHtml = (s) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// Minimales, sicheres Markdown auf bereits ESCAPETEM Text:
// **fett** -> <strong>, *kursiv* -> <em> (nur wenn kein Leerzeichen an den
// Raendern – so bleibt 3*x*2 unangetastet). Mehr Markdown gibt es bewusst
// nicht; der Tutor-Prompt verbietet Titel/Tabellen.
function inlineMarkdown(escaped) {
  return escaped
    .replace(/\*\*([^*\n]+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^\s*][^*\n]*?[^\s*]|[^\s*])\*(?=[\s.,:;!?)]|$)/gm, "$1<em>$2</em>");
}

// Lineare Schreibweise -> LaTeX, damit KaTeX sie schoen setzt:
// 3*x -> 3·x, 1/2 -> Bruch, sqrt(16) -> Wurzel, <= / >= / != -> ≤ ≥ ≠.
// Wird NICHT angewendet, wenn der Ausdruck schon echtes LaTeX ist (Backslash).
export function linearToLatex(src) {
  let s = src;
  s = s.replace(/sqrt\(([^()]*(?:\([^()]*\)[^()]*)*)\)/gi, "\\sqrt{$1}");
  // Exponenten mit mehr als einem Zeichen klammern – KaTeX hebt sonst nur
  // das naechste Zeichen hoch: 2^10 wurde «2¹0», x^(n+1) «x^( n+1)».
  s = s.replace(/\^\(([^()]*)\)/g, "^{$1}");
  s = s.replace(/\^(-?\d+(?:[.,]\d+)?)/g, "^{$1}");
  s = s.replace(/\^-([a-zA-Z])/g, "^{-$1}");
  // einfache Brueche: Zahl/Variable/geklammerte Gruppe auf beiden Seiten
  const tok = "(\\([^()]+\\)|\\d+(?:[.,]\\d+)?|[a-zA-Z])";
  const strip = (t) => (t.startsWith("(") && t.endsWith(")") ? t.slice(1, -1) : t);
  s = s.replace(
    new RegExp(`${tok}\\s*/\\s*${tok}`, "g"),
    (_, a, b) => `\\frac{${strip(a)}}{${strip(b)}}`
  );
  s = s.replace(/<=/g, "\\le ").replace(/>=/g, "\\ge ").replace(/!=/g, "\\ne ");
  s = s.replace(/\*/g, "\\cdot ");
  return s;
}

// Alles andere bleibt normaler Text. Robust gegen KaTeX-Fehler.
function renderMath(src, displayMode) {
  try {
    return katex.renderToString(src, { throwOnError: false, displayMode });
  } catch {
    // Wirft KaTeX doch (nicht-Parse-Fehler), den Rohtext ESCAPEN – niemals
    // ungefiltert als HTML einsetzen (sonst XSS ueber $...$-Nutzereingaben).
    return escapeHtml(src);
  }
}

// Sieht ein Kandidat wirklich nach Mathe aus? Konservativ, damit normaler
// Text («Seite 3-4», «Klasse 2», Jahreszahlen) niemals als Formel endet.
function isMathy(c) {
  if (/[=<>]/.test(c)) return true; // Gleichung/Ungleichung
  if (/[*/^]/.test(c)) return true; // 3*4, 1/2, x^2
  if (/sqrt\(/i.test(c)) return true;
  if (/[+\-]/.test(c) && /\d[a-zA-Z]|[a-zA-Z]\d/.test(c)) return true; // 3x + 5
  return false;
}

// Text-Chunk OHNE echte Woerter: nackte Mathe-Ausdruecke finden und rendern.
function scanChunk(chunk, keep) {
  const re = /[0-9a-zA-Z(][0-9a-zA-Z+\-*/^=<>()., ]*/g;
  let out = "";
  let last = 0;
  let m;
  while ((m = re.exec(chunk)) !== null) {
    // Satzzeichen/haengende Operatoren am Ende gehoeren nicht in die Formel
    const cand = m[0].replace(/[\s.,:;*+\-/^=<>]+$/g, "");
    if (cand && isMathy(cand)) {
      out += escapeHtml(chunk.slice(last, m.index));
      out += keep(renderMath(linearToLatex(cand), false));
      out += escapeHtml(m[0].slice(cand.length));
    } else {
      out += escapeHtml(chunk.slice(last, m.index) + m[0]);
    }
    last = re.lastIndex;
  }
  return out + escapeHtml(chunk.slice(last));
}

// Textsegment (ausserhalb $...$): Woerter (>=3 Buchstaben) bleiben Text,
// dazwischen wird nach nackter Mathe gesucht. «sqrt» zaehlt nicht als Wort.
function plainSegment(raw, keep) {
  const parts = raw.split(/(\b(?!sqrt\b)[A-Za-zÀ-ÿ]{3,}\b)/);
  let out = "";
  for (let i = 0; i < parts.length; i++) {
    out += i % 2 === 1 ? escapeHtml(parts[i]) : scanChunk(parts[i], keep);
  }
  return out;
}

// Zeilen-Nachbearbeitung: Leerzeile -> Absatz-Abstand, «- …» -> Aufzaehlung.
function withLines(html) {
  const out = [];
  for (const line of html.split("\n")) {
    const t = line.trim();
    if (t === "") {
      out.push('<span class="mt-par"></span>');
      continue;
    }
    const li = t.match(/^-\s+([\s\S]*)$/);
    if (li) {
      out.push(`<span class="mt-li">${li[1]}</span>`);
      continue;
    }
    out.push(line + "<br/>");
  }
  return out
    .join("")
    .replace(/<br\/>(<span class="mt-(?:par|li))/g, "$1") // kein Doppelabstand vor Bloecken
    .replace(/(<span class="mt-par"><\/span>){2,}/g, "$1") // mehrere Leerzeilen = 1 Absatz
    .replace(/(?:<br\/>)+$/g, "");
}

// Rendert Text mit eingebetteten Formeln. Erkennt:
//   $...$  und  \(...\)  -> inline
//   $$...$$ und \[...\]  -> display
// plus Auto-Erkennung nackter Mathe (3x + 5 = 20) im normalen Text.
//
// Fertiges KaTeX-HTML wird NIE von withLines/inlineMarkdown angefasst: es
// kommt als Platzhalter durch die Text-Verarbeitung und erst am Schluss
// zurueck. Frueher schnitt withLines an jedem Zeilenumbruch – auch mitten in
// KaTeX' SVG-Pfaden (Wurzelzeichen, grosse Klammern, Pfeile) und in
// mehrzeiligen Formeln. Folge: jedes √ verschwand, aus √16 = 4 wurde 16 = 4.
const P = "\u0000"; // Platzhalter Inline-Formel – kommt in Text nicht vor
const D = "\u0001"; // Platzhalter abgesetzte Formel (eigener Block)
export function buildHtml(text) {
  if (!text) return "";
  const store = [];
  const keep = (html, mark = P) => `${mark}${store.push(html) - 1}${mark}`;
  const parts = [];
  const regex = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\$([^$\n]+?)\$|\\\(([\s\S]+?)\\\)/g;
  const src = text.replace(/[\u0000\u0001]/g, "");
  let last = 0;
  let m;
  while ((m = regex.exec(src)) !== null) {
    if (m.index > last) parts.push(plainSegment(src.slice(last, m.index), keep));
    const display = m[1] !== undefined || m[2] !== undefined;
    const body = m[1] ?? m[2] ?? m[3] ?? m[4] ?? "";
    const html = renderMath(body.includes("\\") ? body : linearToLatex(body), display);
    parts.push(keep(html, display ? D : P));
    last = regex.lastIndex;
  }
  if (last < src.length) parts.push(plainSegment(src.slice(last), keep));
  const html = withLines(inlineMarkdown(parts.join("")))
    // Eine abgesetzte Formel ist selbst ein Block: kein Zeilenumbruch davor
    // oder danach (gaebe eine leere Zeile), kein verirrtes Leerzeichen danach.
    .replace(/<br\/>(\u0001\d+\u0001)/g, "$1")
    .replace(/(\u0001\d+\u0001)(?:<br\/>)?[ \t]*/g, "$1");
  return html.replace(/[\u0000\u0001](\d+)[\u0000\u0001]/g, (_, i) => store[+i]);
}
