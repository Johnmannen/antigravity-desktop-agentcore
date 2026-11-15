# Antigravity Desktop AgentCore

A **global, personalized agent orchestration framework** for the **[Antigravity App](https://antigravity.google/download) (`v2.32.1+`)** and **Remote Control (`antigravity.google.com`)**.

Instead of configuring rules, memory, and verification separately for every project, **AgentCore** splits your setup into three clean layers so your personalized AI workflow works **globally across every repository on your desktop**:

1. **Global Persona & Safety Layer (`plugins/juno-core/`):** Installed once in `%USERPROFILE%\.gemini\config\plugins\juno-core`. Follows you into every workspace with consistent communication ergonomics, approval gates, phase-based skill selection, and mandatory post-verification — while keeping **Antigravity's built-in tools (`browser`, `research`, `swarm`, `run_workflow`, MCP servers) first-class**.
2. **Central Python Engine (one shared home directory):** Hosts your 3-layer memory (`memory/`), visible Chrome live-demo runner (`tools/chrome_agent.py`), Windows desktop bridge (`tools/desktop_bridge.py`), and health monitors (`tools/system_health.py`), invoked via absolute paths from any project.
3. **Stack-Specific Local Complements (`tools/init_project.py`):** Automatically installs lightweight, project-specific `AGENTS.md` + `.gitignore` rulesets (`python`, `web`, `mobile`, `general`) into new projects without bloating your global context or duplicating scripts.

---

## 1. Prerequisites (Installed Separately)

Before cloning this repository, ensure the following applications and runtimes are installed:

1. **[Antigravity App](https://antigravity.google/download) (`v2.32.1+`)**
   * Download from `https://antigravity.google/download` (official docs: `https://antigravity.google/docs`).
   * Enable **Remote Control** so web/mobile sessions on `antigravity.google.com` connect seamlessly to your local workspace.
2. **Google Chrome**
   * Required for `tools/chrome_agent.py` (`channel="chrome"`, visible live demos) and Chrome DevTools MCP debugging.
3. **Python `3.10+`** *(Windows 10/11 required for `pywinauto` / `desktop_bridge.py`; core CLI tools are cross-platform Python)*
   * Powers the central engine, 3-layer memory, desktop bridge, and optional voice proxy.
4. **Node.js (`18+` with `npx`)**
   * Required for MCP servers and guidance tools such as `chrome-devtools-mcp` and `modern-web-guidance`.
5. **Git & GitHub CLI (`gh`)** *(optional, for dual-repo sync)*
   * Needed if you use `tools/sync_repos.py` to sync private + public template repositories.

### How Antigravity Connects to This Python Engine
Today, the Antigravity App orchestrates these local Python tools natively through **Skills (`SKILL.md`)**, **Hooks (`hooks.json`)**, **MCP (`chrome-devtools-mcp`)**, and **CLI commands (`run_command`)** — no extra Antigravity SDK dependency is required to run AgentCore.

* **Optional / Next-Step Integration — [Google Antigravity SDK (`antigravity-sdk-python`)](https://github.com/google-antigravity/antigravity-sdk-python):** If you want to build standalone Python services or custom apps that programmatically lease and orchestrate Antigravity agents directly from Python code, you can pair this repository with the `google-antigravity` Python package.

---

## 2. Recommended Antigravity Settings

* **Remote Control:** Turn on Remote Control in the Antigravity App so `antigravity.google.com` can drive your local workspace.
* **MCP Servers:** Enable **`chrome-devtools`** (`npx chrome-devtools-mcp@latest`) for silent DOM, console, network, and accessibility inspection.
* **Global Plugin Path:** Copy or link `plugins/juno-core/` into `%USERPROFILE%\.gemini\config\plugins\juno-core` so global rules, subagents (`juno-builder`, `qa-auditor`, `system-guardian`, `chrome-visual-agent`), hooks, and `post-verify` load in every project.
* **Workspace Rules:** Customize `AGENTS.template.md` as `AGENTS.md` (initialized automatically by `setup.ps1`).

---

## 3. Quick Start (Installed via This Repo)

```powershell
git clone https://github.com/Johnmannen/antigravity-desktop-agentcore.git
cd antigravity-desktop-agentcore
.\setup.ps1
```

Optional: pass `-WithVoice` to install local voice proxy dependencies (`fastapi`, `uvicorn`, `edge-tts`, `faster-whisper`, `kokoro`):

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

```powershell
.\.venv\Scripts\python.exe tools\init_project.py "C:\path\to\my-new-project" --stack web
```

Supported `--stack` values: `python`, `web`, `mobile`, `general`.

---

## 4. Complete Feature Catalog

| Feature | What It Does & How It Works | Included in Repo |
| :--- | :--- | :--- |
| **Global Plugin (`plugins/juno-core/`)** | Bundles global persona/ergonomics rules, `post_edit_verify.py` hook, `post-verify` skill, and 8 specialist subagents (`juno-builder`, `qa-auditor`, `system-guardian`, `chrome-visual-agent`, `deep-research`, `desktop-operator`, `disk-librarian`, `google-assistant`). | Yes |
| **3-Layer Memory Engine (`memory/` + `tools/memory_cli.py`)** | Stores preferences and learned facts in JSON with `write_gate.py` (secret filtering + prompt-injection guard), `lifecycle.py` (importance scoring + deduplication), `stage`/`approve` gating, and `learn`/`update`/`forget` with concise chat receipts. | Yes |
| **Project Initializer (`tools/init_project.py`)** | Generates stack-specific local `AGENTS.md` (`python`, `web`, `mobile`, `general`) and `.gitignore` complements for new projects while keeping all Python tools centralized. | Yes |
| **Visible Chrome Live-Demo (`tools/chrome_agent.py`)** | Launches visible Google Chrome (`headless=False`, `--start-maximized`, cyan cursor overlay) for `open`, `search`, and `demo` (clicks live UI flows, captures screenshots, and leaves Chrome open with `--keep-open`). | Yes |
| **Windows Desktop Bridge (`tools/desktop_bridge.py`, `desktop_operator.py`)** | Local HTTP desktop bridge (`127.0.0.1:18765`) + `pywinauto` automation to inspect open Windows apps, focus windows, launch apps, and route visible Chrome windows to your active desktop session. | Yes (Windows 10/11) |
| **Two-Step Visual `post-verify`** | Mandatory 3-part quality gate: (1) silent `browser`/`chrome-devtools` X-ray on desktop + mobile, (2) visible `chrome_agent.py demo` + screenshot review via `read_file`, (3) independent `qa-auditor` sign-off. | Yes |
| **System Health & Watchdogs (`system_health.py`, `ops_watchdog.py`, `repo_janitor.py`, `guardian_watch.py`)** | Monitors Windows RAM, disk space, running services/ports, and git working-tree cleanliness; writes structured alerts for automated morning checks. | Yes |
| **Research & Disk Utilities (`deep_research.py`, `disk_librarian.py`, `inbox_organizer.py`)** | Iterative web research helper, SHA-256 exact duplicate file finder, and read-only folder categorizer for Downloads/Desktop cleanup plans. | Yes |
| **Dual-Repo Sync & PII Sanitizer (`export_public_template.py`, `sync_repos.py`)** | Whitelist-exports generic framework files to a clean public folder, strips local paths, and runs a strict regex secret/PII scan before committing/pushing both private and public repos. | Yes |
| **Local Voice Proxy (`services/juno_rostproxy.py`)** | Optional OpenAI-compatible local STT/TTS FastAPI service (`faster-whisper`, `edge-tts`, `kokoro`) for voice-driven workflows. | Yes (`-WithVoice`) |

---

## 5. Safety & Approval Boundaries

* **Autonomous (no prompt needed):** Reading/analyzing workspace files, editing local project code, running `memory_cli.py learn` / `stage`, and writing audit logs.
* **Always requires explicit user confirmation:** Deleting files/folders outside temp caches, changing Windows settings/autostart, sending emails or modifying cloud files, approving (`approve`) staged memory changes, and pushing to public repositories.

---

## License

MIT — see [LICENSE](LICENSE).
