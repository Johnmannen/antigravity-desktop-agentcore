---
name: juno-memory
description: Read, stage, and manage Juno's 3-layer memory (profile.json, projects.json, energy level, and pending write_gate proposals) in <PROJECT_ROOT>.
---

# Juno Memory Skill

Använd detta verktyg för att läsa och uppdatera Johns minnesarkiv utan att bryta mot skrivgrinden (`write_gate.py`).

## Kommandon (körs från `<PROJECT_ROOT>`)

- **Visa status & energi:** `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\memory_cli.py status`
- **Lista inlärda minnen:** `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\memory_cli.py memories`
- **Livscykel-underhåll (dedup, stale-koll, rensa gamla pending):** `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\memory_cli.py maintain`
- **Autonomt självlärande (korta fakta/preferenser, med sekretfilter & dedup):**
  `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\memory_cli.py learn "John föredrar korta röstsvar utan punktlistor" --stability stable --source auto_learn`
- **Lista väntande förslag:** `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\memory_cli.py pending`
- **Föreslå minnesändring (staging):**
  `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\memory_cli.py stage profile.json patch '{"reminders": ["Ny påminnelse"]}'`
- **Godkänn förslag (efter Johns OK):**
  `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\memory_cli.py approve <pending_id>`
- **Sätt energi (endast på Johns begäran, Regel 41):**
  `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\memory_cli.py energy 75`
