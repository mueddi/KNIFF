import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useLang } from "./i18n.jsx";

// Alle Rueckfragen und Meldungen der App an EINER Stelle – im Design der App.
//
// Vorher standen an elf Stellen `window.confirm` / `window.alert` /
// `window.prompt`. Das sind Fenster des BROWSERS: sie haengen oben am
// Bildschirmrand, tragen den Vorspann «kniff.app sagt:»,
// benutzen die Schrift des Betriebssystems und ignorieren jede Gestaltung.
// Dazu kommen drei harte Grenzen, die uns hier wirklich weh taten:
//
//   1. Nicht uebersetzbar – die Knoepfe heissen immer «OK»/«Abbrechen» in der
//      Sprache des Systems, egal ob das Kind die App auf Deutsch benutzt.
//   2. Nicht gestaltbar – kein roter Loeschknopf, keine hervorgehobene
//      Empfehlung.
//   3. Nur ZWEI Antworten – genau deshalb waren in `Themen.jsx` drei
//      Browser-Fenster hintereinander noetig, um «archivieren oder loeschen?»
//      zu fragen.
//
// Deshalb: eine Funktion `frage(spec)`, die ein Promise zurueckgibt, plus vier
// duenne Huellen darum. Der Aufrufer schreibt weiterhin eine einzige
// `await`-Zeile, seine Ablauflogik bleibt unveraendert.

const DialogCtx = createContext(null);

export function useDialog() {
  return useContext(DialogCtx);
}

const UEBERLAGERUNG = {
  position: "fixed", inset: 0, background: "rgba(20,22,30,.45)",
  zIndex: 400, display: "grid", placeItems: "center", padding: 14,
};
const KARTE = {
  background: "#fff", borderRadius: 18, width: "min(420px, 100%)",
  padding: 20, boxShadow: "0 20px 60px rgba(20,22,30,.25)",
};
// Dieselben Knopf-Stile, die die App ueberall sonst benutzt – kein neues
// Aussehen erfinden, sondern das vorhandene wiederverwenden.
const KNOPF = { borderRadius: 11, padding: "10px 16px", fontSize: 13, fontWeight: 700, cursor: "pointer" };
const GEFAHR = { ...KNOPF, border: "none", background: "#b3492f", color: "#fff" };   // wie Einstellungen.jsx
const STILL = { ...KNOPF, border: "1px solid #e7e8ee", background: "#fff", color: "#6b7280", fontWeight: 600 };

export function DialogProvider({ children }) {
  const { t } = useLang();
  const [spec, setSpec] = useState(null);
  const [wert, setWert] = useState("");
  // Der Resolver liegt im ref, nicht im State: StrictMode rendert doppelt, und
  // ein Promise darf nur genau einmal aufgeloest werden.
  const antwort = useRef(null);
  const vorherFokus = useRef(null);
  const erstesFeld = useRef(null);

  const schliessen = useCallback((ergebnis) => {
    const fertig = antwort.current;
    antwort.current = null;
    setSpec(null);
    setWert("");
    // Fokus dorthin zurueck, wo er vor dem Dialog war – sonst steht die
    // Tastatur-Navigation nach dem Schliessen am Seitenanfang.
    //
    // ERST im naechsten Durchgang: gibt man den Fokus sofort zurueck, landet
    // der Rest DESSELBEN Tastendrucks (keypress/keyup) auf dem Knopf, der den
    // Dialog geoeffnet hat – der Dialog ging sofort wieder auf. Im Browser
    // nachgestellt, bevor es jemand zu spueren bekam.
    const zurueck = vorherFokus.current;
    vorherFokus.current = null;
    setTimeout(() => zurueck?.focus?.(), 0);
    fertig?.(ergebnis);
  }, []);

  const frage = useCallback((neu) => {
    // Zweiter Aufruf bei offenem Dialog: den ersten sauber als «abgebrochen»
    // aufloesen, statt ihn fuer immer haengen zu lassen.
    antwort.current?.(neu.abbruchWert ?? null);
    vorherFokus.current = document.activeElement;
    setWert(neu.wert || "");
    setSpec(neu);
    return new Promise((res) => { antwort.current = res; });
  }, []);

  useEffect(() => {
    if (!spec) return;
    // Fokus auf das Eingabefeld bzw. den bestaetigenden Knopf – ein
    // Browser-Dialog macht das von selbst, hier muessen wir es tun.
    const id = setTimeout(() => erstesFeld.current?.focus?.(), 0);
    const aufTaste = (e) => {
      if (e.key === "Escape") { e.preventDefault(); schliessen(spec.abbruchWert ?? null); }
    };
    document.addEventListener("keydown", aufTaste);
    return () => { clearTimeout(id); document.removeEventListener("keydown", aufTaste); };
  }, [spec, schliessen]);

  const api = {
    frage,
    // Ja/Nein – ersetzt window.confirm
    bestaetigen: (o) => frage({ ...o, art: "bestaetigen", abbruchWert: false }),
    // Mehrere Wege – das, was ein Browser-Dialog gar nicht kann
    wahl: (o) => frage({ ...o, art: "wahl", abbruchWert: null }),
    // Nur zur Kenntnis – ersetzt window.alert
    hinweis: (o) => frage({ ...o, art: "hinweis", abbruchWert: undefined }),
    // Text erfragen – ersetzt window.prompt
    eingabe: (o) => frage({ ...o, art: "eingabe", abbruchWert: null }),
  };

  // Handlungs-Knoepfe in der Reihenfolge, in der sie der Aufrufer nennt.
  const handlungen = [];
  if (spec?.art === "wahl") {
    for (const o of spec.optionen || []) {
      handlungen.push({ ...o, onClick: () => schliessen(o.id) });
    }
  } else if (spec?.art === "hinweis") {
    handlungen.push({ id: "ok", label: spec.bestaetigen || t("Alles klar", "Got it"), art: "primaer", onClick: () => schliessen(undefined) });
  } else if (spec) {
    handlungen.push({
      id: "ok",
      label: spec.bestaetigen || t("OK", "OK"),
      art: spec.gefahr ? "gefahr" : "primaer",
      onClick: () => schliessen(spec.art === "eingabe" ? wert.trim() : true),
      gesperrt: spec.art === "eingabe" && !wert.trim(),
    });
  }
  // «Abbrechen» steht links, die Handlungen rechts davon.
  const reihe = spec && spec.art !== "hinweis"
    ? [{ id: "abbrechen", label: spec.abbrechen || t("Abbrechen", "Cancel"), art: "still",
         onClick: () => schliessen(spec.abbruchWert ?? null) }, ...handlungen]
    : handlungen;
  // Fokus bekommt der empfohlene Weg (primaer), sonst die erste Handlung –
  // NIE ein roter Loeschknopf, den ein Druck auf die Leertaste ausloest.
  const fokusId = (handlungen.find((h) => h.art === "primaer" || !h.art) || handlungen[0])?.id;

  return (
    <DialogCtx.Provider value={api}>
      {children}
      {spec && (
        <div style={UEBERLAGERUNG} onClick={() => schliessen(spec.abbruchWert ?? null)}>
          <div
            className="popin"
            role="dialog"
            aria-modal="true"
            aria-label={spec.titel}
            onClick={(e) => e.stopPropagation()}
            style={KARTE}
          >
            <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: "-.01em" }}>{spec.titel}</div>
            {spec.text && (
              <div style={{ fontSize: 13.5, color: "#6b7280", lineHeight: 1.55, marginTop: 7, whiteSpace: "pre-wrap" }}>
                {spec.text}
              </div>
            )}
            {spec.art === "eingabe" && (
              <input
                ref={erstesFeld}
                value={wert}
                onChange={(e) => setWert(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key !== "Enter" || !wert.trim()) return;
                  e.preventDefault(); // sonst loest derselbe Druck den Knopf dahinter aus
                  schliessen(wert.trim());
                }}
                maxLength={120}
                style={{ width: "100%", marginTop: 12, border: "1px solid #d2d4dd", borderRadius: 10, padding: "10px 12px", fontSize: 14, outline: "none" }}
              />
            )}
            {/* Erklaerungen zu den Wegen – VOR den Knoepfen: man liest sie,
                bevor man sich entscheidet, nicht danach. */}
            {spec.art === "wahl" && (spec.optionen || []).some((o) => o.hinweis) && (
              <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 5 }}>
                {(spec.optionen || []).filter((o) => o.hinweis).map((o) => (
                  <div key={o.id} style={{ fontSize: 12.5, color: "#9aa0ab", lineHeight: 1.45 }}>
                    <b style={{ color: "#6b7280", fontWeight: 700 }}>{o.label}</b> – {o.hinweis}
                  </div>
                ))}
              </div>
            )}
            <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "flex-end", gap: 8, marginTop: 18 }}>
              {reihe.map((k) => {
                const stil = k.art === "gefahr" ? GEFAHR : k.art === "still" ? STILL : KNOPF;
                return (
                  <button
                    key={k.id}
                    // Fokus auf den empfohlenen Knopf, ausser bei einer
                    // Eingabe – dort gehoert er ins Feld.
                    ref={k.id === fokusId && spec.art !== "eingabe" ? erstesFeld : undefined}
                    onClick={k.onClick}
                    disabled={k.gesperrt}
                    className={k.art === "primaer" || !k.art ? "btn-primary" : undefined}
                    style={{ ...stil, ...(k.art === "primaer" || !k.art ? { border: "none" } : {}), opacity: k.gesperrt ? 0.5 : 1 }}
                  >
                    {k.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </DialogCtx.Provider>
  );
}
