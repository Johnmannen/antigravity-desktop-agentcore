"""Global Kod-, Git- & Backup-förvaltare (repo-janitor) for all Antigravity projects.

Automatically discovers existing and future Git repositories across John's
workspace roots and .gemini/projects.json, checks dirty working trees, unpushed
commits, and secret leaks, proposes clean commit messages, and updates
logs/guardian_alert.json without ever pushing or overwriting remote code.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "logs"
ALERT_FILE = LOGS_DIR / "guardian_alert.json"
REPO_STATUS_FILE = LOGS_DIR / "repo_status.json"
GEMINI_PROJECTS = Path.home() / ".gemini" / "projects.json"

SCAN_ROOTS = [
    Path("C:/"),
    Path.home() / "Documents",
    Path.home() / "Projects",
]
SKIP_DIRS = {
    "Windows", "Program Files", "Program Files (x86)", "ProgramData",
    "$Recycle.Bin", "System Volume Information", "AppData", "node_modules",
    ".venv", "venv", "__pycache__", ".chrome-agent-profile", "juno", "juno-beta",
}
SECRET_FILE_RE = re.compile(r"(^\.env($|\.)|secret|credential|\.pem$|\.key$)", re.IGNORECASE)
SECRET_CONTENT_RE = re.compile(r"(AIza[0-9A-Za-z\-_]{20,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|nvapi-[A-Za-z0-9\-_]{20,})")


def _run_git(repo: Path, *args: str) -> tuple[int, str]:
    no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        creationflags=no_win,
    )
    return proc.returncode, proc.stdout.strip()


def discover_repos() -> list[Path]:
    """Discover Git repositories automatically across scan roots and .gemini/projects.json."""
    found: dict[str, Path] = {}

    for base in SCAN_ROOTS:
        if not base.exists():
            continue
        base_depth = len(base.parts)
        for cur, dirs, _files in os.walk(base):
            cur_path = Path(cur)
            if ".git" in dirs:
                found[str(cur_path).lower()] = cur_path
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith("$")]
            if len(cur_path.parts) - base_depth >= 2:
                dirs[:] = []

    if GEMINI_PROJECTS.exists():
        try:
            data = json.loads(GEMINI_PROJECTS.read_text(encoding="utf-8"))
            paths = data if isinstance(data, list) else data.get("projects", [])
            for item in paths:
                p_str = item.get("path") if isinstance(item, dict) else str(item)
                p = Path(p_str)
                if p.exists() and (p / ".git").exists():
                    found[str(p).lower()] = p
        except Exception:
            pass

    return sorted(found.values(), key=lambda p: p.name.lower())


def inspect_repo(repo: Path) -> dict:
    """Inspect a single Git repository for dirty files, unpushed commits, and secret risks."""
    _rc_br, branch = _run_git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _rc_st, status_out = _run_git(repo, "status", "--porcelain")
    dirty_files = [line[3:].strip() for line in status_out.splitlines() if line.strip()]

    ahead, behind = 0, 0
    has_upstream = False
    rc_ab, ab_out = _run_git(repo, "rev-list", "--left-right", "--count", "@{u}...HEAD")
    if rc_ab == 0 and "\t" in ab_out:
        has_upstream = True
        parts = ab_out.split("\t")
        behind, ahead = int(parts[0]), int(parts[1])

    secret_warnings: list[str] = []
    for f in dirty_files:
        fname = Path(f).name
        if SECRET_FILE_RE.search(fname):
            secret_warnings.append(f"Känslig fil i git status: {f}")

    if dirty_files:
        _rc_df, diff_out = _run_git(repo, "diff", "HEAD")
        if SECRET_CONTENT_RE.search(diff_out):
            secret_warnings.append("Möjlig API-nyckel eller token upptäckt i osparad diff")

    suggested_commit = None
    if dirty_files:
        sample = ", ".join(Path(f).name for f in dirty_files[:3])
        suffix = f" (+{len(dirty_files) - 3} till)" if len(dirty_files) > 3 else ""
        suggested_commit = f"chore({repo.name}): spara {len(dirty_files)} ändrade filer ({sample}{suffix})"

    needs_attention = bool(dirty_files or ahead > 0 or secret_warnings)
    return {
        "name": repo.name,
        "path": str(repo),
        "branch": branch or "unknown",
        "has_upstream": has_upstream,
        "dirty_count": len(dirty_files),
        "dirty_files": dirty_files[:15],
        "ahead_commits": ahead,
        "behind_commits": behind,
        "secret_warnings": secret_warnings,
        "suggested_commit": suggested_commit,
        "needs_attention": needs_attention,
    }


def _merge_alerts(repo_alerts: list[dict], summary: dict) -> None:
    """Merge repo-janitor alerts into logs/guardian_alert.json without clobbering ops/system alerts."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    existing: dict = {"alerts": [], "summary": {}}
    if ALERT_FILE.exists():
        try:
            existing = json.loads(ALERT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    kept = [a for a in existing.get("alerts", []) if not str(a.get("type", "")).startswith("repo_")]
    merged_alerts = kept + repo_alerts
    merged_summary = {**existing.get("summary", {}), "repo_janitor": summary}
    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "alert" if merged_alerts else "ok",
        "alerts": merged_alerts,
        "summary": merged_summary,
    }
    ALERT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_scan(quiet: bool = False) -> dict:
    """Scan all discovered repositories, save repo_status.json, and update guardian_alert.json."""
    repos = discover_repos()
    results = [inspect_repo(r) for r in repos]

    alerts: list[dict] = []
    for r in results:
        if r["secret_warnings"]:
            alerts.append({
                "type": "repo_secret_risk",
                "project": r["name"],
                "path": r["path"],
                "message": f"[{r['name']}] Säkerhetsvarning: {'; '.join(r['secret_warnings'])}",
            })
        elif r["dirty_count"] > 0 or r["ahead_commits"] > 0:
            parts = []
            if r["dirty_count"] > 0:
                parts.append(f"{r['dirty_count']} osparade filer")
            if r["ahead_commits"] > 0:
                parts.append(f"{r['ahead_commits']} opushade commits")
            msg = f"[{r['name']}] {', '.join(parts)}."
            if r["suggested_commit"]:
                msg += f" Förslag: \"{r['suggested_commit']}\""
            alerts.append({
                "type": "repo_pending_changes",
                "project": r["name"],
                "path": r["path"],
                "message": msg,
                "suggested_commit": r["suggested_commit"],
            })

    summary = {
        "repos_scanned": len(results),
        "repos_needing_attention": sum(1 for r in results if r["needs_attention"]),
        "secret_warnings": sum(len(r["secret_warnings"]) for r in results),
    }
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    report = {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "summary": summary, "repos": results}
    REPO_STATUS_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _merge_alerts(alerts, summary)

    if alerts or not quiet:
        return report
    return {"status": "ok", "summary": summary}


def cmd_install_hook(repo_path: str) -> dict:
    """Install a lightweight pre-commit secret guard hook into a Git repository."""
    repo = Path(repo_path)
    hooks_dir = repo / ".git" / "hooks"
    if not hooks_dir.exists():
        return {"error": f"Hittade ingen .git/hooks-mapp i: {repo}"}

    hook_file = hooks_dir / "pre-commit"
    hook_script = (
        "#!/bin/sh\n"
        "# Juno Repo Janitor secret guard\n"
        "if git diff --cached --name-only | grep -iE '(^\\.env($|\\.)|secret|credential|\\.pem$|\\.key$)' >/dev/null; then\n"
        "  echo 'STOPP (repo-janitor): Känslig fil hittad i staged changes!'\n"
        "  exit 1\n"
        "fi\n"
        "if git diff --cached | grep -E '(AIza[0-9A-Za-z_-]{20,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|nvapi-[A-Za-z0-9_-]{20,})' >/dev/null; then\n"
        "  echo 'STOPP (repo-janitor): Möjlig API-nyckel hittad i diff!'\n"
        "  exit 1\n"
        "fi\n"
    )
    hook_file.write_text(hook_script, encoding="utf-8")
    return {"status": "ok", "hook_installed": str(hook_file)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Juno-AGY Global Repo Janitor")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="Scan all discovered Git repos")
    p_scan.add_argument("--quiet", action="store_true")

    p_hook = sub.add_parser("install-hook", help="Install pre-commit secret guard in a repo")
    p_hook.add_argument("path")

    args = parser.parse_args()
    if args.cmd == "install-hook":
        res = cmd_install_hook(args.path)
    else:
        res = cmd_scan(quiet=args.quiet)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
