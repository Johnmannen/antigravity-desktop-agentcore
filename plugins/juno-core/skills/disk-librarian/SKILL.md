---
name: disk-librarian
description: Inventory folders, detect exact duplicate files (size + SHA-256), and generate safe read-only cleanup plans using tools/disk_librarian.py.
---

# Disk Librarian Skill (Hårddisk-bibliotekarien)

Använd detta verktyg för att inventera, katalogisera och föreslå rensning på `C:\` och `G:\` utan att röra några filer.

## Kommandon (körs från `<PROJECT_ROOT>`)

- **Inventera och spara katalog:** `.\.venv\Scripts\python.exe tools/disk_librarian.py catalog "<USER_HOME>\Downloads"`
- **Hitta exakta dubbletter:** `.\.venv\Scripts\python.exe tools/disk_librarian.py duplicates "<USER_HOME>\Downloads" --min-size-kb 100`
- **Skapa rensningsförslag:** `.\.venv\Scripts\python.exe tools/disk_librarian.py cleanup-plan "<USER_HOME>\Downloads" --days-old 90`

## Säkerhetsregel
Verktyget är strikt läs-orienterat. Flytta till arkiv eller radera **aldrig** filer förrän John uttryckligen godkänt exakt vilka filer som ska hanteras.
