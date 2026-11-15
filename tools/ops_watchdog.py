"""Lokal Drift-, Process- & Portvakt (ops-watchdog) for C:\\juno-agy.

Reads RAM/CPU usage, grouped top memory consumers, listening TCP ports,
and user autostart entries using psutil + winreg (zero AI cost).
Compares against a baseline, updates logs/guardian_alert.json, and can
show a discreet Windows notification on alert.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import winreg
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "logs"
TOOLS_DIR = ROOT / "tools"
BASELINE_FILE = LOGS_DIR / "ops_baseline.json"
ALERT_FILE = LOGS_DIR / "guardian_alert.json"
CONFIG_FILE = TOOLS_DIR / "guardian_config.json"


def _load_thresholds() -> dict:
    defaults = {"ram_max_pct": 88, "cpu_max_pct": 90}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            defaults.update({k: data[k] for k in defaults if k in data})
        except Exception:
            pass
    return defaults


def get_grouped_processes(limit: int = 8) -> list[dict]:
    """Group running processes by name and return top RAM consumers."""
    grouped: dict[str, dict] = defaultdict(lambda: {"count": 0, "rss_bytes": 0})
    for proc in psutil.process_iter(["name", "memory_info"]):
        try:
            name = proc.info["name"] or "unknown"
            mem = proc.info["memory_info"]
            if not mem:
                continue
            grouped[name]["count"] += 1
            grouped[name]["rss_bytes"] += mem.rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    ranked = sorted(grouped.items(), key=lambda x: x[1]["rss_bytes"], reverse=True)[:limit]
    return [
        {"name": name, "count": info["count"], "ram_mb": round(info["rss_bytes"] / (1024**2), 1)}
        for name, info in ranked
    ]


def get_listening_ports() -> list[dict]:
    """Return unique listening TCP ports with owning process name."""
    pid_names: dict[int, str] = {}
    seen: set[tuple[int, str]] = set()
    ports: list[dict] = []
    for conn in psutil.net_connections(kind="tcp"):
        if conn.status != psutil.CONN_LISTEN or not conn.laddr:
            continue
        port = conn.laddr.port
        pid = conn.pid or 0
        if pid not in pid_names:
            try:
                pid_names[pid] = psutil.Process(pid).name() if pid else "system"
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pid_names[pid] = "unknown"
        pname = pid_names[pid]
        if (port, pname) not in seen:
            seen.add((port, pname))
            ports.append({"port": port, "process": pname, "pid": pid, "ip": conn.laddr.ip})
    ports.sort(key=lambda x: x["port"])
    return ports


def get_autostart_entries() -> list[dict]:
    """Read HKCU Run registry keys and user Startup folder items."""
    entries: list[dict] = []
    run_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_path) as key:
            idx = 0
            while True:
                try:
                    name, val, _ = winreg.EnumValue(key, idx)
                    entries.append({"source": "HKCU_Run", "name": name, "command": str(val)})
                    idx += 1
                except OSError:
                    break
    except OSError:
        pass

    startup_dir = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    if startup_dir.exists():
        for item in startup_dir.iterdir():
            if item.name.lower() != "desktop.ini":
                entries.append({"source": "Startup_Folder", "name": item.name, "command": str(item)})
    return entries


def _send_windows_toast(title: str, message: str) -> None:
    """Show a discreet Windows balloon notification without opening a console window."""
    safe_title = title.replace("'", " ")
    safe_msg = message.replace("'", " ")[:220]
    ps_script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$n = New-Object System.Windows.Forms.NotifyIcon; "
        "$n.Icon = [System.Drawing.SystemIcons]::Warning; "
        "$n.Visible = $true; "
        f"$n.ShowBalloonTip(6000, '{safe_title}', '{safe_msg}', [System.Windows.Forms.ToolTipIcon]::Warning); "
        "Start-Sleep -Seconds 7; $n.Dispose()"
    )
    no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(["powershell", "-NoProfile", "-Command", ps_script], creationflags=no_win)


def _merge_alerts_into_guardian(ops_alerts: list[dict], summary: dict) -> None:
    """Merge ops-watchdog alerts into logs/guardian_alert.json without clobbering other alerts."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    existing: dict = {"alerts": [], "summary": {}}
    if ALERT_FILE.exists():
        try:
            existing = json.loads(ALERT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    kept = [a for a in existing.get("alerts", []) if not str(a.get("type", "")).startswith("ops_")]
    merged_alerts = kept + ops_alerts
    merged_summary = {**existing.get("summary", {}), "ops_watchdog": summary}
    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "alert" if merged_alerts else "ok",
        "alerts": merged_alerts,
        "summary": merged_summary,
    }
    ALERT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_scan(*, update_baseline: bool = False, notify: bool = False) -> dict:
    """Collect system metrics, compare with baseline, and update guardian_alert.json."""
    thresholds = _load_thresholds()
    vm = psutil.virtual_memory()
    cpu_pct = psutil.cpu_percent(interval=0.4)
    top_procs = get_grouped_processes(8)
    ports = get_listening_ports()
    autostart = get_autostart_entries()

    current_ports = {f"{p['port']}:{p['process']}" for p in ports if p["port"] < 49152}
    current_auto = {f"{a['source']}:{a['name']}" for a in autostart}

    if update_baseline or not BASELINE_FILE.exists():
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        BASELINE_FILE.write_text(
            json.dumps({"ports": sorted(current_ports), "autostart": sorted(current_auto)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        base_ports, base_auto = current_ports, current_auto
    else:
        base = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
        base_ports = set(base.get("ports", []))
        base_auto = set(base.get("autostart", []))

    alerts: list[dict] = []
    if vm.percent >= thresholds["ram_max_pct"]:
        top_str = ", ".join(f"{p['name']} ({p['ram_mb']} MB)" for p in top_procs[:3])
        alerts.append({
            "type": "ops_ram_high",
            "message": f"RAM-användning är {vm.percent}% (gräns {thresholds['ram_max_pct']}%). Tyngst: {top_str}.",
            "value": vm.percent,
        })
    if cpu_pct >= thresholds["cpu_max_pct"]:
        alerts.append({
            "type": "ops_cpu_high",
            "message": f"CPU-belastning är {cpu_pct}% (gräns {thresholds['cpu_max_pct']}%).",
            "value": cpu_pct,
        })

    new_ports = sorted(current_ports - base_ports)
    if new_ports:
        alerts.append({
            "type": "ops_new_ports",
            "message": f"Nya lyssnande portar upptäckta: {', '.join(new_ports[:5])}.",
            "ports": new_ports,
        })

    new_auto = sorted(current_auto - base_auto)
    if new_auto:
        alerts.append({
            "type": "ops_new_autostart",
            "message": f"Nya autostart-poster upptäckta: {', '.join(new_auto[:5])}.",
            "entries": new_auto,
        })

    # Detect potentially stalled/zombie heavy tools (ffmpeg/playwright/python > 30 min uptime)
    stalled_procs: list[str] = []
    now_ts = datetime.now(timezone.utc).timestamp()
    for proc in psutil.process_iter(["pid", "name", "create_time", "cmdline"]):
        try:
            pname = (proc.info["name"] or "").lower()
            if pname not in ("ffmpeg.exe", "ffprobe.exe"):
                continue
            age_min = (now_ts - float(proc.info["create_time"] or now_ts)) / 60.0
            if age_min >= 20.0:
                stalled_procs.append(f"{pname} (PID {proc.info['pid']}, {age_min:.0f}m)")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if stalled_procs:
        alerts.append({
            "type": "ops_stalled_media_proc",
            "message": f"Långkörande/eventuellt hängd mediaprocess: {', '.join(stalled_procs[:3])}.",
            "processes": stalled_procs,
        })

    summary = {
        "ram_used_pct": vm.percent,
        "ram_avail_gb": round(vm.available / (1024**3), 2),
        "cpu_pct": cpu_pct,
        "listening_ports_count": len(ports),
        "autostart_count": len(autostart),
    }
    _merge_alerts_into_guardian(alerts, summary)

    if notify and alerts:
        _send_windows_toast("Juno Driftvakt", alerts[0]["message"])

    return {
        "status": "alert" if alerts else "ok",
        "alerts": alerts,
        "summary": summary,
        "top_ram_processes": top_procs,
        "listening_ports": ports,
        "autostart": autostart,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Juno-AGY Ops Watchdog (Process, Port & Autostart)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="Run watchdog scan and update guardian_alert.json")
    p_scan.add_argument("--baseline", action="store_true", help="Save current ports/autostart as baseline")
    p_scan.add_argument("--notify", action="store_true", help="Show Windows toast if alerts exist")
    p_scan.add_argument("--quiet", action="store_true", help="Suppress stdout when status is ok")

    sub.add_parser("baseline", help="Update approved baseline for ports and autostart")

    args = parser.parse_args()
    if args.cmd == "baseline":
        res = run_scan(update_baseline=True, notify=False)
        print(json.dumps({"status": "baseline_updated", "summary": res["summary"]}, ensure_ascii=False, indent=2))
        return

    res = run_scan(update_baseline=args.baseline, notify=args.notify)
    if res["alerts"] or not args.quiet:
        print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
