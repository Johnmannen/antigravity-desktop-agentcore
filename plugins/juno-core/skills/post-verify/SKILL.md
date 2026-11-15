---
name: post-verify
description: Obligatorisk 3-stegs efterkontroll (kod/live-test, beställningskontroll, regel-/artefaktkontroll) innan ett uppdrag avslutas.
---

# Post-Verify (Obligatorisk Efterkontroll)

Innan du presenterar ett slutfört uppdrag eller kodbygge för John måste följande tre kontroller vara genomförda och passerade:

1. **Funktionell kod- & live-test:**
   - Kod måste köras i skarpt läge mot sitt verkliga mål (t.ex. HTTP-endpoint, CLI-kommando, filoperation eller UI-test) — inte bara syntaxkollas eller antas fungera.
   - **Visuell tvåstegskombo (vid UI, dashboard, hemsida, spel eller mobil-PWA):**
     1. *Tyst teknisk röntgen:* Använd `chrome-devtools` eller `browser`-agenten för att kontrollera konsolfel, trasiga nätverksanrop samt layout/overflow på **både desktop och mobil**.
     2. *Synlig live-demo:* Öppna slutresultatet synligt i förgrunden på Johns skärm med `chrome_agent.py` (`--keep-open --screenshot`) **och kör en aktiv live-demonstration av appens/spelets funktioner** så John ser att allt fungerar innan överlämning. Läs alltid in den tagna skärmdumpen med `read_file` för att visuellt kontrollera att inget klipps av.
   - Rapportera endast tester som du själv har kört efter den sista ändringen.
2. **Beställningskontroll:**
   - Gå punkt för punkt igenom Johns ursprungliga beställning och verifiera att varje krav, format och begränsning är uppfylld.
3. **Regel- & artefaktkontroll:**
   - Kontrollera att arbetet följer `AGENTS.md`, globala regler (`juno-core`), säkerhetsgränser (inga raderingar utan OK, inga läckta nycklar) samt att resursredovisningen står överst i svaret.

Vid större kod- eller systembyggen: delegera en slutlig granskning till underagenten `qa-auditor`.
