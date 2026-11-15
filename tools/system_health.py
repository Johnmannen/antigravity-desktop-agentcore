"""System health and disk check tool for C:\\juno-agy."""

from __future__ import annotations

import argparse
import ctypes
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def get_memory_info() -> dict[str, float | int]:
    """Return physical RAM usage in GB and percentage via Windows API."""
    stat = _MemoryStatusEx()
    stat.dwLength = ctypes.sizeof(stat)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    gb = 1024**3
    return {
        "ram_used_pct": stat.dwMemoryLoad,
        "ram_total_gb": round(stat.ullTotalPhys / gb, 1),
        "ram_avail_gb": round(stat.ullAvailPhys / gb, 1),
    }


def get_disk_info(drive: str) -> dict[str, str | float] | None:
    """Return disk usage in GB for a mounted drive letter, or None if unavailable."""
    path = Path(f"{drive}:\\")
    if not path.exists():
        return None
    usage = shutil.disk_usage(path)
    gb = 1024**3
    return {
        "drive": f"{drive}:\\",
        "total_gb": round(usage.total / gb, 1),
        "free_gb": round(usage.free / gb, 1),
        "used_pct": round((usage.used / usage.total) * 100, 1) if usage.total else 0.0,
    }


def get_juno_footprint() -> dict[str, int]:
    """Return file count and byte size of key Juno memory files."""
    profile = ROOT / "memory" / "profile.json"
    projects = ROOT / "memory" / "projects.json"
    audit = ROOT / "logs" / "juno_tools_audit.jsonl"
    return {
        "profile_bytes": profile.stat().st_size if profile.exists() else 0,
        "projects_bytes": projects.stat().st_size if projects.exists() else 0,
        "audit_lines": len(audit.read_text(encoding="utf-8").splitlines()) if audit.exists() else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Juno-AGY System Health Check")
    parser.add_argument("--drives", nargs="+", default=["C", "G"], help="Drive letters to check")
    args = parser.parse_args()

    disks = [info for d in args.drives if (info := get_disk_info(d)) is not None]
    report = {
        "memory": get_memory_info(),
        "disks": disks,
        "juno": get_juno_footprint(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
