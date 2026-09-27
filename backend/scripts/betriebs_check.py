"""Betriebs-Check: stimmt alles RUND UM den Code?

Die teuersten Fehler bis Ende September lagen nicht im Code, sondern in
Einstellungen, die kein Test sieht: der Stripe-Webhook war nie eingerichtet,
die Mail-Links zeigten auf die tote alte Adresse, `www` hatte keinen
DNS-Eintrag, BACKUP_PASSWORD fehlte (die Sicherungen lagen unverschluesselt
in einem oeffentlichen Repository), und ein roter Deploy blieb zwoelf Tage
unbemerkt. Jede dieser Luecken prueft dieses Skript – taeglich und nach
jedem Deploy (.github/workflows/betriebs-check.yml).

Drei Stufen je Befund:
    fehler   -> Lauf rot, GitHub schickt eine Mail
    warnung  -> steht im Bericht, Lauf bleibt gruen
    ok

Die Pruef-Funktionen sind rein (bekommen fertige Daten, rechnen nichts
nach aussen) und damit testbar: backend/tests/test_betriebs_check.py.
Ausgegeben werden nur Namen und Zustaende, nie Werte von Secrets.

    GITHUB_TOKEN=... GITHUB_REPOSITORY=mueddi/KNIFF python scripts/betriebs_check.py
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

LIVE = "https://kniff.app"
WEBHOOK_URL = f"{LIVE}/api/pay/webhook"
SUPABASE_PRODUKTION = "bogrqbazqjvjpahuecon"

# Was der Webhook melden muss (routers/pay.py kennt genau diese).
WEBHOOK_EREIGNISSE = (
    "checkout.session.completed",
    "invoice.paid",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "charge.refunded",
    "charge.dispute.created",
)

# Secret -> (Pflicht?, wofuer). Der Workflow reicht nur «gesetzt ja/nein»
# herein (HAT_<NAME>=true/false), nie den Wert.
SECRETS = {
    "DATABASE_URL": (True, "Sicherung, Zahlungs-Abgleich"),
    "BACKUP_PASSWORD": (True, "verschluesselt die Sicherung"),
    "VERCEL_TOKEN": (True, "Deploy"),
    "RUNTIME_ENV_JSON": (True, "Einstellungen der Produktion beim Deploy"),
    "STRIPE_ABGLEICH_KEY": (True, "taeglicher Zahlungs-Abgleich und Webhook-Pruefung"),
    "SUPABASE_ACCESS_TOKEN": (True, "Vorschau-Datenbank und Supabase-Pruefung"),
    "VERCEL_AUTOMATION_BYPASS_SECRET": (False, "gestufter Deploy: erst pruefen, dann live"),
    "STRIPE_TEST_SECRET_KEY": (False, "Test gegen echten Stripe-Testmodus"),
}

BACKUP_MAX_TAGE = 8


@dataclass(frozen=True)
class Befund:
    bereich: str
    stufe: str  # "ok" | "warnung" | "fehler"
    text: str


# ---------- Pruefungen (rein) ----------

def pruefe_repo(repo: dict | None) -> Befund:
    if repo is None:
        return Befund("Repository", "warnung", "Sichtbarkeit nicht abrufbar.")
    if repo.get("private"):
        return Befund("Repository", "ok", "privat")
    return Befund("Repository", "fehler",
                  "ÖFFENTLICH – jede Person mit GitHub-Konto kann Code und Artefakte der Abläufe "
                  "(z.B. Sicherungen) herunterladen. Settings → General → Danger Zone → Make private.")


def pruefe_secrets(gesetzt: dict[str, bool]) -> list[Befund]:
    aus = []
    for name, (pflicht, wofuer) in SECRETS.items():
        if gesetzt.get(name):
            aus.append(Befund(f"Secret {name}", "ok", "gesetzt"))
        else:
            aus.append(Befund(f"Secret {name}", "fehler" if pflicht else "warnung",
                              f"fehlt – nötig für: {wofuer}"))
    return aus


def pruefe_webhook(endpunkte: list[dict] | None) -> Befund:
    if endpunkte is None:
        return Befund("Stripe-Webhook", "warnung",
                      "nicht prüfbar (STRIPE_ABGLEICH_KEY fehlt oder darf «Webhook Endpoints» nicht lesen).")
    passend = [e for e in endpunkte if (e.get("url") or "").rstrip("/") == WEBHOOK_URL]
    if not passend:
        return Befund("Stripe-Webhook", "fehler",
                      f"kein Endpunkt auf {WEBHOOK_URL} – Käufe würden nie gutgeschrieben.")
    aktiv = [e for e in passend if e.get("status") == "enabled"]
    if not aktiv:
        return Befund("Stripe-Webhook", "fehler", f"Endpunkt {WEBHOOK_URL} ist deaktiviert.")
    ereignisse = set()
    for e in aktiv:
        ereignisse |= set(e.get("enabled_events") or [])
    if "*" in ereignisse:
        return Befund("Stripe-Webhook", "ok", "aktiv, alle Ereignisse")
    fehlen = [x for x in WEBHOOK_EREIGNISSE if x not in ereignisse]
    if fehlen:
        return Befund("Stripe-Webhook", "fehler", "es fehlen die Ereignisse: " + ", ".join(fehlen))
    return Befund("Stripe-Webhook", "ok", f"aktiv, alle {len(WEBHOOK_EREIGNISSE)} Ereignisse")


def pruefe_supabase_auth(cfg: dict | None) -> Befund:
    if cfg is None:
        return Befund("Supabase Mail-Links", "warnung", "nicht prüfbar (SUPABASE_ACCESS_TOKEN fehlt oder ungültig).")
    site = (cfg.get("site_url") or "").rstrip("/")
    erlaubt = [u.strip() for u in (cfg.get("uri_allow_list") or "").split(",") if u.strip()]
    if site != LIVE:
        return Befund("Supabase Mail-Links", "fehler",
                      f"Site URL ist «{site or 'leer'}» statt {LIVE} – Bestätigungs-Links führen ins Leere. "
                      "Supabase → Authentication → URL Configuration.")
    if not any(u.startswith(LIVE) for u in erlaubt):
        return Befund("Supabase Mail-Links", "fehler",
                      f"{LIVE}/** steht nicht in den Redirect URLs – Links aus Mails werden abgewiesen.")
    return Befund("Supabase Mail-Links", "ok", f"Site URL {LIVE}, Weiterleitung erlaubt")


def pruefe_dns(www: list[str] | None, mx: list[str] | None) -> list[Befund]:
    aus = []
    if www is None:
        aus.append(Befund("DNS www.kniff.app", "warnung", "nicht abfragbar"))
    elif www:
        aus.append(Befund("DNS www.kniff.app", "ok", "eingetragen"))
    else:
        aus.append(Befund("DNS www.kniff.app", "fehler", "kein Eintrag – www.kniff.app ist nicht erreichbar."))
    if mx is None:
        aus.append(Befund("DNS Mail (MX)", "warnung", "nicht abfragbar"))
    elif mx:
        aus.append(Befund("DNS Mail (MX)", "ok", "Mails an @kniff.app werden zugestellt"))
    else:
        aus.append(Befund("DNS Mail (MX)", "warnung",
                          "kein MX-Eintrag – Mails an @kniff.app (z.B. hi@kniff.app) kommen zurück."))
    return aus


def pruefe_health(status_code: int | None, body: dict | None) -> Befund:
    if status_code is None:
        return Befund("kniff.app", "fehler", "nicht erreichbar")
    if status_code == 200 and (body or {}).get("status") == "ok":
        return Befund("kniff.app", "ok", "/api/health meldet «ok»")
    return Befund("kniff.app", "fehler", f"/api/health antwortet {status_code} ohne «ok»")


def pruefe_letzten_lauf(name: str, laeufe: list[dict] | None, jetzt: datetime,
                        max_alter_tage: int | None = None, pflicht: bool = True) -> Befund:
    """Letzter abgeschlossener Lauf auf main gruen? Optional: letzter gruener
    nicht aelter als max_alter_tage."""
    if laeufe is None:
        return Befund(name, "warnung", "Läufe nicht abrufbar")
    fertig = [r for r in laeufe if r.get("status") == "completed"]
    if not fertig:
        return Befund(name, "fehler" if pflicht else "warnung", "noch nie gelaufen")
    letzter = fertig[0]
    if letzter.get("conclusion") != "success":
        wann = (letzter.get("created_at") or "")[:10]
        return Befund(name, "fehler", f"letzter Lauf ({wann}) ist ROT: {letzter.get('html_url', '')}")
    if max_alter_tage is not None:
        gruen = datetime.fromisoformat(letzter["created_at"].replace("Z", "+00:00"))
        if jetzt - gruen > timedelta(days=max_alter_tage):
            return Befund(name, "fehler", f"letzter grüner Lauf ist {(jetzt - gruen).days} Tage alt")
    return Befund(name, "ok", f"letzter Lauf grün ({(letzter.get('created_at') or '')[:10]})")


def bericht(befunde: list[Befund]) -> str:
    zeichen = {"ok": "✅", "warnung": "⚠️", "fehler": "❌"}
    n = {s: sum(b.stufe == s for b in befunde) for s in zeichen}
    zeilen = ["## Betriebs-Check", "",
              f"**{n['fehler']} Fehler · {n['warnung']} Warnungen · {n['ok']} in Ordnung**", "",
              "| | Bereich | Befund |", "|---|---|---|"]
    reihenfolge = {"fehler": 0, "warnung": 1, "ok": 2}
    for b in sorted(befunde, key=lambda b: reihenfolge[b.stufe]):
        zeilen.append(f"| {zeichen[b.stufe]} | {b.bereich} | {b.text.replace('|', '/')} |")
    return "\n".join(zeilen)


# ---------- Daten holen ----------

def _json(url: str, **kw) -> tuple[int | None, dict | list | None]:
    try:
        r = httpx.get(url, timeout=20, follow_redirects=True, **kw)
    except httpx.HTTPError:
        return None, None
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, None


def _dns(name: str, typ: str) -> list[str] | None:
    code, daten = _json("https://dns.google/resolve", params={"name": name, "type": typ})
    if code != 200 or not isinstance(daten, dict):
        return None
    return [a.get("data", "") for a in daten.get("Answer") or []]


def main() -> int:
    jetzt = datetime.now(timezone.utc)
    repo_name = os.environ.get("GITHUB_REPOSITORY", "mueddi/KNIFF")
    gh = {"Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}",
          "Accept": "application/vnd.github+json"}

    def gh_json(pfad):
        code, daten = _json(f"https://api.github.com/repos/{repo_name}{pfad}", headers=gh)
        return daten if code == 200 else None

    def laeufe(datei):
        d = gh_json(f"/actions/workflows/{datei}/runs?branch=main&per_page=10")
        return None if d is None else d.get("workflow_runs") or []

    befunde: list[Befund] = [pruefe_repo(gh_json(""))]

    gesetzt = {name: os.environ.get(f"HAT_{name}", "").lower() == "true" for name in SECRETS}
    befunde += pruefe_secrets(gesetzt)

    stripe_key = os.environ.get("STRIPE_ABGLEICH_KEY", "").strip()
    endpunkte = None
    if stripe_key:
        code, daten = _json("https://api.stripe.com/v1/webhook_endpoints", params={"limit": 100},
                            auth=(stripe_key, ""))
        if code == 200 and isinstance(daten, dict):
            endpunkte = daten.get("data") or []
    befunde.append(pruefe_webhook(endpunkte))

    sb_token = os.environ.get("SUPABASE_ACCESS_TOKEN", "").strip()
    auth_cfg = None
    if sb_token:
        code, daten = _json(f"https://api.supabase.com/v1/projects/{SUPABASE_PRODUKTION}/config/auth",
                            headers={"Authorization": f"Bearer {sb_token}"})
        if code == 200 and isinstance(daten, dict):
            auth_cfg = daten
    befunde.append(pruefe_supabase_auth(auth_cfg))

    # Typ A liefert bei einem CNAME die ganze Kette mit – ein Eintrag reicht.
    befunde += pruefe_dns(_dns("www.kniff.app", "A"), _dns("kniff.app", "MX"))

    code, daten = _json(f"{LIVE}/api/health")
    befunde.append(pruefe_health(code, daten if isinstance(daten, dict) else None))

    befunde.append(pruefe_letzten_lauf("Deploy", laeufe("deploy.yml"), jetzt))
    befunde.append(pruefe_letzten_lauf("Sicherung", laeufe("backup.yml"), jetzt, max_alter_tage=BACKUP_MAX_TAGE))
    befunde.append(pruefe_letzten_lauf("Zahlungs-Abgleich", laeufe("zahlungsabgleich.yml"), jetzt, max_alter_tage=2))

    text = bericht(befunde)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text + "\n")
    fehler = [b for b in befunde if b.stufe == "fehler"]
    for b in fehler:
        print(f"::error::{b.bereich}: {b.text}")
    for b in befunde:
        if b.stufe == "warnung":
            print(f"::warning::{b.bereich}: {b.text}")
    if os.environ.get("BEFUNDE_JSON"):
        with open(os.environ["BEFUNDE_JSON"], "w", encoding="utf-8") as f:
            json.dump([b.__dict__ for b in befunde], f, ensure_ascii=False, indent=1)
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
