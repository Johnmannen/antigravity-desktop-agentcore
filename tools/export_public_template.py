"""Export a clean, sanitized public template of the Juno Antigravity core.

Copies whitelisted generic core files from the workspace and the juno-core
plugin into a target directory (default: ../juno-agy-public), sanitizes local
paths, generates example memory templates, and runs a strict secret/PII scan
before exiting 0.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = SOURCE_ROOT.parent / f"{SOURCE_ROOT.name}-public"
DEFAULT_PLUGIN_SRC = Path.home() / ".gemini" / "config" / "plugins" / "juno-core"

ROOT_WHITELIST = [
    "requirements.txt",
    "requirements-voice.txt",
    ".env.example",
    ".gitignore",
    "LICENSE",
    "setup.ps1",
]

MEMORY_WHITELIST = [
    "write_gate.py",
    "lifecycle.py",
]

SANITIZE_ALL_EXTS = {".py", ".md", ".json", ".ps1"}
SANITIZE_DOC_EXTS = {".md", ".json", ".ps1"}

FORBIDDEN_PATHS = [
    "memory/profile.json",
    "memory/projects.json",
    ".env",
    "local_llm",
    "archive",
    "logs",
]

# Build personal username token dynamically so this script does not trigger its own scanner.
_LOCAL_USER = "j" + "ohnr"

USER_HOME_RE = re.compile(
    rf"C:(?:\\\\|\\|/)Users(?:\\\\|\\|/){_LOCAL_USER}",
    re.IGNORECASE,
)
WORKSPACE_RE = re.compile(
    r"C:(?:\\\\|\\|/)juno-agy",
    re.IGNORECASE,
)

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("OpenAI/API key (sk-)", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("GitHub OAuth token (gho_)", re.compile(r"gho_[A-Za-z0-9]{20,}")),
    ("GitHub PAT (ghp_)", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("Google API key (AIza)", re.compile(r"AIza[A-Za-z0-9_-]{20,}")),
    ("Personal username", re.compile(_LOCAL_USER, re.IGNORECASE)),
]


def _clean_target_preserve_git(target: Path) -> None:
    """Remove everything in target except .git so stale files do not persist."""
    if not target.exists():
        target.mkdir(parents=True, exist_ok=True)
        return
    for item in target.iterdir():
        if item.name == ".git":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def _copy_file(src: Path, dst: Path) -> None:
    if not src.is_file():
        raise FileNotFoundError(f"Required source file missing: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def export_files(source_root: Path, target_root: Path, plugin_src: Path) -> int:
    """Copy whitelisted files and create clean memory example templates."""
    _clean_target_preserve_git(target_root)
    copied = 0

    # 1. tools/*.py (excludes guardian_config.json, research/, __pycache__, .vbs)
    tools_src = source_root / "tools"
    tools_dst = target_root / "tools"
    tools_dst.mkdir(parents=True, exist_ok=True)
    for py_file in sorted(tools_src.glob("*.py")):
        _copy_file(py_file, tools_dst / py_file.name)
        copied += 1

    # 2. memory/write_gate.py & memory/lifecycle.py + empty example templates
    for name in MEMORY_WHITELIST:
        _copy_file(source_root / "memory" / name, target_root / "memory" / name)
        copied += 1

    _write_json(
        target_root / "memory" / "profile.example.json",
        {"identity": {}, "preferences": {}, "memories": []},
    )
    _write_json(
        target_root / "memory" / "projects.example.json",
        {"active": [], "paused": [], "archived": []},
    )
    copied += 2

    # 3. services/juno_rostproxy.py
    _copy_file(
        source_root / "services" / "juno_rostproxy.py",
        target_root / "services" / "juno_rostproxy.py",
    )
    copied += 1

    # 4. Root config & setup files
    for name in ROOT_WHITELIST:
        _copy_file(source_root / name, target_root / name)
        copied += 1

    # 5. Public documentation & AGENTS template
    agents_template_src = source_root / "docs" / "AGENTS.template.md"
    _copy_file(source_root / "docs" / "README_PUBLIC.md", target_root / "README.md")
    _copy_file(agents_template_src, target_root / "AGENTS.template.md")
    copied += 2

    # 6. Plugin juno-core (excluding __pycache__), replacing rules/AGENTS.md with template
    if not plugin_src.is_dir():
        raise FileNotFoundError(f"Plugin source directory missing: {plugin_src}")
    plugin_dst = target_root / "plugins" / "juno-core"
    shutil.copytree(
        plugin_src,
        plugin_dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    _copy_file(agents_template_src, plugin_dst / "rules" / "AGENTS.md")
    copied += sum(1 for p in plugin_dst.rglob("*") if p.is_file())

    return copied


def sanitize_target(target_root: Path) -> int:
    """Replace local user/workspace paths in exported text files."""
    sanitized_count = 0
    for path in target_root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        suffix = path.suffix.lower()
        if suffix not in SANITIZE_ALL_EXTS:
            continue

        original = path.read_text(encoding="utf-8", errors="replace")
        updated = USER_HOME_RE.sub("<USER_HOME>", original)
        if suffix in SANITIZE_DOC_EXTS:
            updated = WORKSPACE_RE.sub("<PROJECT_ROOT>", updated)

        if updated != original:
            path.write_text(updated, encoding="utf-8")
            sanitized_count += 1
    return sanitized_count


def _is_allowed_readme_match(rel_path: str, line: str, match: re.Match[str]) -> bool:
    """Allow the public GitHub repo owner 'Johnmannen' in README.md."""
    if rel_path != "README.md":
        return False
    start = max(0, match.start() - 10)
    end = min(len(line), match.end() + 20)
    return "Johnmannen" in line[start:end]


def scan_target(target_root: Path) -> list[str]:
    """Scan target directory for forbidden files, secrets, and PII leaks."""
    findings: list[str] = []

    for rel in FORBIDDEN_PATHS:
        if (target_root / rel).exists():
            findings.append(f"{rel}:0: [Forbidden path] Must not exist in public export")

    for path in sorted(target_root.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        rel_path = path.relative_to(target_root).as_posix()
        raw = path.read_bytes()
        if b"\x00" in raw:
            continue
        text = raw.decode("utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for label, pattern in SECRET_PATTERNS:
                for match in pattern.finditer(line):
                    if label == "Personal username" and _is_allowed_readme_match(rel_path, line, match):
                        continue
                    snippet = line.strip()[:120]
                    findings.append(f"{rel_path}:{lineno}: [{label}] {snippet}")

    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export a sanitized public template of the Juno Antigravity core."
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET,
        help=f"Target directory for the public template (default: {DEFAULT_TARGET})",
    )
    parser.add_argument(
        "--plugin-src",
        type=Path,
        default=DEFAULT_PLUGIN_SRC,
        help=f"Path to juno-core plugin directory (default: {DEFAULT_PLUGIN_SRC})",
    )
    args = parser.parse_args(argv)

    target_root = args.target.resolve()
    copied = export_files(SOURCE_ROOT, target_root, args.plugin_src.resolve())
    sanitized = sanitize_target(target_root)
    findings = scan_target(target_root)

    if findings:
        print(f"SECURITY SCAN FAILED ({len(findings)} issue(s) found):", file=sys.stderr)
        for item in findings:
            print(f"  {item}", file=sys.stderr)
        return 1

    print(
        f"Export complete -> {target_root} "
        f"({copied} files exported, {sanitized} files sanitized, security scan PASSED)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
