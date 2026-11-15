"""Shared client helper to route GUI commands through the local desktop bridge."""

from __future__ import annotations

import httpx

BRIDGE_URL = "http://127.0.0.1:18765"


def is_bridge_running() -> bool:
    """Return True if the interactive desktop bridge is reachable on localhost."""
    try:
        resp = httpx.get(f"{BRIDGE_URL}/health", timeout=1.5)
        return resp.status_code == 200
    except Exception:
        return False


def run_via_bridge(tool: str, args: list[str], *, keep_open: bool = False, timeout: float = 90.0) -> dict:
    """Forward a tool invocation to the interactive desktop bridge."""
    resp = httpx.post(
        f"{BRIDGE_URL}/run",
        json={"tool": tool, "args": args, "keep_open": keep_open},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()
