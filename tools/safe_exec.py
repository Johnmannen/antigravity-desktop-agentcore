"""Global Anti-Hang & Anti-Deadlock Runtime Guard (safe_exec) for C:\\juno-agy.

Prevents silent Windows pipe deadlocks, stalled subprocesses, and hanging
network/TTS calls by enforcing:
1. Log-file / unbuffered streaming (never PIPE stderr while feeding stdin).
2. Hard wall-clock timeout and stall-detection (kills entire process tree on Windows).
3. Async retry with strict per-attempt asyncio.wait_for timeouts.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Awaitable, Callable, Sequence, TypeVar

T = TypeVar("T")


class SafeExecError(RuntimeError):
    """Base error for safe_exec failures."""


class StallTimeoutError(SafeExecError):
    """Raised when a child process produces no output/progress within stall_timeout."""


class ExecutionTimeoutError(SafeExecError):
    """Raised when a child process exceeds max wall-clock timeout."""


def kill_process_tree(pid: int) -> None:
    """Terminate a process and all its child processes cleanly (Windows-safe)."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def run_command_safe(
    cmd: Sequence[str],
    *,
    timeout: float = 600.0,
    stall_timeout: float = 90.0,
    log_file: Path | str | None = None,
    cwd: Path | str | None = None,
) -> int:
    """Run a command with unbuffered output, wall-clock timeout, and stall watchdog."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    if log_file is None:
        log_path = Path.cwd() / f"safe_exec_{os.getpid()}.log"
        cleanup_log = True
    else:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        cleanup_log = False

    start = time.monotonic()
    last_activity = start
    last_size = 0

    with open(log_path, "w", encoding="utf-8", errors="replace") as lf:
        proc = subprocess.Popen(
            list(cmd),
            stdout=lf,
            stderr=subprocess.STDOUT,
            cwd=str(cwd) if cwd else None,
            env=env,
        )
        try:
            while True:
                rc = proc.poll()
                now = time.monotonic()
                try:
                    cur_size = log_path.stat().st_size
                except OSError:
                    cur_size = last_size

                if cur_size > last_size:
                    # Stream new bytes to our stdout so parent task logs stay live
                    with open(log_path, "r", encoding="utf-8", errors="replace") as rf:
                        rf.seek(last_size)
                        chunk = rf.read()
                        if chunk:
                            sys.stdout.write(chunk)
                            sys.stdout.flush()
                    last_size = cur_size
                    last_activity = now

                if rc is not None:
                    return rc

                if now - start > timeout:
                    kill_process_tree(proc.pid)
                    raise ExecutionTimeoutError(
                        f"Command exceeded max timeout ({timeout:.0f}s): {' '.join(cmd)}"
                    )

                if now - last_activity > stall_timeout:
                    kill_process_tree(proc.pid)
                    raise StallTimeoutError(
                        f"Command stalled with zero output for {stall_timeout:.0f}s: {' '.join(cmd)}"
                    )

                time.sleep(0.5)
        finally:
            if proc.poll() is None:
                kill_process_tree(proc.pid)
            if cleanup_log and log_path.exists():
                try:
                    log_path.unlink()
                except OSError:
                    pass


async def retry_async(
    coro_factory: Callable[[int], Awaitable[T]],
    *,
    retries: int = 3,
    per_attempt_timeout: float = 30.0,
    backoff: float = 1.5,
    label: str = "task",
) -> T:
    """Execute an async operation with per-attempt timeout and exponential backoff."""
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return await asyncio.wait_for(coro_factory(attempt), timeout=per_attempt_timeout)
        except Exception as exc:
            last_err = exc
            print(f"[{label}] attempt {attempt}/{retries} failed: {exc}", flush=True)
            if attempt < retries:
                await asyncio.sleep(backoff * attempt)
    assert last_err is not None
    raise last_err


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a command with anti-hang stall watchdog.")
    parser.add_argument("--timeout", type=float, default=600.0, help="Max wall-clock seconds")
    parser.add_argument("--stall-timeout", type=float, default=90.0, help="Max seconds without output")
    parser.add_argument("--log-file", type=str, default=None, help="Optional persistent log file")
    parser.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to execute after --")
    args = parser.parse_args()

    cmd = list(args.cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        parser.error("No command provided after --")

    return run_command_safe(
        cmd,
        timeout=args.timeout,
        stall_timeout=args.stall_timeout,
        log_file=args.log_file,
    )


if __name__ == "__main__":
    raise SystemExit(main())
