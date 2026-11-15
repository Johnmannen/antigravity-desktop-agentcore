"""CLI wrapper for Juno's memory write_gate and lifecycle in C:\\juno-agy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = ROOT / "memory"
sys.path.insert(0, str(MEMORY_DIR))

import lifecycle  # noqa: E402
import write_gate  # noqa: E402


def cmd_status(_args: argparse.Namespace) -> None:
    profile = json.loads((MEMORY_DIR / "profile.json").read_text(encoding="utf-8"))
    projects = json.loads((MEMORY_DIR / "projects.json").read_text(encoding="utf-8"))
    pending = write_gate.list_pending()
    energy = profile.get("current_state", {}).get("energy_level")
    out = {
        "energy_level": energy,
        "reminders_count": len(profile.get("reminders", [])),
        "memories_count": len(profile.get("memories", [])),
        "active_projects": [p.get("name") for p in projects.get("active", [])],
        "pending_updates": len(pending),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_pending(_args: argparse.Namespace) -> None:
    print(json.dumps(write_gate.list_pending(), ensure_ascii=False, indent=2))


def cmd_stage(args: argparse.Namespace) -> None:
    payload = json.loads(args.payload)
    res = write_gate.stage(args.target, args.operation, payload, user=args.user)
    print(json.dumps(res, ensure_ascii=False, indent=2))


def cmd_approve(args: argparse.Namespace) -> None:
    res = write_gate.approve(args.pending_id, user="john")
    print(json.dumps(res, ensure_ascii=False, indent=2))


def cmd_reject(args: argparse.Namespace) -> None:
    res = write_gate.reject(args.pending_id, user="john")
    print(json.dumps(res, ensure_ascii=False, indent=2))


def cmd_energy(args: argparse.Namespace) -> None:
    value = max(0, min(100, args.value))
    payload = {
        "current_state": {"energy_level": value, "last_updated": lifecycle._now()},
        "anvandare": {"energi": value},
    }
    staged = write_gate.stage("profile.json", "patch", payload, user="john")
    if "pending_id" in staged:
        res = write_gate.approve(staged["pending_id"], user="john")
        print(json.dumps({"energy_level": value, "result": res}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(staged, ensure_ascii=False, indent=2))


def cmd_learn(args: argparse.Namespace) -> None:
    """Autonomously record a concise fact or preference into profile.json memories."""
    hits = write_gate.secret_scan(args.text)
    if hits:
        write_gate._audit("learn_blocked_secret", user="juno", target="profile.json", ok=False, note=";".join(hits[:3]))
        print(json.dumps({"error": f"Blockerad av sekretfilter ({hits[0]})", "code": "SECRET_FILTERED"}, ensure_ascii=False, indent=2))
        return

    entry = lifecycle.normalize_entry(
        args.text,
        stability=args.stability,
        source=args.source,
        importance=args.importance,
    )
    profile_path = MEMORY_DIR / "profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    mems = profile.get("memories", [])
    cleaned, updates = lifecycle.dedup(mems + [entry])
    profile["memories"] = cleaned

    size = len(json.dumps(profile, ensure_ascii=False))
    limit = write_gate.FILE_LIMITS.get("profile.json", 8192)
    if size > limit:
        write_gate._audit("learn_blocked_full", user="juno", target="profile.json", ok=False, note=f"{size}>{limit}")
        print(json.dumps({"error": f"FILE_FULL: profile.json skulle bli {size} tecken (tak {limit}). Konsolidera först.", "code": "FILE_FULL"}, ensure_ascii=False, indent=2))
        return

    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    action = "updated" if updates else "added"
    write_gate._audit("auto_learn", user="juno", target="profile.json", ok=True, note=f"{action}:{entry['id']}")
    print(json.dumps({"status": action, "entry": entry, "memories_count": len(cleaned), "size": size}, ensure_ascii=False, indent=2))


def cmd_memories(_args: argparse.Namespace) -> None:
    """List all learned memories stored in profile.json."""
    print(json.dumps(lifecycle.get_memories(), ensure_ascii=False, indent=2))


def cmd_maintain(_args: argparse.Namespace) -> None:
    """Run non-destructive lifecycle maintenance: dedup, stale check, and old pending cleanup."""
    profile_path = MEMORY_DIR / "profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    mems = profile.get("memories", [])
    cleaned, updates = lifecycle.dedup(mems)
    if updates:
        profile["memories"] = cleaned
        profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    stale = lifecycle.find_stale(cleaned)
    _, decayed = lifecycle.prune(cleaned)
    cleared_pending = write_gate.clear_old_pending()

    report = {
        "memories_total": len(cleaned),
        "dedup_updates": len(updates),
        "stale_count": len(stale),
        "decayed_count": len(decayed),
        "cleared_old_pending": cleared_pending,
    }
    write_gate._audit("maintain", user="juno", target="profile.json", ok=True, note=json.dumps(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Juno-AGY Memory CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Show memory status, energy, and active projects")
    sub.add_parser("pending", help="List pending memory updates")

    p_stage = sub.add_parser("stage", help="Stage a memory update into memory/pending/")
    p_stage.add_argument("target", choices=["profile.json", "projects.json", "juno_minne.json"])
    p_stage.add_argument("operation", choices=["write", "patch", "append"])
    p_stage.add_argument("payload", help="JSON string payload")
    p_stage.add_argument("--user", default="juno")

    p_app = sub.add_parser("approve", help="Approve a pending update")
    p_app.add_argument("pending_id")

    p_rej = sub.add_parser("reject", help="Reject a pending update")
    p_rej.add_argument("pending_id")

    p_en = sub.add_parser("energy", help="Explicitly set John's energy level (0-100)")
    p_en.add_argument("value", type=int)

    p_learn = sub.add_parser("learn", help="Autonomously save a concise fact or preference with secret-scan and dedup")
    p_learn.add_argument("text", help="Concise fact or preference to remember")
    p_learn.add_argument("--stability", choices=["stable", "fluid", "transient"], default="fluid")
    p_learn.add_argument("--source", default="auto_learn")
    p_learn.add_argument("--importance", type=int, default=None)

    sub.add_parser("memories", help="List learned memories in profile.json")
    sub.add_parser("maintain", help="Run non-destructive memory lifecycle maintenance")

    args = parser.parse_args()
    {
        "status": cmd_status,
        "pending": cmd_pending,
        "stage": cmd_stage,
        "approve": cmd_approve,
        "reject": cmd_reject,
        "energy": cmd_energy,
        "learn": cmd_learn,
        "memories": cmd_memories,
        "maintain": cmd_maintain,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
