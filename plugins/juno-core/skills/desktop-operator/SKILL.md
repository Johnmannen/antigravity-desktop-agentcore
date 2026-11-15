---
name: desktop-operator
description: Inspect open Windows applications, focus windows, launch apps, and type text via pywinauto (<PROJECT_ROOT>\tools\desktop_operator.py).
---

# Desktop Operator Skill (Windows Skrivbords- & Appstyrning)

Använd detta verktyg för att inspektera öppna programfönster eller styra lokala Windows-program som saknar API.

## Kommandon (körs från `<PROJECT_ROOT>`)

- **Lista öppna fönster (läsläge):** `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\desktop_operator.py windows`
- **Fokusera ett fönster:** `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\desktop_operator.py focus ".*Anteckningar.*"`
- **Starta ett program:** `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\desktop_operator.py launch notepad.exe`
- **Skriv text i ett fönster:** `<PROJECT_ROOT>\.venv\Scripts\python.exe <PROJECT_ROOT>\tools\desktop_operator.py type-into ".*Anteckningar.*" "Hej från Juno"`

## Säkerhetsregel
Ändra aldrig Windows-inställningar, register eller stäng/radera något utan Johns uttryckliga OK.
