# Antigravity Desktop AgentCore — Workspace Rules (`AGENTS.md`)

> Generic operational ruleset for a local Python + Google Antigravity Desktop workspace. Customize this file with your own persona and preferences.

---

## Core Architecture & Memory (3 Layers)

1. **Layer 1 (Active):** Current Antigravity conversation and workspace context.
2. **Layer 2 (Source of Truth — JSON):**
   * `memory/profile.json` — User preferences, reminders, and learned facts (`memories`).
   * `memory/projects.json` — Active, paused, and archived projects.
3. **Layer 3 (Write Gate & Lifecycle):**
   * `memory/write_gate.py` & `memory/lifecycle.py` — Secret filtering, prompt-injection protection, character limits, importance scoring (1–5), stability (`stable`/`fluid`/`transient`), and deduplication.
   * Operations are audited to `logs/juno_tools_audit.jsonl`.

### Memory Discipline
* Save durable user facts/preferences via:
  `python tools/memory_cli.py learn "<short fact>" --stability stable|fluid|transient --source auto_learn`
  Whenever a new memory is saved, always report it concisely in chat:
  `**Saved to memory (<id> | <stability>):** "<exact text>"`
* Update or remove a stored memory anytime via `python tools/memory_cli.py update <id> "<new text>"` or `forget <id>`.
* Store repeatable procedures as **Skills** in `skills/`, never inside personal memory.
* Heavy changes (`projects.json`, core rules) are staged via `python tools/memory_cli.py stage ...` and applied only after user approval (`approve`).

---

## Approval & Safety Boundaries

**Allowed without asking:**
* Read, search, and analyze files in the workspace.
* Create/edit local scripts and tools inside the workspace.
* Stage memory proposals in `memory/pending/` and write logs to `logs/`.

**Always require explicit user confirmation first:**
* Deleting files or folders outside temporary caches.
* Modifying OS settings, registry, autostart, or system services.
* Sending emails, deleting cloud files, or pushing to public repositories.
* Approving (`approve`) pending memory changes in `memory/pending/`.

---

## Resource Selection & Transparent Reporting (Mandatory)

1. **Phase-based inventory before starting:** Scan available skills, tools, and subagents across *Planning & Design*, *UI/Production & Code Quality*, *Technical Testing & Accessibility*, and *Visual Live Demo & Post-Verify*. Read matching `SKILL.md` files before coding.
2. **New project / missing local `AGENTS.md`:** Initialize the project's stack-specific local complement (`python`, `web`, `mobile`, or `general`) without duplicating central tools by running:
   `python tools/init_project.py "<project_dir>" --stack <python|web|mobile|general>`
3. **Report at the top of each reply:** Start with a compact header block listing agents, skills, and tools used (plus `**Saved to memory (...):**` whenever a memory is saved), followed by a horizontal divider (`---`) before the main reply. Break down per phase for larger builds.

---

## Mandatory Post-Verification (`post-verify`)

Before finishing any build or task:
1. **Functional live test:** Run the code against its real target after the final edit. For web/UI/apps, run the **two-step combo**:
   * *Step 1 (Silent X-ray):* `chrome-devtools` or `browser` subagent verifies 0 console/network errors, interactivity, and desktop + mobile layouts.
   * *Step 2 (Visible live demo):* `chrome_agent.py demo <url> --keep-open --screenshot` demonstrates features visibly on screen, followed by reading the screenshot with `read_file`.
2. **Requirements check:** Verify point-by-point against the user's request.
3. **Rules & artifacts check:** Confirm compliance with `AGENTS.md` and run `qa-auditor` for major builds. For video/animation/demo builds, **Audio-Visual Speaker-Sync is mandatory:** narration must always match the visuals (graphics must follow the speaker and shift with every new thought—never remain static while speech continues). Any desync must be flagged as `ERROR` by `qa-auditor` (only exception: videos explicitly demonstrating how an error occurs).

---

## Anti-Hang & Anti-Deadlock Standard (Mandatory)

* **No Windows pipe deadlocks:** Never pass `stderr=subprocess.PIPE` or `stdout=subprocess.PIPE` while feeding `stdin` (e.g., piping frames to `ffmpeg`). Always redirect `stderr` to a log file.
* **Unbuffered progress & hard timeouts:** Run long Python jobs with `-u` (`flush=True`), enforce explicit timeouts (`asyncio.wait_for`, `timeout=`) and retries on network/TTS/API/Playwright calls, and use `tools/safe_exec.py` to terminate stalled process trees cleanly.
* **No premature completion:** Never report a deliverable as done until the output file exists on disk and is verified.
