#!/usr/bin/env python3
"""
agy_sync.py — Automatisk uppdaterings- och kunskapssynk för Antigravity.

Körs blixtsnabbt som SessionStart-hook (--hook) eller manuellt (--force).
- Känner av ändringar i Antigravity.exe, builtin-skills och config.json.
- Hämtar de senaste releasenoterna från https://antigravity.google/docs/changelog.md
  med kort timeout och tyst fallback om offline.
- Genererar en kompakt, aktuell översikt i C:\juno-agy\memory\antigravity_state.md.
- Injicerar en kort systemMessage i SessionStart enbart när en ny app-version
  eller ny changelog-post upptäckts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

AGY_EXE = Path(r"<USER_HOME>\AppData\Local\Programs\antigravity\Antigravity.exe")
BUILTIN_DIR = Path(r"<USER_HOME>\.gemini\antigravity\builtin\skills")
CONFIG_DIR = Path(r"<USER_HOME>\.gemini\config")
CONFIG_JSON = CONFIG_DIR / "config.json"
PLUGINS_DIR = CONFIG_DIR / "plugins"
GLOBAL_SKILLS_DIR = CONFIG_DIR / "skills"
GLOBAL_RULES = PLUGINS_DIR / "juno-core" / "rules" / "AGENTS.md"

MEMORY_DIR = Path(r"C:\juno-agy\memory")
STATE_JSON = MEMORY_DIR / "antigravity_sync_state.json"
STATE_MD = MEMORY_DIR / "antigravity_state.md"
CHANGELOG_URL = "https://antigravity.google/docs/changelog.md"

CHECK_INTERVAL_SEC = 24 * 3600
HTTP_TIMEOUT_SEC = 6


def compute_app_fingerprint() -> str:
    """Snabb hash över Antigravity.exe och builtin/skills (ändras vid app-uppdatering)."""
    h = hashlib.sha256()
    if AGY_EXE.exists():
        st = AGY_EXE.stat()
        h.update(f"exe:{st.st_size}:{int(st.st_mtime)}".encode("utf-8"))
    if BUILTIN_DIR.exists():
        for p in sorted(BUILTIN_DIR.rglob("SKILL.md")):
            st = p.stat()
            rel = p.relative_to(BUILTIN_DIR).as_posix()
            h.update(f"|{rel}:{st.st_size}:{int(st.st_mtime)}".encode("utf-8"))
    return h.hexdigest()[:16]


def compute_env_fingerprint(app_fp: str) -> str:
    """Inkluderar även config.json mtime så plugin-ändringar triggar lokal omsynk."""
    cfg_sig = "none"
    if CONFIG_JSON.exists():
        st = CONFIG_JSON.stat()
        cfg_sig = f"{st.st_size}:{int(st.st_mtime)}"
    return hashlib.sha256(f"{app_fp}|cfg:{cfg_sig}".encode("utf-8")).hexdigest()[:16]


def load_cache() -> dict:
    if STATE_JSON.exists():
        try:
            return json.loads(STATE_JSON.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(data: dict) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    STATE_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def fetch_changelog_sections() -> tuple[dict[str, list[str]], str]:
    """Hämtar toppen av changelog.md för App, CLI och IDE. Returnerar (sections, top_marker)."""
    req = urllib.request.Request(
        CHANGELOG_URL,
        headers={"User-Agent": "Juno-AgySync/1.0"},
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    targets = ["Antigravity App", "Antigravity CLI", "Antigravity IDE"]
    sections: dict[str, list[str]] = {}
    lines = raw.splitlines()

    for target in targets:
        header_pat = re.compile(rf"^##\s+{re.escape(target)}\b", re.IGNORECASE)
        start_idx = None
        for i, line in enumerate(lines):
            if header_pat.match(line.strip()):
                start_idx = i + 1
                break
        if start_idx is None:
            continue

        collected: list[str] = []
        release_count = 0
        for line in lines[start_idx:]:
            stripped = line.strip()
            if stripped.startswith("## "):
                break
            if stripped.startswith("### "):
                release_count += 1
                if release_count > 2:
                    break
            if stripped:
                collected.append(line)
            if len(collected) >= 24:
                break
        if collected:
            sections[target] = collected

    top_marker = ""
    for sec in ("Antigravity App", "Antigravity CLI", "Antigravity IDE"):
        if sections.get(sec):
            top_marker = sections[sec][0].strip()
            break
    return sections, top_marker


def audit_local_environment() -> dict:
    pmap: dict = {}
    if CONFIG_JSON.exists():
        try:
            pmap = json.loads(CONFIG_JSON.read_text(encoding="utf-8")).get("plugins", {})
        except Exception:
            pmap = {}

    active_plugins: list[str] = []
    disabled_plugins: list[str] = []
    active_plugin_skills = 0

    if PLUGINS_DIR.exists():
        for p in sorted(PLUGINS_DIR.iterdir()):
            if not p.is_dir():
                continue
            is_enabled = pmap.get(p.name, {}).get("enabled", True)
            if is_enabled:
                active_plugins.append(p.name)
                active_plugin_skills += len(list(p.rglob("SKILL.md")))
            else:
                disabled_plugins.append(p.name)

    builtin_skills = (
        sorted(p.name for p in BUILTIN_DIR.iterdir() if p.is_dir())
        if BUILTIN_DIR.exists()
        else []
    )
    standalone_skills = (
        len([p for p in GLOBAL_SKILLS_DIR.iterdir() if p.is_dir()])
        if GLOBAL_SKILLS_DIR.exists()
        else 0
    )
    rules_bytes = GLOBAL_RULES.stat().st_size if GLOBAL_RULES.exists() else 0

    return {
        "active_plugins": active_plugins,
        "disabled_plugins": disabled_plugins,
        "active_plugin_skills": active_plugin_skills,
        "builtin_skills": builtin_skills,
        "standalone_skills": standalone_skills,
        "rules_bytes": rules_bytes,
    }


def write_state_markdown(
    app_fp: str,
    env: dict,
    sections: dict[str, list[str]],
    changelog_ok: bool,
) -> None:
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Antigravity Live-Status & Senaste Nytt (Auto-synkad)",
        "",
        f"> **Senast synkad:** {now_iso} | **App-fingeravtryck:** `{app_fp}` | **Changelog-källa:** {'Live (antigravity.google)' if changelog_ok else 'Offline-cache'}",
        "",
        "## Lokal verktygslåda just nu",
        f"- **Aktiva plugins ({len(env['active_plugins'])}):** {', '.join(env['active_plugins']) or 'Inga'}",
        f"- **Avstängda plugins ({len(env['disabled_plugins'])}):** {', '.join(env['disabled_plugins']) or 'Inga'}",
        f"- **Skills i kontext:** {env['active_plugin_skills']} plugin-skills + {len(env['builtin_skills'])} inbyggda + {env['standalone_skills']} globala fristående",
        f"- **Global `AGENTS.md`:** {env['rules_bytes']} / 24 000 bytes",
        f"- **Inbyggda skills:** {', '.join(env['builtin_skills'])}",
        "",
        "## Officiella nyheter (från `changelog.md`)",
    ]

    if sections:
        for title, body in sections.items():
            lines.append(f"### {title}")
            lines.extend(body)
            lines.append("")
    else:
        lines.append("_Kunde inte hämta changelog.md just nu (offline eller timeout). Läs `builtin/skills/antigravity_guide/SKILL.md`._")
        lines.append("")

    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    STATE_MD.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def run_sync(force: bool = False) -> tuple[bool, str]:
    """
    Kör synk vid behov.
    Returnerar (should_notify, notification_text).
    """
    app_fp = compute_app_fingerprint()
    env_fp = compute_env_fingerprint(app_fp)
    cache = load_cache()
    now = time.time()

    app_changed = bool(cache.get("app_fp")) and cache.get("app_fp") != app_fp
    env_changed = cache.get("env_fp") != env_fp
    stale = (now - float(cache.get("last_checked_ts", 0))) >= CHECK_INTERVAL_SEC
    missing_md = not STATE_MD.exists()

    if not (force or app_changed or env_changed or stale or missing_md):
        return False, ""

    sections: dict[str, list[str]] = {}
    top_marker = cache.get("top_changelog_marker", "")
    changelog_ok = False
    changelog_changed = False

    if force or app_changed or stale or missing_md:
        try:
            sections, new_marker = fetch_changelog_sections()
            changelog_ok = True
            if new_marker and cache.get("top_changelog_marker") and new_marker != cache.get("top_changelog_marker"):
                changelog_changed = True
            if new_marker:
                top_marker = new_marker
        except Exception:
            changelog_ok = False

    env = audit_local_environment()
    write_state_markdown(app_fp, env, sections, changelog_ok)

    save_cache(
        {
            "app_fp": app_fp,
            "env_fp": env_fp,
            "last_checked_ts": now,
            "last_checked_iso": datetime.now(timezone.utc).isoformat(),
            "top_changelog_marker": top_marker,
            "changelog_ok": changelog_ok,
        }
    )

    if app_changed or changelog_changed:
        reason = "ny Antigravity-version upptäckt" if app_changed else "nya releasenoter i changelog.md"
        note = (
            f"Antigravity auto-synk: {reason} ({top_marker or app_fp}). "
            f"Uppdaterad sammanfattning finns i C:\\juno-agy\\memory\\antigravity_state.md."
        )
        return True, note

    return False, ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Synka Antigravity-version och changelog till lokal kunskapsfil.")
    parser.add_argument("--hook", action="store_true", help="Kör som Antigravity SessionStart-hook (läs stdin JSON, skriv stdout JSON).")
    parser.add_argument("--force", action="store_true", help="Tvinga full synk oavsett cache.")
    args = parser.parse_args()

    if args.hook:
        try:
            # Läs eventuell stdin-payload utan att hänga
            if not sys.stdin.isatty():
                sys.stdin.read()
            should_notify, note = run_sync(force=args.force)
            if should_notify and note:
                out = {
                    "injectSteps": [
                        {
                            "systemMessage": {
                                "systemMessage": note,
                            }
                        }
                    ]
                }
            else:
                out = {}
            print(json.dumps(out, ensure_ascii=False))
        except Exception:
            print("{}")
        return 0

    should_notify, note = run_sync(force=args.force)
    print(f"Synk klar. Fil: {STATE_MD}")
    if should_notify:
        print(f"Notis: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
