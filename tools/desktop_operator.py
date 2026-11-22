"""Windows Desktop & Application operator using pywinauto (UIA) for C:\\juno-agy."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from pywinauto import Desktop
from pywinauto.application import Application

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import bridge_client  # noqa: E402


def cmd_windows(_args: argparse.Namespace) -> dict:
    """List visible top-level desktop windows with title and handle."""
    desktop = Desktop(backend="uia")
    items = []
    for win in desktop.windows():
        try:
            title = (win.window_text() or "").strip()
            if not title:
                continue
            items.append({
                "title": title[:120],
                "class_name": win.class_name(),
                "handle": win.handle,
            })
        except Exception:
            continue
    return {"status": "ok", "count": len(items), "windows": items}


def cmd_focus(args: argparse.Namespace) -> dict:
    """Bring a window matching title regex to the foreground."""
    desktop = Desktop(backend="uia")
    win = desktop.window(title_re=args.title_re, found_index=0)
    win.set_focus()
    return {"status": "ok", "focused": win.window_text()}


def cmd_launch(args: argparse.Namespace) -> dict:
    """Launch a Windows application or .lnk shortcut and return status/PID."""
    if args.command.lower().endswith(".lnk") or Path(args.command).suffix.lower() in (".url",):
        os.startfile(args.command)
        time.sleep(args.wait)
        return {"status": "ok", "command": args.command, "pid": None}
    app = Application(backend="uia").start(args.command)
    time.sleep(args.wait)
    return {"status": "ok", "command": args.command, "pid": app.process}


def cmd_type_into(args: argparse.Namespace) -> dict:
    """Focus a matching window, optionally click (x,y), and send keys reliably (works on Electron/Antigravity)."""
    from pywinauto import keyboard, mouse

    desktop = Desktop(backend="uia")
    win = desktop.window(title_re=args.title_re, found_index=0)
    win.set_focus()
    time.sleep(0.25)
    if getattr(args, "click_xy", ""):
        cx, cy = [int(v) for v in args.click_xy.split(",")]
        mouse.click(coords=(cx, cy))
        time.sleep(0.25)
    keyboard.send_keys(args.text, with_spaces=True, with_newlines=True, pause=0.015)
    return {"status": "ok", "window": win.window_text(), "typed_chars": len(args.text)}


def cmd_choreograph(args: argparse.Namespace) -> dict:
    """Execute a smooth sequence of real mouse moves, clicks, wheel scrolls, typing, and pauses."""
    from pywinauto import keyboard, mouse

    steps = json.loads(args.steps_json)
    if args.title_re:
        desktop = Desktop(backend="uia")
        win = desktop.window(title_re=args.title_re, found_index=0)
        win.set_focus()
        time.sleep(0.25)

    cur_x, cur_y = 960, 540
    for step in steps:
        action = step.get("action")
        if action == "sleep":
            time.sleep(float(step.get("sec", 0.5)))
        elif action == "move":
            tx, ty = int(step["x"]), int(step["y"])
            n = max(8, int(step.get("steps", 18)))
            dur = float(step.get("dur", 0.45))
            for i in range(1, n + 1):
                nx = int(cur_x + (tx - cur_x) * (i / n))
                ny = int(cur_y + (ty - cur_y) * (i / n))
                mouse.move(coords=(nx, ny))
                time.sleep(dur / n)
            cur_x, cur_y = tx, ty
        elif action == "click":
            tx, ty = int(step["x"]), int(step["y"])
            mouse.click(coords=(tx, ty))
            cur_x, cur_y = tx, ty
        elif action == "scroll":
            tx, ty = int(step.get("x", cur_x)), int(step.get("y", cur_y))
            wheel = int(step.get("wheel", -4))
            mouse.scroll(coords=(tx, ty), wheel_dist=wheel)
        elif action == "type":
            txt = str(step["text"])
            pause = float(step.get("pause", 0.04))
            keyboard.send_keys(txt, with_spaces=True, with_newlines=True, pause=pause)
    return {"status": "ok", "steps_run": len(steps)}


def cmd_inspect(args: argparse.Namespace) -> dict:
    """List interactive UIA controls (buttons, edits, menu items) inside a window."""
    desktop = Desktop(backend="uia")
    win = desktop.window(title_re=args.title_re, found_index=0)
    win.set_focus()
    controls = []
    for ctrl in win.descendants():
        try:
            ctype = ctrl.friendly_class_name()
            name = (ctrl.window_text() or "").strip()
            if not name and ctype not in ("Edit", "Document"):
                continue
            if ctype in ("Button", "Edit", "Document", "MenuItem", "TabItem", "CheckBox", "Link"):
                rect = ctrl.rectangle()
                if rect.width() <= 0 or rect.height() <= 0:
                    continue
                controls.append({
                    "type": ctype,
                    "name": name[:80],
                    "center": [int((rect.left + rect.right) / 2), int((rect.top + rect.bottom) / 2)],
                })
        except Exception:
            continue
        if len(controls) >= args.limit:
            break
    return {"status": "ok", "window": win.window_text(), "count": len(controls), "controls": controls}


def cmd_click(args: argparse.Namespace) -> dict:
    """Focus a window and click the first matching UIA control by name regex."""
    desktop = Desktop(backend="uia")
    win = desktop.window(title_re=args.title_re, found_index=0)
    win.set_focus()
    pattern = re.compile(args.control_re)
    for ctrl in win.descendants():
        try:
            name = (ctrl.window_text() or "").strip()
            if name and pattern.search(name):
                rect = ctrl.rectangle()
                if rect.width() <= 0 or rect.height() <= 0:
                    continue
                ctrl.click_input()
                return {"status": "ok", "window": win.window_text(), "clicked": name}
        except Exception:
            continue
    raise RuntimeError(f"Hittade ingen kontroll som matchar: {args.control_re}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Juno-AGY Windows Desktop Operator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_win = sub.add_parser("windows", help="List visible top-level Windows")
    p_win.add_argument("--local", action="store_true")

    p_focus = sub.add_parser("focus", help="Focus a window by title regex")
    p_focus.add_argument("title_re")
    p_focus.add_argument("--local", action="store_true")

    p_launch = sub.add_parser("launch", help="Launch a Windows application")
    p_launch.add_argument("command")
    p_launch.add_argument("--wait", type=float, default=1.0)
    p_launch.add_argument("--local", action="store_true")

    p_type = sub.add_parser("type-into", help="Focus a window and type text")
    p_type.add_argument("title_re")
    p_type.add_argument("text")
    p_type.add_argument("--click-xy", default="", help="Optional x,y screen coordinates to click before typing")
    p_type.add_argument("--local", action="store_true")

    p_insp = sub.add_parser("inspect", help="List interactive controls inside a window")
    p_insp.add_argument("title_re")
    p_insp.add_argument("--limit", type=int, default=40)
    p_insp.add_argument("--local", action="store_true")

    p_clk = sub.add_parser("click", help="Focus a window and click a control by name regex")
    p_clk.add_argument("title_re")
    p_clk.add_argument("control_re")
    p_clk.add_argument("--local", action="store_true")

    p_cho = sub.add_parser("choreograph", help="Run smooth live mouse/keyboard sequence")
    p_cho.add_argument("title_re")
    p_cho.add_argument("steps_json")
    p_cho.add_argument("--local", action="store_true")

    args = parser.parse_args()
    if not args.local and bridge_client.is_bridge_running():
        forward = [args.cmd]
        if args.cmd == "focus":
            forward.append(args.title_re)
        elif args.cmd == "launch":
            forward.extend([args.command, "--wait", str(args.wait)])
        elif args.cmd == "type-into":
            forward.extend([args.title_re, args.text])
            if args.click_xy:
                forward.extend(["--click-xy", args.click_xy])
        elif args.cmd == "inspect":
            forward.extend([args.title_re, "--limit", str(args.limit)])
        elif args.cmd == "click":
            forward.extend([args.title_re, args.control_re])
        elif args.cmd == "choreograph":
            forward.extend([args.title_re, args.steps_json])
        print(json.dumps(bridge_client.run_via_bridge("desktop_operator", forward), ensure_ascii=False, indent=2))
        return

    res = {
        "windows": cmd_windows,
        "focus": cmd_focus,
        "launch": cmd_launch,
        "type-into": cmd_type_into,
        "inspect": cmd_inspect,
        "click": cmd_click,
        "choreograph": cmd_choreograph,
    }[args.cmd](args)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
