// Schmaler API-Client. Basis-URL aus VITE_API_BASE (leer = Vite-Dev-Proxy).
// Sprache fuer Backend-Fehlermeldungen VOR dem Login (X-Lang-Header);
// nach dem Login zaehlt das Profil serverseitig.
import { detectLang as currentLang } from "./sprache.js";

const BASE = import.meta.env.VITE_API_BASE || "";

let token = localStorage.getItem("sw_token") || null;

export function setToken(t) {
  token = t;
  if (t) localStorage.setItem("sw_token", t);
  else localStorage.removeItem("sw_token");
}
export function getToken() {
  return token;
}

let onUnauthorized = null;
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}


function headers(extra = {}) {
  const h = { "Content-Type": "application/json", "X-Lang": currentLang(), ...extra };
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

// Ein 401 heisst zweierlei, und der Unterschied ist fuer den Benutzer alles:
// entweder ist eine bestehende Anmeldung abgelaufen – dann muss der Token weg
// und die App zum Login springen. Oder der Anmeldeversuch SELBST ist
// gescheitert. Im zweiten Fall gehoert die Meldung des Servers auf den Schirm
// ("E-Mail oder Passwort falsch"); frueher schluckte der Client sie und zeigte
// stattdessen "Sitzung abgelaufen" – wer sich vertippte, dachte, die App sei
// kaputt. Diese Wege verlangen keine Anmeldung, ihr 401 ist nie ein Ablauf:
const OFFENE_WEGE = /\/api\/auth\/(login|register|request-link|verify|verify-supabase)(\?|$)/;

async function handle(res) {
  if (res.status === 401 && !OFFENE_WEGE.test(res.url || "")) {
    setToken(null);
    onUnauthorized?.();
    throw new Error("Sitzung abgelaufen – bitte neu anmelden.");
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = data?.detail || data?.message || `Fehler ${res.status}`;
    const err = new Error(typeof msg === "string" ? msg : "Unbekannter Fehler");
    err.status = res.status; // z.B. 402 = Kontingent aufgebraucht -> Kauf-Hinweis
    err.grund = res.headers.get("x-kniff-grund") || null; // trial | fairuse | guthaben
    throw err;
  }
  return data;
}

export const api = {
  base: BASE,
  get: (path) => fetch(`${BASE}${path}`, { headers: headers() }).then(handle),
  post: (path, body) =>
    fetch(`${BASE}${path}`, { method: "POST", headers: headers(), body: JSON.stringify(body || {}) }).then(handle),
  patch: (path, body) =>
    fetch(`${BASE}${path}`, { method: "PATCH", headers: headers(), body: JSON.stringify(body || {}) }).then(handle),
  del: (path) => fetch(`${BASE}${path}`, { method: "DELETE", headers: headers() }).then(handle),
  // multipart-Upload (Foto)
  upload: (path, formData) =>
    fetch(`${BASE}${path}`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    }).then(handle),
};
