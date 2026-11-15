"""Local Interactive Desktop Bridge for C:\\juno-agy.

Listens strictly on 127.0.0.1:8765 inside John's interactive Windows session
so Antigravity tools (chrome_agent.py, desktop_operator.py) can open visible
windows on the real desktop and interact with native Windows applications.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "tools"
PYTHON_EXE = ROOT / ".venv" / "Scripts" / "python.exe"

ALLOWED_TOOLS = {
    "chrome_agent": TOOLS_DIR / "chrome_agent.py",
    "desktop_operator": TOOLS_DIR / "desktop_operator.py",
}


class BridgeHandler(BaseHTTPRequestHandler):
    """Handle /health and /run requests from local Juno tools."""

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "session": "interactive_desktop"})
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/run":
            self._send_json(404, {"error": "Not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        req = json.loads(self.rfile.read(length).decode("utf-8"))
        tool = req.get("tool", "")
        args = [str(a) for a in req.get("args", [])]
        keep_open = bool(req.get("keep_open", False))

        if tool not in ALLOWED_TOOLS:
            self._send_json(400, {"error": f"Otillåtet verktyg: {tool}"})
            return

        script = ALLOWED_TOOLS[tool]
        cmd = [str(PYTHON_EXE), str(script), *args, "--local"]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        if keep_open and tool == "chrome_agent":
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
                result_file = Path(tf.name)
            result_file.unlink(missing_ok=True)
            cmd.extend(["--keep-open", "--result-file", str(result_file)])
            proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stderr=subprocess.PIPE, text=True, encoding="utf-8", creationflags=no_win)
            deadline = time.time() + 75.0
            while time.time() < deadline:
                if result_file.exists() and result_file.stat().st_size > 0:
                    data = json.loads(result_file.read_text(encoding="utf-8"))
                    result_file.unlink(missing_ok=True)
                    self._send_json(200, data)
                    return
                if proc.poll() is not None:
                    err = proc.stderr.read().strip() if proc.stderr else ""
                    self._send_json(500, {"error": err or f"Chrome-agent avslutades med kod {proc.returncode}"})
                    return
                time.sleep(0.25)
            self._send_json(500, {"error": "Timeout i väntan på Chrome-resultat"})
            return

        proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, creationflags=no_win)
        if proc.returncode != 0:
            self._send_json(500, {"error": proc.stderr.strip() or f"Exit {proc.returncode}"})
            return
        try:
            self._send_json(200, json.loads(proc.stdout))
        except json.JSONDecodeError:
            self._send_json(200, {"status": "ok", "output": proc.stdout.strip()})

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return


def _watchdog_loop(interval_sec: int = 900) -> None:
    """Run ops_watchdog silently in the background every 15 minutes."""
    no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    watchdog_script = TOOLS_DIR / "ops_watchdog.py"
    while True:
        try:
            if watchdog_script.exists():
                subprocess.run(
                    [str(PYTHON_EXE), str(watchdog_script), "scan", "--quiet", "--notify"],
                    cwd=str(ROOT),
                    capture_output=True,
                    timeout=30,
                    creationflags=no_win,
                )
        except Exception:
            pass
        time.sleep(interval_sec)


def main() -> None:
    threading.Thread(target=_watchdog_loop, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", 18765), BridgeHandler)
    print("Juno Desktop Bridge listening on http://127.0.0.1:18765", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
