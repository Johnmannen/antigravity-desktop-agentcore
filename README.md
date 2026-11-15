# Antigravity Desktop AgentCore

A **global, personalized agent orchestration framework** for **Google Antigravity Desktop (`v2.32.1+`)** and **Remote Control (`antigravity.google.com`)**.

Instead of setting up rules, memory, and verification workflows separately for every repository, **AgentCore** separates your environment into three clean layers so your personalized AI setup works **globally across every project on your desktop**:

1. **Global Persona & Safety Layer (`plugins/juno-core/`):** Installed once in your global Antigravity config (`~/.gemini/config/`). Travels with you to every workspace — providing consistent communication ergonomics, approval gates, phase-based skill selection, and mandatory post-verification while keeping **Antigravity's built-in tools (`browser`, `research`, `swarm`, `run_workflow`, MCP servers) first-class**.
2. **Central Python Engine (one shared home directory):** Hosts your 3-layer memory (`memory/`), visible Chrome live-demo runner (`tools/chrome_agent.py`), Windows desktop bridge (`tools/desktop_bridge.py`), and system health monitors (`tools/system_health.py`) — invoked via absolute paths from any project.
3. **Stack-Specific Local Complements (`tools/init_project.py`):** Automatically installs lightweight, project-specific `AGENTS.md` + `.gitignore` rulesets (`python`, `web`, `mobile`, `general`) into new projects without bloating your global context or duplicating scripts.

---

## 1. Prerequisites (Installed Separately)

Before cloning this repository, ensure the following applications and runtimes are available (Windows 10/11 recommended):

1. **Google Antigravity Desktop (`v2.32.1+`)**
   * Connected to **`antigravity.google.com`** with **Remote Control** enabled so desktop and mobile sessions share the same local workspace and global plugin.
2. **Google Chrome**
   * Required for `tools/chrome_agent.py` (`channel="chrome"`, visible live demos) and Chrome DevTools MCP debugging.
3. **Python `3.10+`**
   * Powers the central engine, 3-layer memory, desktop bridge, and optional voice proxy.
4. **Node.js (`18+` with `npx`)**
   * Required for MCP servers and guidance tools such as `chrome-devtools-mcp` and `modern-web-guidance`.
5. **Git & GitHub CLI (`gh`)** *(optional, for repo sync)*
   * Needed if you use `tools/sync_repos.py` to manage private + public template sync.

---

## 2. Recommended Antigravity Settings

* **Remote Control:** Enable Remote Control in Antigravity Desktop so `antigravity.google.com` connects to your local machine.
* **MCP Servers:** Enable **`chrome-devtools`** (`npx chrome-devtools-mcp@latest`) for silent DOM, console, network, and accessibility inspection.
* **Global Plugin:** Load `plugins/juno-core/` in your global Antigravity config (`~/.gemini/config/plugins/`) so your personalized rules, specialist subagents (`juno-builder`, `qa-auditor`, `system-guardian`, `chrome-visual-agent`), and `post-verify` workflow apply across all projects.
* **Workspace Rules:** Customize `AGENTS.template.md` as `AGENTS.md` (created automatically by `setup.ps1`).

---

## 3. Quick Start (Installed via This Repo)

Everything in `tools/`, `memory/`, `plugins/juno-core/`, and `services/` is included in this repository.

```powershell
git clone https://github.com/Johnmannen/antigravity-desktop-agentcore.git
cd antigravity-desktop-agentcore
.\setup.ps1
```

Optional: add `-WithVoice` to include the local voice proxy dependencies (`fastapi`, `uvicorn`, `edge-tts`, `faster-whisper`, `kokoro`):

```powershell
.\setup.ps1 -WithVoice
```

`setup.ps1` automatically:
1. Creates a Python virtual environment (`.venv`).
2. Installs core packages from `requirements.txt` (`playwright`, `pywinauto`, `psutil`, `httpx`, `openai`, `beautifulsoup4`, `ddgs`, `python-dotenv`).
3. Installs Playwright's Chromium binary.
4. Initializes `.env` from `.env.example`, `AGENTS.md` from `AGENTS.template.md`, and empty memory templates in `memory/`.
5. Runs `tools/system_health.py` to verify your setup.

Then open `.env` and add your own API keys.

### Initialize Any New Project Globally

Once AgentCore is set up, initialize any new or existing project folder with stack-appropriate local rules while keeping all Python tools and memory centralized:

```powershell
.\.venv\Scripts\python.exe tools\init_project.py "C:\path\to\my-new-project" --stack web
```

Supported `--stack` values: `python`, `web`, `mobile`, `general`.

---

## 4. Architecture Overview

| Component | Purpose |
| :--- | :--- |
| **`plugins/juno-core/`** | Global Antigravity plugin: slimmed global rules, specialist subagents (`juno-builder`, `qa-auditor`, `system-guardian`), hooks, and `post-verify` skills. |
| **`memory/`** | 3-layer memory engine (`write_gate.py`, `lifecycle.py`) with secret filtering, prompt-injection guards, stability tiers, and deduplication. |
| **`tools/init_project.py`** | Installs lightweight, stack-specific local `AGENTS.md` and `.gitignore` complements into any project without duplicating central tools. |
| **`tools/chrome_agent.py`** | Visible Google Chrome automation (`open`, `search`, `demo`) with `--keep-open`, maximized viewport, cursor overlay, and screenshots. |
| **`tools/desktop_bridge.py`** & **`desktop_operator.py`** | Interactive Windows desktop bridge and `pywinauto` window inspection/control. |
| **`tools/system_health.py`**, **`ops_watchdog.py`**, **`repo_janitor.py`** | Local RAM/disk monitoring, service checks, and git cleanliness scanner. |
| **`tools/deep_research.py`**, **`disk_librarian.py`**, **`inbox_organizer.py`** | Local research, SHA-256 duplicate detection, and read-only folder analysis. |
| **`tools/export_public_template.py`** & **`sync_repos.py`** | Whitelisted public template exporter with PII/secret scanning and dual-repo GitHub sync. |
| **`services/juno_rostproxy.py`** | Optional local OpenAI-compatible STT/TTS proxy service. |

---

## 5. Two-Step Visual Post-Verification (`post-verify`)

UI and web builds follow a strict verification loop before delivery:
1. **Step 1 — Silent Technical X-Ray:** `browser` subagent / `chrome-devtools` checks 0 console errors, 0 failed network requests, interactive state, and desktop + mobile layouts.
2. **Step 2 — Visible Live Demo:** `tools/chrome_agent.py demo <url> --keep-open --screenshot` launches Chrome visibly in the foreground, interacts with the app live, captures a screenshot, and leaves the window open for inspection.
3. **Step 3 — Independent QA:** `qa-auditor` verifies requirements, rules, and test evidence (and closes any temporary test tabs).

---

## License

MIT — see [LICENSE](LICENSE).
