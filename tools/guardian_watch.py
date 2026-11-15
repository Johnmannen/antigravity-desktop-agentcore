"""Lightweight autonomous system sensor for C:\\juno-agy.

Runs with zero AI cost, checks thresholds from guardian_config.json,
and writes alerts to logs/guardian_alert.json only when attention is needed.
Designed to be consumed by both Antigravity (Juno) and future standalone Python agents.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "tools"
MEMORY_DIR = ROOT / "memory"
LOGS_DIR = ROOT / "logs"

sys.path.insert(0, str(TOOLS_DIR))
sys.path.insert(0, str(MEMORY_DIR))

import inbox_organizer  # noqa: E402
import system_health  # noqa: E402
import write_gate  # noqa: E402

DEFAULT_CONFIG = {
    "disk_min_free_gb": 20.0,
    "ram_max_pct": 88,
    "downloads_max_files": 100,
    "large_file_mb": 500,
    "pending_max_count": 1,
    "drives": ["C", "G"],
}


def load_config() -> dict:
    """Load threshold config from tools/guardian_config.json with safe defaults."""
    cfg_path = TOOLS_DIR / "guardian_config.json"
    if cfg_path.exists():
        loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
        return {**DEFAULT_CONFIG, **loaded}
    return dict(DEFAULT_CONFIG)


def evaluate_system(cfg: dict) -> dict:
    """Run all lightweight checks and return structured status + alerts."""
    alerts: list[dict[str, str | float | int]] = []

    mem = system_health.get_memory_info()
    if mem["ram_used_pct"] >= cfg["ram_max_pct"]:
        alerts.append({
            "type": "ram_high",
            "message": f"RAM-användning är {mem['ram_used_pct']}% (gräns {cfg['ram_max_pct']}%).",
            "value": mem["ram_used_pct"],
        })

    disks = []
    for drive in cfg["drives"]:
        info = system_health.get_disk_info(drive)
        if info is None:
            continue
        disks.append(info)
        if info["free_gb"] < cfg["disk_min_free_gb"]:
            alerts.append({
                "type": "disk_low",
                "message": f"Enhet {info['drive']} har bara {info['free_gb']} GB ledigt (gräns {cfg['disk_min_free_gb']} GB).",
                "drive": info["drive"],
                "value": info["free_gb"],
            })

    downloads = inbox_organizer.scan_folder(Path.home() / "Downloads", large_mb=cfg["large_file_mb"])
    if "error" not in downloads:
        if downloads["total_files"] > cfg["downloads_max_files"]:
            alerts.append({
                "type": "downloads_crowded",
                "message": f"Downloads har {downloads['total_files']} filer (gräns {cfg['downloads_max_files']}).",
                "value": downloads["total_files"],
            })
        if downloads["large_files"]:
            names = ", ".join(f["name"] for f in downloads["large_files"][:3])
            alerts.append({
                "type": "downloads_large_files",
                "message": f"Stora filer över {cfg['large_file_mb']} MB i Downloads: {names}.",
                "count": len(downloads["large_files"]),
            })

    pending = write_gate.list_pending()
    if len(pending) >= cfg["pending_max_count"]:
        alerts.append({
            "type": "memory_pending",
            "message": f"Det finns {len(pending)} väntande minnesförslag i memory/pending/.",
            "count": len(pending),
        })

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "alert" if alerts else "ok",
        "alerts": alerts,
        "summary": {
            "ram_used_pct": mem["ram_used_pct"],
            "disks_free_gb": {d["drive"]: d["free_gb"] for d in disks},
            "downloads_files": downloads.get("total_files", 0),
            "pending_updates": len(pending),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous lightweight system sensor")
    parser.add_argument("--quiet", action="store_true", help="Suppress stdout when status is ok")
    args = parser.parse_args()

    cfg = load_config()
    result = evaluate_system(cfg)

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    alert_file = LOGS_DIR / "guardian_alert.json"
    alert_file.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if result["alerts"] or not args.quiet:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
