---
name: system-health
description: Check Windows RAM usage, free disk space on C:\ and G:\, and Juno memory/log footprint using <PROJECT_ROOT>\tools\system_health.py.
---

# System Health Skill

Använd detta verktyg när John frågar om datorns hälsa, diskutrymme, RAM eller minnesfilernas storlek.

## Kommando (körs från `<PROJECT_ROOT>`)

- **Standardkoll (`C:\` och `G:\`):** `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\system_health.py`
- **Valfria enheter:** `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\system_health.py --drives C D G`
- **Autonom sensor (skriver till `logs/guardian_alert.json`):** `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\guardian_watch.py` (använd `--quiet` i bakgrundsjobb)
- **Tröskelvärden:** Justeras i [guardian_config.json](file:///<PROJECT_ROOT>/tools/guardian_config.json)
