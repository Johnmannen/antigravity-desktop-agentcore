---
name: chrome-visual-agent
description: Visual Google Chrome automation using Playwright (headless=False) so John can watch searches, page navigation, and indexing in real time.
---

# Visual Chrome Web Agent Skill

Använd detta verktyg när John vill att agenten ska söka, navigera eller samla underlag **visuellt i Google Chrome** på skärmen (inte dolt i bakgrunden).

## Kommandon (körs från `<PROJECT_ROOT>`)

- **Öppna och läs en sida visuellt (stannar öppen):**
  `.\.venv\Scripts\python.exe tools/chrome_agent.py open "https://example.com" --keep-open --screenshot`
- **Sök visuellt med smart tvåspråkig `OR`-expansion (stannar öppen):**
  `.\.venv\Scripts\python.exe tools/chrome_agent.py search "begagnade elskotrar i Haninge" --smart --keep-open`

## Säkerhetsregler
- Kringgå **aldrig** CAPTCHA, inloggningsspärrar eller betalväggar. Stanna och be John ta över i fönstret om en sådan dyker upp.
- Skicka aldrig formulär, kommentarer eller köp utan Johns uttryckliga OK.
