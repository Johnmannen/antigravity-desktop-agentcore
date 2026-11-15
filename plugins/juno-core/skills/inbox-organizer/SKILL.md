---
name: inbox-organizer
description: Read-only folder analyzer that categorizes files and flags large items in Downloads, Desktop, or any target folder using <PROJECT_ROOT>\tools\inbox_organizer.py.
---

# Inbox Organizer Skill

Använd detta verktyg för att säkert skanna en mapp (som Hämtade filer eller Skrivbordet) och föreslå sortering utan att flytta eller radera något.

## Kommandon (körs från `<PROJECT_ROOT>`)

- **Skanna Hämtade filer:** `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\inbox_organizer.py`
- **Skanna specifik mapp:** `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\inbox_organizer.py "<USER_HOME>\Desktop"`
- **Ändra gräns för stora filer (MB):** `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\inbox_organizer.py --large-mb 50`

## Säkerhetsregel
Verktyget är strikt read-only. Flytta eller radera aldrig filer utan Johns uttryckliga OK.
