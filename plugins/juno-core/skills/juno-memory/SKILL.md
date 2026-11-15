---
name: juno-memory
description: Read, stage, and manage Juno's 3-layer memory (profile.json, projects.json, energy level, and pending write_gate proposals) in <PROJECT_ROOT>.
---

# Juno Memory Skill

Använd detta verktyg för att läsa och uppdatera Johns minnesarkiv utan att bryta mot skrivgrinden (`write_gate.py`).

## Kommandon (körs från `<PROJECT_ROOT>`)

- **Visa status & energi:** `python tools/memory_cli.py status`
- **Lista inlärda minnen:** `python tools/memory_cli.py memories`
- **Livscykel-underhåll (dedup, stale-koll, rensa gamla pending):** `python tools/memory_cli.py maintain`
- **Autonomt självlärande (korta fakta/preferenser, med sekretfilter & dedup):**
  `python tools/memory_cli.py learn "John föredrar korta röstsvar utan punktlistor" --stability stable --source auto_learn`
- **Lista väntande förslag:** `python tools/memory_cli.py pending`
- **Föreslå minnesändring (staging):**
  `python tools/memory_cli.py stage profile.json patch '{"reminders": ["Ny påminnelse"]}'`
- **Godkänn förslag (efter Johns OK):**
  `python tools/memory_cli.py approve <pending_id>`
- **Sätt energi (endast på Johns begäran, Regel 41):**
  `python tools/memory_cli.py energy 75`
