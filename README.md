# Antigravity Desktop AgentCore

A modular **local desktop & Python agent framework** designed to pair with **Google Antigravity Desktop (v2.32.1+)** and its **Remote Control (`antigravity.google.com`)** workflow.

It turns your local machine into an autonomous, safety-gated execution environment with a 3-layer memory engine, visible Google Chrome live-demo automation, Windows desktop inspection, system health monitoring, and a strict two-step post-verification pipeline.

---

## 1. What You Need to Install Separately (Prerequisites)

Before cloning this repository, make sure the following applications and runtimes are installed on your machine (Windows 10/11 recommended):

1. **Google Antigravity Desktop (`v2.32.1+`)**
   * The Antigravity desktop client connected to **`antigravity.google.com`** (with **Remote Control** enabled so web/mobile sessions can drive your local workspace).
2. **Google Chrome**
   * Required for `tools/chrome_agent.py` (`channel="chrome"`, visible live demos) and Chrome DevTools MCP debugging.
3. **Python `3.10+`**
   * Used for the local CLI tools, memory engine, desktop bridge, and optional voice proxy.
4. **Node.js (`18+` with `npx`)**
   * Required for MCP servers and guidance tools such as `chrome-devtools-mcp` and `modern-web-guidance`.
5. **Git & GitHub CLI (`gh`)** *(optional, for repo sync)*
   * Needed if you want to sync or publish updates via `tools/sync_repos.py`.

---

## 2. Recommended Antigravity Settings

To get the full multi-agent and live-verification experience inside Google Antigravity:

* **Remote Control:** Enable Remote Control in Antigravity Desktop settings so `antigravity.google.com` stays linked to your local workspace.
* **MCP Servers:** Enable **`chrome-devtools`** (`npx chrome-devtools-mcp@latest`) for silent DOM, console, network, and accessibility inspection.
* **Plugins / Customizations:** Load `plugins/juno-core/` in your Antigravity plugin/config directory (provides subagents `juno-builder`, `qa-auditor`, `system-guardian`, `chrome-visual-agent`, plus `post-verify` and core skills).
* **Workspace Rules:** Copy `AGENTS.template.md` to `AGENTS.md` (handled automatically by `setup.ps1`) and customize your preferences.

---

## 3. What Is Installed Automatically via This Repo

Everything in `tools/`, `memory/`, `skills/`, `plugins/juno-core/`, and `services/` is included directly in the repository.

### Quick Start (Windows PowerShell)

```powershell
git clone https://github.com/Johnmannen/antigravity-desktop-agentcore.git
cd antigravity-desktop-agentcore
.\setup.ps1
```

Optional: include `-WithVoice` if you want the local voice proxy dependencies (`fastapi`, `uvicorn`, `edge-tts`, `faster-whisper`, `kokoro`):

```powershell
.\setup.ps1 -WithVoice
```

`setup.ps1` will automatically:
1. Create a Python virtual environment (`.venv`).
2. Install core Python packages from `requirements.txt` (`playwright`, `pywinauto`, `psutil`, `httpx`, `openai`, `beautifulsoup4`, `ddgs`, `python-dotenv`).
3. Install Playwright's Chromium binary.
4. Initialize `.env` from `.env.example`, `AGENTS.md` from `AGENTS.template.md`, and empty memory files in `memory/`.
5. Run `tools/system_health.py` to verify your environment.

Then open `.env` and add any API keys you use (for example OpenAI/Gemini/OpenRouter keys).

---

## 4. Architecture Overview

| Component | Purpose |
| :--- | :--- |
| **`memory/`** | 3-layer memory system (`write_gate.py`, `lifecycle.py`) with secret filtering, prompt-injection guards, stability tiers, and deduplication. |
| **`tools/chrome_agent.py`** | Visible Google Chrome automation (`open`, `search`, `demo`) with `--keep-open`, maximized viewport, cursor overlay, and screenshots. |
| **`tools/desktop_bridge.py`** & **`desktop_operator.py`** | Interactive Windows desktop bridge and `pywinauto` window inspection/control. |
| **`tools/system_health.py`**, **`ops_watchdog.py`**, **`repo_janitor.py`** | Local RAM/disk monitoring, service checks, and git cleanliness scanner. |
| **`tools/init_project.py`** | Installs stack-specific local `AGENTS.md` + `.gitignore` complements into new projects while keeping central tools in one place. |
| **`tools/deep_research.py`**, **`disk_librarian.py`**, **`inbox_organizer.py`** | Local research, SHA-256 duplicate detection, and read-only folder analysis. |
| **`plugins/juno-core/`** | Portable Antigravity plugin containing specialist subagents (`juno-builder`, `qa-auditor`, `system-guardian`) and `post-verify` skills. |
| **`services/juno_rostproxy.py`** | Optional local OpenAI-compatible STT/TTS proxy service. |

---

## 5. Two-Step Visual Post-Verification (`post-verify`)

UI and web builds follow a strict verification loop before delivery:
1. **Step 1 — Silent Technical X-Ray:** `browser` subagent / `chrome-devtools` checks 0 console errors, 0 failed network requests, interactive state, and desktop + mobile layouts.
2. **Step 2 — Visible Live Demo:** `tools/chrome_agent.py demo <url> --keep-open --screenshot` launches Chrome visibly in the foreground, interacts with the app live, captures a screenshot, and leaves the window open for manual inspection.
3. **Step 3 — Independent QA:** `qa-auditor` verifies requirements, rules, and test evidence.

---

## License

MIT — see [LICENSE](LICENSE).
