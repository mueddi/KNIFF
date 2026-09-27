## Was ändert sich

<!-- Ein bis drei Sätze, aus Sicht eines Nutzers. Was merkt ein Kind oder ein
     Elternteil davon? Wenn niemand etwas merkt, dann schreib genau das. -->

## Warum

<!-- Welches Problem löst es? Wenn es eine Messung gibt (Datenbank,
     Laufzeitprotokoll, Testlauf), gehört sie hierher. -->

## In der Vorschau geprüft

<!-- Die Vorschau-Adresse dieses Zweigs und was du dort angeschaut hast.
     Bei reinen Text- oder Teständerungen: «nicht nötig» und warum. -->

Adresse:
Geprüft:

## Vor dem Merge

- [ ] Alle Tests grün (`backend-tests`, `backend-postgres`, `frontend-build`, `e2e` unten auf dieser Seite)
- [ ] In der Vorschau angeschaut — oder begründet, warum nicht nötig
- [ ] Keine Geheimnisse im Diff (keine Schlüssel, keine `.env`, keine `runtime-env.json`)
- [ ] Nur **ein** Thema in diesem Pull Request

## Handarbeit nach dem Merge

<!-- Alles, was NICHT im Code steckt und von Hand gemacht werden muss, damit
     die Änderung wirkt – mit genauem Ort. Zum Beispiel: «Stripe → Webhook:
     Ereignis charge.refunded ergänzen», «GitHub-Secret X anlegen»,
     «Vercel → Environment Variables: Y setzen», «DNS-Eintrag Z bei
     Squarespace». Wenn nichts: «keine».
     Was hier steht, gehört danach auch in den Betriebs-Check
     (backend/scripts/betriebs_check.py), damit es nicht vergessen geht. -->

- keine

## Wenn es live schiefgeht

<!-- Reicht «Instant Rollback in Vercel»? Oder muss zusätzlich etwas
     rückgängig gemacht werden – eine Datenbankspalte, eine Einstellung? -->
