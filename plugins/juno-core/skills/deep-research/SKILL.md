---
name: deep-research
description: Iterative Deep Research workflow with an adaptive one-question-at-a-time prompt writer before running <PROJECT_ROOT>\tools\deep_research.py.
---

# Deep Research Skill (Adaptiv Promptskrivare + Iterativ Sökning)

Använd detta arbetsflöde när John vill göra en grundlig research på ett ämne.

## Steg 1: Adaptiv Promptskrivare (ALLTID EN FRÅGA I TAGET)
1. Starta **aldrig** med att slänga ut en lista med 3–5 frågor samtidigt.
2. Ställ **fråga 1** först (t.ex. vad resultatet ska användas till eller vilket huvudfokus som är viktigast).
3. Använd Johns svar från fråga 1 för att forma **fråga 2** (t.ex. avgränsning, tidsram, eller vad som ska uteslutas). Fortsätt en fråga i taget (oftast 2–5 frågor) tills du har allt som behövs.
4. Visa den färdiga, skarpa research-prompten för John och be om **"Kör"**.

## Steg 2: Kör Deep Research-motorn
När John godkänt prompten, kör:
```powershell
<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\deep_research.py "<färdig_prompt>"
```

## Steg 3: Leverera
Länka till den sparade rapporten i `docs/research/` och ge en kort, skannbar sammanfattning av huvudfynden och eventuella osäkerheter.
