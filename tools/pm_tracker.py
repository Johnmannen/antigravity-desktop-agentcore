#!/usr/bin/env python3
"""pm_tracker.py — Projektledar- och Att-Göra-List-motor för Juno & Antigravity.

Hanterar avbockningsbara att-göra-listor (TODO_CHECKLIST.md + .juno_pm.json) per projekt
samt ett centralt projektregister i C:/juno-agy/memory/pm_registry.json.

Kärnregler:
1. Mockups före UI-kod: varnar/stoppar om en 'code'-uppgift startas innan projektets
   'mockup'-grind är godkänd ([x]).
2. Äkta avbockning ([x]): en uppgift kan ENBART bockas av som klar ([x]) när den är
   både testad (--test-proof) OCH godkänd av John (--approved-by-john).
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

JUNO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = JUNO_ROOT / "memory" / "pm_registry.json"
AUDIT_LOG = JUNO_ROOT / "logs" / "juno_tools_audit.jsonl"
INIT_PROJECT_SCRIPT = JUNO_ROOT / "tools" / "init_project.py"

VALID_GATES = ("plan", "mockup", "code", "qa", "launch")
VALID_STACKS = ("python", "web", "mobile", "general")

STATUS_CHECKBOX = {
    "todo": "[ ]",
    "in_progress": "[~]",
    "tested": "[?]",
    "done": "[x]",
}

STATUS_LABEL = {
    "todo": "Att göra",
    "in_progress": "Pågår",
    "tested": "Testad — väntar Johns OK",
    "done": "Klart & godkänt",
}


class PMTrackerError(Exception):
    """Kontrollerat domänfel vid brott mot projektledargrinden."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _log_audit(action: str, details: dict[str, Any]) -> None:
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool": "pm_tracker",
            "action": action,
            "details": details,
        }
        with AUDIT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _state_paths(project_dir: Path) -> tuple[Path, Path]:
    pdir = project_dir.expanduser().resolve()
    return pdir / ".juno_pm.json", pdir / "TODO_CHECKLIST.md"


def load_project_state(project_dir: Path) -> dict[str, Any]:
    json_path, _ = _state_paths(project_dir)
    if not json_path.exists():
        raise PMTrackerError(
            f"Ingen projektstatus hittades i {project_dir}. Kör 'pm_tracker.py init' först."
        )
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PMTrackerError(f"Korrupt .juno_pm.json i {project_dir}: {exc}") from exc


def render_checklist_markdown(state: dict[str, Any]) -> str:
    tasks: list[dict[str, Any]] = state.get("tasks", [])
    done_count = sum(1 for t in tasks if t.get("status") == "done")
    total_count = len(tasks)
    pct = int(round((done_count / total_count) * 100)) if total_count else 0

    lines: list[str] = [
        f"# 📋 Att-Göra-Lista & Projektstatus: {state['name']}",
        "",
        f"> **Mål:** {state['goal']}",
        f"> **Framsteg:** **{done_count} / {total_count} klara ({pct} %)** | **Stack:** `{state['stack']}` | **Uppdaterad:** {state['updated_at']}",
        "",
        "**Förklaring:** `[ ]` Att göra · `[~]` Pågår · `[?]` Färdigbyggd & live-testad (väntar Johns OK) · `[x]` Godkänd & avbockad",
        "",
    ]

    notes: list[dict[str, str]] = state.get("proactive_notes", [])
    if notes:
        lines.append("## 💡 Projektledarens Aktiva Påminnelser & Riskvakter")
        for n in notes:
            lines.append(f"- ⚠️ **{n['created_at']}:** {n['text']}")
        lines.append("")

    # Gruppera uppgifter per fas i den ordning faserna dyker upp
    phases_order: list[str] = []
    by_phase: dict[str, list[dict[str, Any]]] = {}
    for t in tasks:
        ph = t.get("phase", "Allmänt")
        if ph not in by_phase:
            phases_order.append(ph)
            by_phase[ph] = []
        by_phase[ph].append(t)

    lines.append("## ✅ Avbockningsbar Checklista")
    lines.append("")
    if not tasks:
        lines.append("_Inga punkter tillagda ännu. Lägg till med `pm_tracker.py add`._")
        lines.append("")
    else:
        for ph in phases_order:
            lines.append(f"### {ph}")
            for t in by_phase[ph]:
                box = STATUS_CHECKBOX.get(t["status"], "[ ]")
                gate_tag = f"`[{t['gate']}]`" if t.get("gate") else ""
                line = f"- {box} **{t['id']}** {gate_tag} {t['title']}".replace("  ", " ")
                lines.append(line)
                if t.get("notes"):
                    lines.append(f"  - *Notering:* {t['notes']}")
                if t.get("test_proof"):
                    lines.append(f"  - *Verifierat test:* {t['test_proof']}")
                if t.get("approved_at"):
                    lines.append(f"  - *Godkänd av John:* {t['approved_at']}")
            lines.append("")

    # Nästa rekommenderade steg
    next_task = next(
        (t for t in tasks if t["status"] in ("in_progress", "tested", "todo")),
        None,
    )
    lines.append("---")
    lines.append("## 🧭 Nästa Fokus")
    if next_task:
        st_lbl = STATUS_LABEL.get(next_task["status"], next_task["status"])
        lines.append(
            f"- **Aktuell punkt:** `{next_task['id']}` — **{next_task['title']}** *(Status: {st_lbl})*"
        )
    else:
        lines.append("- 🎉 Alla punkter i listan är färdigbyggda, testade och godkända!")

    return "\n".join(lines).rstrip() + "\n"


def save_project_state(project_dir: Path, state: dict[str, Any]) -> Path:
    pdir = project_dir.expanduser().resolve()
    json_path, md_path = _state_paths(pdir)
    state["updated_at"] = _now_iso()
    json_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_checklist_markdown(state), encoding="utf-8")
    _sync_registry(pdir, state)
    return md_path


def _sync_registry(project_dir: Path, state: dict[str, Any]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    reg: dict[str, Any] = {"projects": {}}
    if REGISTRY_PATH.exists():
        try:
            reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            reg = {"projects": {}}
    if "projects" not in reg or not isinstance(reg["projects"], dict):
        reg["projects"] = {}

    tasks = state.get("tasks", [])
    done_count = sum(1 for t in tasks if t.get("status") == "done")
    next_task = next((t for t in tasks if t["status"] != "done"), None)

    reg["projects"][str(project_dir)] = {
        "name": state["name"],
        "goal": state["goal"],
        "stack": state["stack"],
        "path": str(project_dir),
        "checklist_path": str(project_dir / "TODO_CHECKLIST.md"),
        "done": done_count,
        "total": len(tasks),
        "next_task": f"{next_task['id']}: {next_task['title']} ({next_task['status']})" if next_task else "KLART",
        "updated_at": state["updated_at"],
    }
    REGISTRY_PATH.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_init(args: argparse.Namespace) -> int:
    pdir = Path(args.project_dir).expanduser().resolve()
    pdir.mkdir(parents=True, exist_ok=True)

    # Säkerställ att lokal AGENTS.md och .gitignore finns via init_project.py
    if INIT_PROJECT_SCRIPT.exists() and not (pdir / "AGENTS.md").exists():
        subprocess.run(
            [sys.executable, str(INIT_PROJECT_SCRIPT), str(pdir), "--stack", args.stack, "--name", args.name],
            capture_output=True,
            text=True,
            check=False,
        )

    json_path, md_path = _state_paths(pdir)
    if json_path.exists() and not args.force:
        state = load_project_state(pdir)
        print(json.dumps({"status": "exists", "checklist": str(md_path), "name": state["name"]}, ensure_ascii=False))
        return 0

    # Säkerställ att .juno_pm.json inte läcker hemligheter men spåras rent lokalt
    state: dict[str, Any] = {
        "name": args.name,
        "goal": args.goal,
        "stack": args.stack,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "proactive_notes": [],
        "tasks": [],
    }
    save_project_state(pdir, state)
    _log_audit("init", {"project_dir": str(pdir), "name": args.name, "stack": args.stack})
    print(
        json.dumps(
            {
                "status": "initialized",
                "project_dir": str(pdir),
                "checklist": str(md_path),
                "name": args.name,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    pdir = Path(args.project_dir).expanduser().resolve()
    state = load_project_state(pdir)
    tasks: list[dict[str, Any]] = state.setdefault("tasks", [])
    next_num = len(tasks) + 1
    task_id = args.id.strip().upper() if args.id else f"T{next_num:02d}"

    if any(t["id"] == task_id for t in tasks):
        raise PMTrackerError(f"Uppgifts-ID {task_id} finns redan i projektet.")

    task = {
        "id": task_id,
        "phase": args.phase,
        "title": args.title,
        "gate": args.gate,
        "status": "todo",
        "notes": args.notes or "",
        "test_proof": "",
        "approved_at": "",
    }
    tasks.append(task)
    md_path = save_project_state(pdir, state)
    _log_audit("add_task", {"project_dir": str(pdir), "task_id": task_id, "title": args.title})
    print(json.dumps({"status": "added", "task": task, "checklist": str(md_path)}, ensure_ascii=False, indent=2))
    return 0


def _find_task(state: dict[str, Any], task_id: str) -> dict[str, Any]:
    tid = task_id.strip().upper()
    for t in state.get("tasks", []):
        if t["id"].upper() == tid:
            return t
    raise PMTrackerError(f"Hittade ingen uppgift med ID '{tid}'.")


def cmd_start(args: argparse.Namespace) -> int:
    pdir = Path(args.project_dir).expanduser().resolve()
    state = load_project_state(pdir)
    task = _find_task(state, args.task_id)

    # Proaktiv projektledarspärr: varna/stoppa om UI/kod startas före oavklarade mockups!
    if task.get("gate") == "code" and not args.override_mockup_gate:
        unapproved_mockups = [
            t["id"] for t in state.get("tasks", [])
            if t.get("gate") == "mockup" and t.get("status") != "done"
        ]
        if unapproved_mockups:
            raise PMTrackerError(
                f"PROAKTIV SPÄRR (Mockups först): Uppgiften {task['id']} är en kod-uppgift, men "
                f"mockup-punkterna {', '.join(unapproved_mockups)} är ännu inte godkända ([x]) av John. "
                f"Gör klart och få Johns OK på mockups först!"
            )

    task["status"] = "in_progress"
    md_path = save_project_state(pdir, state)
    _log_audit("start_task", {"project_dir": str(pdir), "task_id": task["id"]})
    print(json.dumps({"status": "in_progress", "task": task, "checklist": str(md_path)}, ensure_ascii=False, indent=2))
    return 0


def cmd_mark_tested(args: argparse.Namespace) -> int:
    pdir = Path(args.project_dir).expanduser().resolve()
    state = load_project_state(pdir)
    task = _find_task(state, args.task_id)
    proof = args.test_proof.strip()
    if len(proof) < 5:
        raise PMTrackerError("Ange ett konkret --test-proof som beskriver vad som har testats skarpt.")

    task["status"] = "tested"
    task["test_proof"] = proof
    md_path = save_project_state(pdir, state)
    _log_audit("mark_tested", {"project_dir": str(pdir), "task_id": task["id"], "proof": proof})
    print(
        json.dumps(
            {
                "status": "tested_awaiting_john_ok",
                "message": f"{task['id']} är markerad som [?] Testad. Visa resultatet för John och invänta hans OK innan 'check' körs.",
                "task": task,
                "checklist": str(md_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    pdir = Path(args.project_dir).expanduser().resolve()
    state = load_project_state(pdir)
    task = _find_task(state, args.task_id)

    if not args.approved_by_john:
        raise PMTrackerError(
            "BLOCKERAD AVBOCKNING: Ingen punkt får bockas av [x] utan Johns uttryckliga godkännande. "
            "Kör 'mark-tested' först, presentera för John, och kör 'check --approved-by-john' först efter hans OK."
        )

    if args.test_proof:
        task["test_proof"] = args.test_proof.strip()

    if not task.get("test_proof"):
        raise PMTrackerError(
            f"BLOCKERAD AVBOCKNING: Uppgiften {task['id']} saknar verifierat testbevis (--test-proof). "
            "Alla punkter måste verifieras/testas innan de bockas av."
        )

    task["status"] = "done"
    task["approved_at"] = _now_iso()
    md_path = save_project_state(pdir, state)

    next_task = next((t for t in state.get("tasks", []) if t["status"] != "done"), None)
    _log_audit("check_done", {"project_dir": str(pdir), "task_id": task["id"]})
    print(
        json.dumps(
            {
                "status": "checked_done",
                "completed_task": task["id"],
                "next_recommended_task": next_task,
                "checklist": str(md_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    pdir = Path(args.project_dir).expanduser().resolve()
    state = load_project_state(pdir)
    notes = state.setdefault("proactive_notes", [])
    if args.clear:
        state["proactive_notes"] = []
    elif args.risk:
        notes.append({"created_at": _now_iso(), "text": args.risk.strip()})
    md_path = save_project_state(pdir, state)
    print(json.dumps({"status": "updated_notes", "count": len(state["proactive_notes"]), "checklist": str(md_path)}, ensure_ascii=False))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    pdir = Path(args.project_dir).expanduser().resolve()
    state = load_project_state(pdir)
    tasks = state.get("tasks", [])
    done_c = sum(1 for t in tasks if t["status"] == "done")
    tested_c = sum(1 for t in tasks if t["status"] == "tested")
    active = [t for t in tasks if t["status"] == "in_progress"]
    upcoming = next((t for t in tasks if t["status"] == "todo"), None)

    out = {
        "name": state["name"],
        "goal": state["goal"],
        "progress": f"{done_c}/{len(tasks)} klara",
        "awaiting_john_approval": [f"{t['id']}: {t['title']}" for t in tasks if t["status"] == "tested"],
        "in_progress": [f"{t['id']}: {t['title']}" for t in active],
        "next_todo": f"{upcoming['id']}: {upcoming['title']} [{upcoming['gate']}]" if upcoming else None,
        "proactive_notes": state.get("proactive_notes", []),
        "tested_count": tested_c,
        "checklist_file": str(pdir / "TODO_CHECKLIST.md"),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_overview(_args: argparse.Namespace) -> int:
    if not REGISTRY_PATH.exists():
        print(json.dumps({"projects": {}}, ensure_ascii=False, indent=2))
        return 0
    reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    print(json.dumps(reg, ensure_ascii=False, indent=2))
    return 0


def cmd_session_hook(_args: argparse.Namespace) -> int:
    """Snabb SessionStart-hook för Antigravity som påminner om aktiva projektlistor."""
    try:
        if not sys.stdin.isatty():
            sys.stdin.read()
        if not REGISTRY_PATH.exists():
            print("{}")
            return 0
        reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        projects = reg.get("projects", {})
        active_summaries = []
        for p in projects.values():
            if p.get("done", 0) < p.get("total", 0):
                active_summaries.append(
                    f"{p['name']} ({p['done']}/{p['total']} klara — nästa: {p['next_task']})"
                )
        if not active_summaries:
            print("{}")
            return 0
        msg = "Projektledar-status (aktiva att-göra-listor): " + " | ".join(active_summaries[:4])
        print(
            json.dumps(
                {"injectSteps": [{"systemMessage": {"systemMessage": msg}}]},
                ensure_ascii=False,
            )
        )
        return 0
    except Exception:
        print("{}")
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Projektledar- och Att-Göra-List-motor för Juno & Antigravity."
    )
    parser.add_argument(
        "--session-hook",
        action="store_true",
        help="Körs som tyst Antigravity SessionStart-hook.",
    )
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Initiera projekt och avbockningsbar TODO_CHECKLIST.md.")
    p_init.add_argument("project_dir", help="Sökväg till projektmapp.")
    p_init.add_argument("--name", required=True, help="Projektnamn.")
    p_init.add_argument("--goal", required=True, help="Kort målbeskrivning.")
    p_init.add_argument("--stack", choices=VALID_STACKS, default="web", help="Teknikstack.")
    p_init.add_argument("--force", action="store_true", help="Återskapa statusfil.")

    p_add = sub.add_parser("add", help="Lägg till en avbockningsbar uppgift i checklistan.")
    p_add.add_argument("project_dir", help="Sökväg till projektmapp.")
    p_add.add_argument("--phase", required=True, help="Fasrubrik (t.ex. 'Fas 1: Design & Mockups').")
    p_add.add_argument("--title", required=True, help="Konkret uppgift.")
    p_add.add_argument("--gate", choices=VALID_GATES, default="code", help="Typ av kvalitetsgrind.")
    p_add.add_argument("--notes", default="", help="Valfri notering eller krav.")
    p_add.add_argument("--id", default="", help="Valfritt eget ID (annars T01, T02...).")

    p_start = sub.add_parser("start", help="Markera uppgift som pågående [~] (kontrollerar mockup-spärr).")
    p_start.add_argument("project_dir", help="Sökväg till projektmapp.")
    p_start.add_argument("task_id", help="Uppgifts-ID, t.ex. T01.")
    p_start.add_argument("--override-mockup-gate", action="store_true", help="Tillåt trots oavklarad mockup (endast backend).")

    p_tested = sub.add_parser("mark-tested", help="Markera uppgift som testad [?] inför Johns godkännande.")
    p_tested.add_argument("project_dir", help="Sökväg till projektmapp.")
    p_tested.add_argument("task_id", help="Uppgifts-ID, t.ex. T01.")
    p_tested.add_argument("--test-proof", required=True, help="Kort bevis på genomfört live-test/granskning.")

    p_check = sub.add_parser("check", help="Bocka av [x] som klar (KRÄVER testbevis + godkännande).")
    p_check.add_argument("project_dir", help="Sökväg till projektmapp.")
    p_check.add_argument("task_id", help="Uppgifts-ID, t.ex. T01.")
    p_check.add_argument(
        "--approved-by-john",
        "--approved",
        dest="approved_by_john",
        action="store_true",
        help="Bekräftar att användaren gett uttryckligt OK.",
    )
    p_check.add_argument("--test-proof", default="", help="Testbevis (om ej redan satt via mark-tested).")

    p_note = sub.add_parser("note", help="Lägg till eller rensa proaktiv projektledar-påminnelse.")
    p_note.add_argument("project_dir", help="Sökväg till projektmapp.")
    p_note.add_argument("--risk", default="", help="Text för proaktiv varning/förslag.")
    p_note.add_argument("--clear", action="store_true", help="Rensa aktiva påminnelser.")

    p_status = sub.add_parser("status", help="Visa aktuell status och nästa steg för projektet.")
    p_status.add_argument("project_dir", help="Sökväg till projektmapp.")

    sub.add_parser("overview", help="Visa översikt över alla registrerade projekt.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.session_hook:
        return cmd_session_hook(args)

    if not args.command:
        parser.print_help()
        return 2

    dispatch = {
        "init": cmd_init,
        "add": cmd_add,
        "start": cmd_start,
        "mark-tested": cmd_mark_tested,
        "check": cmd_check,
        "note": cmd_note,
        "status": cmd_status,
        "overview": cmd_overview,
    }
    try:
        return dispatch[args.command](args)
    except PMTrackerError as exc:
        print(json.dumps({"error": str(exc), "status": "blocked"}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
