"""PostToolUse verification hook for write_file / edit_file.

Checks Python syntax with py_compile whenever a .py file is created or edited.
Exits 0 silently for non-Python files or valid syntax; exits 2 with stderr on syntax error.
"""

from __future__ import annotations

import json
import py_compile
import sys
from pathlib import Path


def main() -> int:
    raw = sys.stdin.read().strip()
    if not raw:
        return 0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0

    tool_input = payload.get("tool_input") or payload.get("arguments") or {}
    path_str = tool_input.get("Path") or tool_input.get("path") or ""
    if not path_str or not path_str.lower().endswith(".py"):
        return 0

    target = Path(path_str)
    if not target.exists():
        return 0

    try:
        py_compile.compile(str(target), doraise=True)
    except py_compile.PyCompileError as exc:
        print(f"POST-VERIFY SYNTAX ERROR in {target.name}: {exc.msg}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
