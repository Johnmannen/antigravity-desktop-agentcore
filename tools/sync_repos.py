"""Synchronize the private Juno workspace and the sanitized public template repo.

Step A: Commit and push pending changes in the private repo (origin).
Step B: Run export_public_template.py into the public repo directory; abort on failure.
Step C: Commit and push changes in the public repo (origin).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PRIVATE_REPO = Path(__file__).resolve().parent.parent
PUBLIC_REPO = PRIVATE_REPO.parent / f"{PRIVATE_REPO.name}-public"
EXPORT_SCRIPT = PRIVATE_REPO / "tools" / "export_public_template.py"


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=no_win,
    )


def _sync_git_repo(repo: Path, label: str, message: str, dry_run: bool) -> bool:
    if not (repo / ".git").exists():
        print(f"[{label}] Error: '{repo}' is not a Git repository.", file=sys.stderr)
        return False

    status = _run(["git", "status", "--short"], repo)
    if status.returncode != 0:
        print(f"[{label}] git status failed:\n{status.stderr.strip()}", file=sys.stderr)
        return False

    changes = status.stdout.strip()
    if not changes:
        print(f"[{label}] Clean working tree — nothing to commit.")
        return True

    print(f"[{label}] Changes detected:\n{changes}")
    if dry_run:
        print(f"[{label}] [dry-run] Would run: git add -A && git commit -m {message!r} && git push")
        return True

    for step_cmd in (
        ["git", "add", "-A"],
        ["git", "commit", "-m", message],
        ["git", "push"],
    ):
        proc = _run(step_cmd, repo)
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            print(f"[{label}] Command {' '.join(step_cmd)} failed:\n{detail}", file=sys.stderr)
            return False

    print(f"[{label}] Committed and pushed to origin.")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sync private juno-agy repo and export/push public template repo."
    )
    parser.add_argument(
        "--message",
        "-m",
        default="chore: sync juno-agy and public template",
        help="Commit message used for changed repositories.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview git status and export without committing or pushing.",
    )
    parser.add_argument(
        "--public-target",
        type=Path,
        default=PUBLIC_REPO,
        help=f"Path to public template repo (default: {PUBLIC_REPO})",
    )
    args = parser.parse_args(argv)
    public_repo = args.public_target.resolve()

    # Step A: Private repo
    print("=== Step A: Private repository ===")
    if not _sync_git_repo(PRIVATE_REPO, "private", args.message, args.dry_run):
        return 1

    # Step B: Sanitized export (aborts immediately on failure)
    print("=== Step B: Export public template ===")
    export_proc = _run(
        [sys.executable, str(EXPORT_SCRIPT), "--target", str(public_repo)],
        PRIVATE_REPO,
    )
    if export_proc.stdout.strip():
        print(export_proc.stdout.strip())
    if export_proc.returncode != 0:
        if export_proc.stderr.strip():
            print(export_proc.stderr.strip(), file=sys.stderr)
        print("Export failed — aborting before public push.", file=sys.stderr)
        return export_proc.returncode

    # Step C: Public repo
    print("=== Step C: Public repository ===")
    if not _sync_git_repo(public_repo, "public", args.message, args.dry_run):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
