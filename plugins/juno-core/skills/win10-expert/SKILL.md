---
name: win10-expert
description: Windows 10-systemexpert för djupdiagnostik, underhåll, inställningar och säkerhetsstyrd felsökning via tools/win10_doctor.py, lokal kunskapsbas och learn.microsoft.com.
---

# Windows 10 System Expert (`win10-expert`)

Använd denna skill när John frågar om Windows 10-problem, långsam dator, drivrutiner, uppdateringar, nätverk, inställningar eller systemunderhåll.

## Arbetsflöde (Säkerhet först)

1. **Läs alltid kunskapsbasen först:** Öppna `references/win10_kb.md` för att se symptom-till-orsak-karta och `ms-settings:`-genvägar.
2. **Kör endast läsande diagnostik (`GREEN`):**
   `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\win10_doctor.py diagnose --section <all|system|events|services|startup|drivers|network|disk|security>`
3. **Hämta ny kunskap vid behov:** Om problemet är specifikt (t.ex. en ny KB-uppdatering eller felkod), slå upp officiell dokumentation på `learn.microsoft.com` via `search_web` och lägg vid behov till den nya lösningen i `references/win10_kb.md`.
4. **Klassa risken innan du föreslår ändring:**
   `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\win10_doctor.py check-risk "<kommando>"`
   - `BLOCKED`: Får aldrig föreslås eller köras.
   - `RED`: Kräv backup (`win10_doctor.py backup`), förklara risken tydligt och invänta Johns uttryckliga **"Kör"**.
   - `YELLOW`: Beskriv ändringen kort och invänta Johns OK.
5. **Öppna inställningar direkt:** Använd `open-setting ms-settings:<sida>` för att guida John rakt till rätt meny.
