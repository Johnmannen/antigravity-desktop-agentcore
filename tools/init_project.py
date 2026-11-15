"""Initialize a local project folder with a stack-specific AGENTS.md and .gitignore.

This tool installs the lightweight local layer (stack-specific AGENTS.md + .gitignore)
without copying central Python tools or memory files, which remain in the central
Juno root (resolved dynamically via Path(__file__).resolve().parent.parent).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

JUNO_ROOT = Path(__file__).resolve().parent.parent
MEMORY_CLI = Path(__file__).resolve().parent / "memory_cli.py"

VALID_STACKS = ("python", "web", "mobile", "general")

GITIGNORE_CONTENT = """# Python & environments
.venv/
__pycache__/
*.py[cod]

# Node & frontend
node_modules/

# Secrets & local config
.env
.env.local

# Logs & build artifacts
logs/
dist/
build/
"""


def _slugify(name: str) -> str:
    """Create a safe lowercase project ID from a display name."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "project"


def _stack_section(stack: str, juno_root: Path) -> str:
    """Return stack-specific rules and workflow instructions."""
    chrome_agent = juno_root / "tools" / "chrome_agent.py"

    if stack == "python":
        return f"""## Stack: Python

- **Miljö:** Använd projektets lokala `.venv` (eller central `{juno_root}\\.venv\\Scripts\\python.exe` för Juno-verktyg).
- **Kodkvalitet:** Skriv ren, modulär och typsäker Python-kod. Följ skill `error-handling-patterns` för robust felhantering och `refactor-cleaner` för att hålla borta död kod.
- **Verifiering (obligatorisk):**
  1. Kör `python -m py_compile <ändrade_filer>` efter varje ändring.
  2. Kör `pytest` (eller motsvarande testsvit) mot verkliga fall innan slutförande.
  3. Passera `post-verify` (live-test, beställningskontroll, regelkontroll)."""

    if stack == "web":
        return f"""## Stack: Webb & UI

- **Design & Arkitektur:** Följ `modern-web-guidance` och `antigravity-design-expert` för modern, responsiv och tillgänglig UI-design.
- **Tillgänglighet & Prestanda:** Använd `a11y-debugging` och `chrome-devtools` för att kontrollera ARIA, kontraster, tangentbordsnavigering, konsolfel och nätverksanrop.
- **Tvåstegs `post-verify` (obligatorisk före överlämning):**
  1. *Tyst teknisk röntgen:* Testa desktop- och mobil-viewport via `chrome-devtools` (konsol, nätverk, overflow/layout).
  2. *Synlig live-demo:* Kör `python "{chrome_agent}" demo "<app-url>" --keep-open --screenshot` för att demonstrera flödet live på skärmen och verifiera skärmdumpen med `read_file`."""

    if stack == "mobile":
        return """## Stack: Mobil (Flutter / PWA)

- **Arkitektur:** Följ `flutter-apply-architecture-best-practices` med tydlig separation mellan UI, logik och datalager.
- **Statisk analys:** Kör `dart analyze` (via skill `dart-run-static-analysis`) före varje avslut och åtgärda varningar.
- **Tillgänglighet & Test:** Verifiera tillgänglighet via `flutter_a11y_agent` och kör funktionstester via `mobile-app-testing` innan överlämning.
- **Efterkontroll:** Passera `post-verify` på både mobilvy och eventuella API-kopplingar."""

    return """## Stack: Generell

- **Mål & Omfattning:** Definiera projektets kärnmål, målgrupp och leverabler tydligt i denna sektion.
- **Artefakter:** Håll kod, dokumentation och eventuella planer spårbara i projektmappen.
- **Verifieringskrav:** Testa alltid slutresultatet skarpt mot verkliga krav och passera `post-verify` (live-test, beställningskontroll, regelkontroll) innan du rapporterar klart."""


def build_agents_md(project_name: str, stack: str, juno_root: Path) -> str:
    """Render the local complement AGENTS.md for the target project."""
    memory_cli = juno_root / "tools" / "memory_cli.py"
    section = _stack_section(stack, juno_root)

    return f"""# {project_name} — Lokal projektinstruktion (`{stack}`)

> Det här är det lokala projektlagret som kompletterar de globala Juno-reglerna.
> Centrala verktyg, minnesarkiv och bakgrundsvakter ligger kvar i `{juno_root}` och kopieras inte hit.

## Centrala Juno-verktyg

- **Central rot:** `{juno_root}`
- **Minne & staging:** `python "{memory_cli}" status` / `stage`
- **Global efterkontroll:** Följ alltid `post-verify` innan uppdraget avslutas.

{section}

## Projektanteckningar

- **Projektnamn:** {project_name}
- **Vald stack:** `{stack}`
- **Regel:** Håll hemligheter (`.env`, API-nycklar, tokens) utanför versionshantering och `AGENTS.md`.
"""


def register_project(project_name: str, target_dir: Path, stack: str) -> dict[str, Any]:
    """Stage the project in central projects.json via memory_cli.py stage."""
    if not MEMORY_CLI.exists():
        return {"ok": False, "error": f"memory_cli.py not found at {MEMORY_CLI}"}

    payload = {
        "active": [
            {
                "id": _slugify(project_name),
                "name": project_name,
                "description": f"Lokalt projekt ({stack}) i {target_dir}",
                "status": "Initierat via init_project.py",
                "next_steps": [
                    f"Verifiera lokal AGENTS.md i {target_dir}",
                ],
            }
        ]
    }
    cmd = [
        sys.executable,
        str(MEMORY_CLI),
        "stage",
        "projects.json",
        "append",
        json.dumps(payload, ensure_ascii=False),
        "--user",
        "juno",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return {
            "ok": False,
            "returncode": proc.returncode,
            "stderr": proc.stderr.strip(),
        }
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        parsed = {"raw_output": proc.stdout.strip()}
    return {"ok": True, "result": parsed}


def init_project(
    target: Path,
    stack: str = "general",
    name: str | None = None,
    force: bool = False,
    register: bool = False,
) -> dict[str, Any]:
    """Create target directory if needed and install AGENTS.md and .gitignore."""
    target_dir = target.expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    project_name = name.strip() if name and name.strip() else target_dir.name
    created: list[str] = []
    skipped: list[dict[str, str]] = []

    agents_path = target_dir / "AGENTS.md"
    if agents_path.exists() and not force:
        skipped.append(
            {
                "file": "AGENTS.md",
                "reason": "Already exists (use --force to overwrite)",
            }
        )
    else:
        agents_content = build_agents_md(project_name, stack, JUNO_ROOT)
        agents_path.write_text(agents_content, encoding="utf-8")
        created.append("AGENTS.md")

    gitignore_path = target_dir / ".gitignore"
    if gitignore_path.exists():
        skipped.append(
            {
                "file": ".gitignore",
                "reason": "Already exists (preserved)",
            }
        )
    else:
        gitignore_path.write_text(GITIGNORE_CONTENT, encoding="utf-8")
        created.append(".gitignore")

    summary: dict[str, Any] = {
        "status": "ok",
        "target": str(target_dir),
        "name": project_name,
        "stack": stack,
        "created": created,
        "skipped": skipped,
    }

    if register:
        summary["register"] = register_project(project_name, target_dir, stack)

    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Installera lokal stack-specifik AGENTS.md och .gitignore i en projektmapp.",
    )
    parser.add_argument(
        "target",
        type=Path,
        help="Sökväg till projektmappen (skapas om den inte finns).",
    )
    parser.add_argument(
        "--stack",
        choices=VALID_STACKS,
        default="general",
        help="Projektets teknikstack (default: general).",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Projektnamn (default: målmappens namn).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Tillåt överskrivning av befintlig AGENTS.md.",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="Stage:a projektet som förslag i central projects.json via memory_cli.py.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    args = parse_args(argv)
    summary = init_project(
        target=args.target,
        stack=args.stack,
        name=args.name,
        force=args.force,
        register=args.register,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
