"""Safe, modular Windows 10 diagnostics and safety gatekeeper for C:\\juno-agy.

Subcommands:
    diagnose      Read-only system diagnostics via PowerShell (with timeouts).
    check-risk    Classify a proposed command/action as GREEN/YELLOW/RED/BLOCKED.
    open-setting  Validate and open a ms-settings: URI (supports --dry-run).
    backup        Export registry key and attempt a System Restore Point.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT / "logs" / "win10_backups"
AUDIT_LOG = ROOT / "logs" / "juno_tools_audit.jsonl"

PS_TIMEOUT_SEC = 15

DIAGNOSE_SECTIONS = (
    "system",
    "events",
    "services",
    "startup",
    "drivers",
    "network",
    "disk",
    "security",
)

# ---------------------------------------------------------------------------
# Audit & PowerShell helpers
# ---------------------------------------------------------------------------


def _audit(action: str, detail: dict[str, Any]) -> None:
    """Append a lightweight audit entry to logs/juno_tools_audit.jsonl."""
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": "win10_doctor",
            "action": action,
            "detail": detail,
        }
        with AUDIT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _run_powershell(script: str, timeout: int = PS_TIMEOUT_SEC) -> tuple[bool, Any, str]:
    """Execute a read-only PowerShell snippet and parse JSON output safely."""
    wrapped = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "$ErrorActionPreference = 'Stop'; "
        f"{script}"
    )
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        wrapped,
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, None, f"PowerShell timeout after {timeout}s"
    except OSError as exc:
        return False, None, f"Failed to launch PowerShell: {exc}"

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    if proc.returncode != 0:
        return False, None, stderr or f"PowerShell exited with code {proc.returncode}"

    if not stdout:
        return True, None, ""

    try:
        return True, json.loads(stdout), ""
    except json.JSONDecodeError as exc:
        return False, stdout, f"JSON parse error: {exc}"


def _as_list(data: Any) -> list[Any]:
    """Normalize PowerShell ConvertTo-Json single-item/null output into a list."""
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return [data]


# ---------------------------------------------------------------------------
# Diagnose sections (strictly read-only)
# ---------------------------------------------------------------------------


def _diag_system() -> dict[str, Any]:
    ps = r"""
    $os = Get-CimInstance Win32_OperatingSystem
    $uptime = (Get-Date) - $os.LastBootUpTime
    $cbs = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'
    $wu = Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
    $sm = Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Name PendingFileRenameOperations -ErrorAction SilentlyContinue
    [PSCustomObject]@{
        os_name = $os.Caption
        version = $os.Version
        build = $os.BuildNumber
        architecture = $os.OSArchitecture
        last_boot = $os.LastBootUpTime.ToString('o')
        uptime_hours = [math]::Round($uptime.TotalHours, 2)
        ram_total_gb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
        ram_free_gb = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
        pending_reboot = ($cbs -or $wu -or ($null -ne $sm))
        pending_reboot_sources = [PSCustomObject]@{
            cbs = $cbs
            windows_update = $wu
            pending_file_rename = ($null -ne $sm)
        }
    } | ConvertTo-Json -Depth 4
    """
    ok, data, err = _run_powershell(ps)
    return data if ok and isinstance(data, dict) else {"error": err or "Unexpected output", "raw": data}


def _diag_events() -> dict[str, Any]:
    ps = r"""
    $events = Get-WinEvent -FilterHashtable @{LogName=@('System','Application'); Level=@(1,2)} -MaxEvents 10 -ErrorAction SilentlyContinue |
        ForEach-Object {
            $msg = if ($_.Message) { ($_.Message -replace '\s+', ' ').Trim() } else { '' }
            if ($msg.Length -gt 280) { $msg = $msg.Substring(0, 280) + '...' }
            [PSCustomObject]@{
                time = if ($_.TimeCreated) { $_.TimeCreated.ToString('o') } else { $null }
                log = $_.LogName
                provider = $_.ProviderName
                id = $_.Id
                level = $_.LevelDisplayName
                message = $msg
            }
        }
    @($events) | ConvertTo-Json -Depth 3
    """
    ok, data, err = _run_powershell(ps)
    if not ok:
        return {"error": err}
    items = _as_list(data)
    return {"count": len(items), "items": items}


def _diag_services() -> dict[str, Any]:
    ps = r"""
    $coreNames = @('wuauserv', 'bits', 'WinDefend', 'Dhcp', 'Dnscache', 'Audiosrv', 'Spooler', 'WSearch')
    $core = foreach ($n in $coreNames) {
        $svc = Get-Service -Name $n -ErrorAction SilentlyContinue
        if ($svc) {
            [PSCustomObject]@{
                name = $svc.Name
                display_name = $svc.DisplayName
                status = $svc.Status.ToString()
                start_type = $svc.StartType.ToString()
            }
        } else {
            [PSCustomObject]@{
                name = $n
                display_name = $null
                status = 'NotFound'
                start_type = $null
            }
        }
    }
    $stoppedAuto = Get-CimInstance Win32_Service -Filter "StartMode='Auto' AND State!='Running'" -ErrorAction SilentlyContinue |
        Select-Object -First 10 Name, DisplayName, State, StartMode |
        ForEach-Object {
            [PSCustomObject]@{
                name = $_.Name
                display_name = $_.DisplayName
                state = $_.State
                start_mode = $_.StartMode
            }
        }
    [PSCustomObject]@{
        core_services = @($core)
        stopped_automatic_top10 = @($stoppedAuto)
    } | ConvertTo-Json -Depth 4
    """
    ok, data, err = _run_powershell(ps)
    return data if ok and isinstance(data, dict) else {"error": err or "Unexpected output"}


def _diag_startup() -> dict[str, Any]:
    ps = r"""
    $items = Get-CimInstance Win32_StartupCommand -ErrorAction SilentlyContinue |
        ForEach-Object {
            [PSCustomObject]@{
                name = $_.Name
                command = $_.Command
                location = $_.Location
                user = $_.User
            }
        }
    @($items) | ConvertTo-Json -Depth 3
    """
    ok, data, err = _run_powershell(ps)
    if not ok:
        return {"error": err}
    items = _as_list(data)
    return {"count": len(items), "items": items}


def _diag_drivers() -> dict[str, Any]:
    ps = r"""
    $broken = Get-CimInstance Win32_PnPEntity -Filter "ConfigManagerErrorCode != 0" -ErrorAction SilentlyContinue |
        ForEach-Object {
            [PSCustomObject]@{
                name = $_.Name
                device_id = $_.DeviceID
                error_code = $_.ConfigManagerErrorCode
                status = $_.Status
            }
        }
    @($broken) | ConvertTo-Json -Depth 3
    """
    ok, data, err = _run_powershell(ps)
    if not ok:
        return {"error": err}
    items = _as_list(data)
    return {"broken_count": len(items), "items": items}


def _diag_network() -> dict[str, Any]:
    ps = r"""
    $adapters = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Up' } |
        ForEach-Object {
            $idx = $_.ifIndex
            $ips = @(Get-NetIPAddress -InterfaceIndex $idx -AddressFamily IPv4 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty IPAddress)
            $dns = @(Get-DnsClientServerAddress -InterfaceIndex $idx -AddressFamily IPv4 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty ServerAddresses)
            [PSCustomObject]@{
                name = $_.Name
                description = $_.InterfaceDescription
                mac = $_.MacAddress
                link_speed = $_.LinkSpeed
                ipv4 = $ips
                dns_servers = $dns
            }
        }
    @($adapters) | ConvertTo-Json -Depth 4
    """
    ok, data, err = _run_powershell(ps)
    if not ok:
        return {"error": err}
    items = _as_list(data)
    return {"active_adapters": len(items), "adapters": items}


def _get_temp_folder_stats() -> dict[str, Any]:
    """Calculate user %TEMP% size safely in Python without failing on locked files."""
    temp_dir = Path(os.environ.get("TEMP") or os.environ.get("TMP") or "")
    if not temp_dir or not temp_dir.exists():
        return {"path": str(temp_dir), "size_mb": 0.0, "file_count": 0, "error": "TEMP not found"}

    total_bytes = 0
    file_count = 0
    stack = [temp_dir]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total_bytes += entry.stat(follow_symlinks=False).st_size
                            file_count += 1
                    except OSError:
                        continue
        except OSError:
            continue

    return {
        "path": str(temp_dir),
        "size_mb": round(total_bytes / (1024**2), 2),
        "file_count": file_count,
    }


def _diag_disk() -> dict[str, Any]:
    ps = r"""
    $disks = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" -ErrorAction SilentlyContinue |
        ForEach-Object {
            $totalGb = if ($_.Size) { [math]::Round($_.Size / 1GB, 2) } else { 0 }
            $freeGb = if ($_.FreeSpace) { [math]::Round($_.FreeSpace / 1GB, 2) } else { 0 }
            $freePct = if ($_.Size -gt 0) { [math]::Round(($_.FreeSpace / $_.Size) * 100, 1) } else { 0 }
            [PSCustomObject]@{
                drive = $_.DeviceID
                volume_name = $_.VolumeName
                total_gb = $totalGb
                free_gb = $freeGb
                free_pct = $freePct
            }
        }
    @($disks) | ConvertTo-Json -Depth 3
    """
    ok, data, err = _run_powershell(ps)
    disks = _as_list(data) if ok else []
    result: dict[str, Any] = {
        "fixed_disks": disks,
        "user_temp": _get_temp_folder_stats(),
    }
    if not ok:
        result["disk_query_error"] = err
    return result


def _diag_security() -> dict[str, Any]:
    ps = r"""
    $defender = $null
    $defError = $null
    try {
        $mp = Get-MpComputerStatus -ErrorAction Stop
        $defender = [PSCustomObject]@{
            antivirus_enabled = $mp.AntivirusEnabled
            realtime_protection_enabled = $mp.RealTimeProtectionEnabled
            antivirus_signature_last_updated = if ($mp.AntivirusSignatureLastUpdated) { $mp.AntivirusSignatureLastUpdated.ToString('o') } else { $null }
            quick_scan_age_days = $mp.QuickScanAge
        }
    } catch {
        $defError = $_.Exception.Message
    }

    $fw = @(Get-NetFirewallProfile -ErrorAction SilentlyContinue | ForEach-Object {
        [PSCustomObject]@{
            name = $_.Name
            enabled = [bool]$_.Enabled
            default_inbound = $_.DefaultInboundAction.ToString()
            default_outbound = $_.DefaultOutboundAction.ToString()
        }
    })

    [PSCustomObject]@{
        defender = $defender
        defender_error = $defError
        firewall_profiles = $fw
    } | ConvertTo-Json -Depth 4
    """
    ok, data, err = _run_powershell(ps)
    return data if ok and isinstance(data, dict) else {"error": err or "Unexpected output"}


SECTION_HANDLERS = {
    "system": _diag_system,
    "events": _diag_events,
    "services": _diag_services,
    "startup": _diag_startup,
    "drivers": _diag_drivers,
    "network": _diag_network,
    "disk": _diag_disk,
    "security": _diag_security,
}


def run_diagnose(section: str) -> dict[str, Any]:
    """Run one or all read-only diagnostic sections."""
    targets = list(DIAGNOSE_SECTIONS) if section == "all" else [section]
    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "section": section,
        "data": {},
    }
    for name in targets:
        report["data"][name] = SECTION_HANDLERS[name]()
    _audit("diagnose", {"section": section})
    return report


# ---------------------------------------------------------------------------
# Risk classification
# ---------------------------------------------------------------------------

_BLOCKED_PATTERNS: list[tuple[str, str]] = [
    (
        r"(?i)Set-MpPreference\b.*\s-Disable(RealtimeMonitoring|BehaviorMonitoring|IOAVProtection|ScriptScanning)\b",
        "Försök att stänga av Windows Defender-skydd är blockerat.",
    ),
    (
        r"(?i)\b(Stop-Service|sc(\.exe)?\s+(stop|config|delete))\b.*\bWinDefend\b",
        "Försök att stoppa eller inaktivera Windows Defender-tjänsten är blockerat.",
    ),
    (
        r"(?i)(Set-NetFirewallProfile\b.*-Enabled\s+(False|\$false|0)|netsh\s+advfirewall\s+set\s+.*\bstate\s+off\b)",
        "Försök att stänga av Windows-brandväggen är blockerat.",
    ),
    (
        r"(?i)(^|[;&|\s])format(\.com|\.exe)?\s+[a-z]:|\bFormat-Volume\b",
        "Formatering av disk/volym är blockerad.",
    ),
    (
        r"(?i)\bbcdedit(\.exe)?\s+/delete\b",
        "Radering av boot-poster med bcdedit är blockerad.",
    ),
    (
        r"(?i)(\b(Invoke-Expression|iex)\b.*https?://|https?://.*(\|\s*iex\b|\|\s*Invoke-Expression\b)|\birm\b.*\|\s*(iex|Invoke-Expression)\b)",
        "Fjärrhämtad kod direkt till Invoke-Expression/iex är blockerad.",
    ),
    (
        r"(?i)\breg(\.exe)?\s+delete\s+['\"]?HKLM\\(SYSTEM|SAM|SECURITY)\b",
        "Radering i kritisk HKLM-systemgren i registret är blockerad.",
    ),
    (
        r"(?i)\b(Remove-Item|rm|rd|rmdir|del)\b.*(['\"]?[A-Za-z]:\\(Windows|Program Files|Users)?['\"]?(\s|$)|/\s*s\s+/\s*q\s+[A-Za-z]:\\)",
        "Rekursiv radering mot systemkatalog eller enhetsrot är blockerad.",
    ),
]

_RED_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)\bsfc(\.exe)?\b", "System File Checker (sfc) kräver admin och modifierar systemfiler."),
    (r"(?i)\bdism(\.exe)?\b", "DISM modifierar Windows-avbildning/komponenter och kräver admin."),
    (r"(?i)\breg(\.exe)?\s+(add|delete|import|restore)\b", "Registerändring med reg.exe kräver backup och godkännande."),
    (r"(?i)\b(Set-ItemProperty|New-ItemProperty|Remove-ItemProperty)\b.*HKLM:", "Ändring i HKLM-registret kräver admin och backup."),
    (r"(?i)\b(Set-Service|Stop-Service|Restart-Service|Start-Service)\b", "Tjänsteändring påverkar systemets drift."),
    (r"(?i)\bsc(\.exe)?\s+(config|stop|start|delete)\b", "Tjänsteändring via sc.exe kräver godkännande."),
    (r"(?i)\bDisable-[A-Za-z0-9]+\b", "Inaktivering av systemkomponent/funktion kräver godkännande."),
    (r"(?i)\bCheckpoint-Computer\b", "Skapande av återställningspunkt kräver adminrättigheter."),
    (r"(?i)\bchkdsk(\.exe)?\b", "Diskkontroll/reparation kan kräva omstart och admin."),
    (r"(?i)\bnetsh\b", "Nätverkskonfiguration via netsh påverkar systemet."),
    (r"(?i)\bRemove-Item\b", "Filradering utanför temp kräver uttryckligt godkännande."),
]

_YELLOW_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)Remove-Item\b.*(%TEMP%|\\Temp\\|\$env:TEMP)", "Rensning av temporära filer i användarens Temp-mapp."),
    (r"(?i)\bms-settings:", "Öppning av Windows-inställningssida."),
    (r"(?i)\bcleanmgr(\.exe)?\b", "Diskrensning på användarnivå."),
    (r"(?i)HKCU\\", "Ändring/hantering i aktuell användares register (HKCU)."),
]

_GREEN_PATTERNS: list[tuple[str, str]] = [
    (
        r"(?i)^\s*(Get-|Select-|Where-|Test-|Format-Table|Format-List|ConvertTo-Json|systeminfo|ipconfig|tasklist|whoami|hostname|nslookup|ping|tracert|netstat|reg\s+query|dir\b|ls\b)",
        "Ren läs- eller diagnostikåtgärd utan systemändring.",
    ),
    (
        r"(?i)win10_doctor\.py\s+diagnose\b",
        "Read-only diagnostik via win10_doctor.",
    ),
]


def classify_risk(action_text: str) -> dict[str, Any]:
    """Classify a command or proposed action into GREEN, YELLOW, RED, or BLOCKED."""
    text = action_text.strip()
    if not text:
        return {
            "risk": "YELLOW",
            "reason": "Tom åtgärdstext — kan inte verifieras som säker läsning.",
            "requires_backup": False,
            "requires_user_ok": True,
        }

    for pattern, reason in _BLOCKED_PATTERNS:
        if re.search(pattern, text):
            return {
                "risk": "BLOCKED",
                "reason": reason,
                "requires_backup": True,
                "requires_user_ok": True,
            }

    # Check YELLOW temp-cleanup before generic RED Remove-Item
    for pattern, reason in _YELLOW_PATTERNS:
        if re.search(pattern, text):
            return {
                "risk": "YELLOW",
                "reason": reason,
                "requires_backup": False,
                "requires_user_ok": True,
            }

    for pattern, reason in _RED_PATTERNS:
        if re.search(pattern, text):
            return {
                "risk": "RED",
                "reason": reason,
                "requires_backup": True,
                "requires_user_ok": True,
            }

    for pattern, reason in _GREEN_PATTERNS:
        if re.search(pattern, text):
            return {
                "risk": "GREEN",
                "reason": reason,
                "requires_backup": False,
                "requires_user_ok": False,
            }

    return {
        "risk": "YELLOW",
        "reason": "Oklassificerad åtgärd — kräver manuell kontroll innan körning.",
        "requires_backup": False,
        "requires_user_ok": True,
    }


# ---------------------------------------------------------------------------
# Open setting
# ---------------------------------------------------------------------------

_SETTING_URI_RE = re.compile(r"^ms-settings:[a-zA-Z0-9:_-]+$")


def open_setting(uri: str, dry_run: bool = False) -> tuple[int, dict[str, Any]]:
    """Validate a ms-settings: URI and optionally launch it via os.startfile."""
    if not _SETTING_URI_RE.match(uri):
        return 1, {
            "status": "error",
            "uri": uri,
            "error": "Ogiltig URI. Måste börja med 'ms-settings:' och bara innehålla [a-zA-Z0-9:_-].",
        }

    if dry_run:
        _audit("open-setting", {"uri": uri, "dry_run": True})
        return 0, {"status": "ok", "uri": uri, "dry_run": True}

    try:
        os.startfile(uri)  # type: ignore[attr-defined]
    except OSError as exc:
        return 1, {"status": "error", "uri": uri, "error": str(exc)}

    _audit("open-setting", {"uri": uri, "dry_run": False})
    return 0, {"status": "ok", "uri": uri, "dry_run": False}


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def _sanitize_filename(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", text).strip("_") or "reg_backup"


def run_backup(reg_key: str) -> tuple[int, dict[str, Any]]:
    """Export a registry key to logs/win10_backups and attempt Checkpoint-Computer."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_key = _sanitize_filename(reg_key)
    reg_file = BACKUP_DIR / f"{safe_key}_{stamp}.reg"

    reg_result: dict[str, Any] = {"reg_key": reg_key, "file": str(reg_file), "ok": False}
    try:
        proc = subprocess.run(
            ["reg.exe", "export", reg_key, str(reg_file), "/y"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PS_TIMEOUT_SEC,
        )
        reg_result["ok"] = proc.returncode == 0
        if proc.returncode != 0:
            reg_result["error"] = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
    except subprocess.TimeoutExpired:
        reg_result["error"] = f"reg export timeout after {PS_TIMEOUT_SEC}s"
    except OSError as exc:
        reg_result["error"] = str(exc)

    ps_checkpoint = (
        "Checkpoint-Computer -Description 'JunoWin10Doctor' "
        "-RestorePointType 'MODIFY_SETTINGS' -ErrorAction Stop"
    )
    cp_ok, _, cp_err = _run_powershell(ps_checkpoint, timeout=PS_TIMEOUT_SEC)
    cp_result: dict[str, Any] = {"ok": cp_ok, "admin_required": False}
    if not cp_ok:
        lower_err = cp_err.lower()
        needs_admin = any(
            kw in lower_err
            for kw in ("access is denied", "access denied", "åtkomst nekad", "administrator", "elevated", "privilege")
        )
        cp_result["admin_required"] = needs_admin
        cp_result["error"] = cp_err
        if needs_admin:
            cp_result["hint"] = "Kör PowerShell som administratör för att skapa System Restore Point."

    _audit("backup", {"reg_ok": reg_result["ok"], "checkpoint_ok": cp_ok})
    overall_code = 0 if reg_result["ok"] else 1
    return overall_code, {
        "status": "ok" if reg_result["ok"] else "partial_or_error",
        "registry_export": reg_result,
        "restore_point": cp_result,
    }


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="win10_doctor",
        description="Säkert Windows 10-diagnostik- och säkerhetsverktyg för Juno-AGY",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_diag = sub.add_parser("diagnose", help="Kör read-only Windows 10-diagnostik")
    p_diag.add_argument(
        "--section",
        choices=("all", *DIAGNOSE_SECTIONS),
        default="all",
        help="Vilken diagnostiksektion som ska köras (default: all)",
    )

    p_risk = sub.add_parser("check-risk", help="Klassificera risknivå för en åtgärd/kommando")
    p_risk.add_argument("action_text", help="Kommando eller åtgärdsbeskrivning att bedöma")

    p_open = sub.add_parser("open-setting", help="Öppna en validerad ms-settings:-URI")
    p_open.add_argument("uri", help="Windows-inställnings-URI, t.ex. ms-settings:windowsupdate")
    p_open.add_argument("--dry-run", action="store_true", help="Validera utan att öppna fönster")

    p_bak = sub.add_parser("backup", help="Exportera registernyckel och försök skapa återställningspunkt")
    p_bak.add_argument(
        "--reg-key",
        default=r"HKCU\Software",
        help=r"Registernyckel att exportera (default: HKCU\Software)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "diagnose":
        result = run_diagnose(args.section)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "check-risk":
        result = classify_risk(args.action_text)
        _audit("check-risk", {"risk": result["risk"]})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "open-setting":
        code, result = open_setting(args.uri, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code

    if args.command == "backup":
        code, result = run_backup(args.reg_key)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
