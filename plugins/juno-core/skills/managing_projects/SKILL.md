---
name: managing-projects
description: Manages project roadmaps, checkable TODO_CHECKLIST.md files, proactive risk spotting, mockup-first gates, and mandatory live-testing/post-verify workflows via tools/pm_tracker.py and the project-manager subagent. Use when starting a project, tracking tasks, checking off completed items, planning next steps, or activating project management.
---

# Managing Projects (Projektledar-lager & Avbockningsbara Listor)

Denna skill kopplar samman underagenten `project-manager`, statusverktyget `<PROJECT_ROOT>/tools/pm_tracker.py`, planeringsverktygen (`brainstorming-designs`, `writing-plans`) och kvalitetsgrinden (`post-verify`, `qa-auditor`).

## När Ska Denna Skill Användas
- Vid uppstart av alla nya byggen, hemsidor, appar eller systemprojekt.
- När John frågar var vi ligger i ett projekt, vad nästa steg är eller vill se sin att-göra-lista.
- Före övergång från idé till design (mockups) och från mockups till kod.
- Varje gång en deluppgift är färdigbyggd, ska live-testas eller bockas av efter Johns OK.

## Workflow

### Steg 1: Initiera Projekt & Avbockningsbar Att-Göra-Lista
Skapa projektets `AGENTS.md` och avbockningsbara `TODO_CHECKLIST.md`:

```powershell
<PROJECT_ROOT>/.venv/Scripts/python.exe <PROJECT_ROOT>/tools/pm_tracker.py init "<projektmapp>" --name "<Projektnamn>" --goal "<Mål>" --stack web
```

Lägg in bockbara etapper i logisk ordning (`plan` -> `mockup` -> `code` -> `qa` -> `launch`):

```powershell
<PROJECT_ROOT>/.venv/Scripts/python.exe <PROJECT_ROOT>/tools/pm_tracker.py add "<projektmapp>" --phase "Fas 1: Design & Mockups" --title "Ta fram visuella mockups och få Johns OK" --gate mockup
```

### Steg 2: Förekommande Projektledarkoll (Innan Bygge)
- Vid UI, hemsida eller app är **Mockups alltid obligatoriskt Steg 1** innan produktionskod skrivs (`pm_tracker.py start` blockerar automatiskt `code`-uppgifter om en `mockup`-uppgift är oavklarad).
- Kalla in underagenten `project-manager` (eller kör `pm_tracker.py status "<projektmapp>"`) vid fasbyten så att den proaktivt kan lyfta *"Har du tänkt på..."*-förslag, risker eller smartare genvägar **utan** att utföra dem på egen hand.

### Steg 3: Exekvera En Punkt i Taget -> Live-Test -> Vänta på Johns OK
1. Starta aktiv punkt (`[~]`):
   ```powershell
   <PROJECT_ROOT>/.venv/Scripts/python.exe <PROJECT_ROOT>/tools/pm_tracker.py start "<projektmapp>" T01
   ```
2. Bygg och kör skarp verifiering enligt `post-verify` (för webb/UI: teknisk röntgen desktop/mobil + synlig `chrome_agent.py demo --keep-open --screenshot` samt `qa-auditor` vid större leveranser).
3. Markera punkten som testad (`[?]`) med konkret testbevis:
   ```powershell
   <PROJECT_ROOT>/.venv/Scripts/python.exe <PROJECT_ROOT>/tools/pm_tracker.py mark-tested "<projektmapp>" T01 --test-proof "Beskriv exakt genomfört test"
   ```
4. Visa resultatet för John och be om godkännande.

### Steg 4: Äkta Avbockning (`[x]`) & Nästa Steg
Först när John uttryckligen godkänt punkten bockas den av till `[x]`:

```powershell
<PROJECT_ROOT>/.venv/Scripts/python.exe <PROJECT_ROOT>/tools/pm_tracker.py check "<projektmapp>" T01 --approved-by-john
```

Visa därefter uppdaterad status och föreslå nästa punkt på listan.

## Snabbkommandon (`pm_tracker.py`)
- Översikt över alla aktiva projekt: `<PROJECT_ROOT>/.venv/Scripts/python.exe <PROJECT_ROOT>/tools/pm_tracker.py overview`
- Status i ett projekt: `<PROJECT_ROOT>/.venv/Scripts/python.exe <PROJECT_ROOT>/tools/pm_tracker.py status "<projektmapp>"`
- Lägg in proaktiv risknotis: `<PROJECT_ROOT>/.venv/Scripts/python.exe <PROJECT_ROOT>/tools/pm_tracker.py note "<projektmapp>" --risk "<påminnelse>"`

## Status Checklist
- [ ] Projekt initierat med `TODO_CHECKLIST.md`
- [ ] Mockup-grind inlagd före alla UI-kodsteg
- [ ] Proaktiv risk- och förbättringskoll genomförd
- [ ] Aktiv uppgift live-testad enligt `post-verify` (`[?]`)
- [ ] John har godkänt leveransen före avbockning (`[x]`)
