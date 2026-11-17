# write_gate.py — Skrivgrinden för minnesarkivet (Fas 3.5.2, Minnearkitekturen)
#
# Källa: MINNESARKIV_UTREDNING_2026-08-10 §12 (komponenter 10–13) + JUNO_MINNE_STRATEGI_V1
# Regler (hybridspecen §12.5):
#   R1 Git först             — permanenta ändringar skrivs till JSON (git)
#   R2 En skrivare           — inget skriver direkt till JSON utan staging-grinden
#   R5 Allt audit-loggas     — varje arkiv-operation loggas till logs/juno_tools_audit.jsonl
#
# Flöde:  skriv(...) → pending/ (JSON, id) → approve(id)/reject(id) av John → JSON uppdateras → audit

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------- sökvägar
MEMORY_DIR = Path(__file__).resolve().parent
PENDING_DIR = MEMORY_DIR / "pending"
LOGS_DIR = MEMORY_DIR.parent / "logs"

# Godkända målfilnamn i arkivet (whitelist — inget godtyckligt skrivande)
ALLOWED_TARGETS = {
    "profile.json": MEMORY_DIR / "profile.json",
    "projects.json": MEMORY_DIR / "projects.json",
    "juno_minne.json": MEMORY_DIR / "juno_minne.json",
}
# Teckentak per fil (komponent 12) — vid fullt returneras FILE_FULL så agenten konsoliderar
FILE_LIMITS = {
    "profile.json": 8192,
    "projects.json": 16384,
    "juno_minne.json": 32768,
}
MAX_PENDING_AGE_DAYS = 30  # gamla pending-förslag rensas av livscykel-rutinen

# ---------------------------------------------------------------- sekretfilter (komponent 10)
_SECRET_PATTERNS = [
    re.compile(r"\b(sk|pk|rk|ghp|gho|glpat|xoxb|xoxp)-[A-Za-z0-9_\-]{15,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}\b"),
    re.compile(r"\bGOCSPX-[0-9A-Za-z\-_]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token)\s*[=:]\s*['\"]?[^\s'\"]{8,}\b"),
]
_INJECTION_PATTERNS = [
    re.compile(r"(?i)\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|above|prior|earlier)?\s*(instructions|prompts?|system prompt|rules)\b"),
    re.compile(r"(?i)\byou are now\b.{0,60}\b(dan|jailbreak|unfiltered|no restrictions)\b"),
    re.compile(r"(?i)\b(system prompt|jailbreak|injection)\b.{0,30}\b(reveal|show|print|output|leak)\b"),
]
_INVISIBLE_UNICODE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\u00ad]")

def secret_scan(text: str) -> list[str]:
    hits = []
    for rx in _SECRET_PATTERNS:
        if rx.search(text):
            hits.append(rx.pattern[:40])
    for rx in _INJECTION_PATTERNS:
        if rx.search(text):
            hits.append(rx.pattern[:40])
    if _INVISIBLE_UNICODE.search(text):
        hits.append("osynlig-unicode")
    return hits

# ---------------------------------------------------------------- audit (R5, Regel 43)
def _audit(event, *, user, target, pending_id=None, ok=True, note="") -> None:
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        line = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": event, "user": user, "target": target,
            "pending_id": pending_id, "ok": ok, "note": note,
        }
        with (LOGS_DIR / "juno_tools_audit.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:
        pass  # audit får aldrig krascha operationen

# ---------------------------------------------------------------- staging (komponent 11)
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _pending_path(pending_id: str) -> Path:
    return PENDING_DIR / f"{pending_id}.json"

def stage(target: str, operation: str, payload: dict, *, user: str = "system") -> dict:
    """Staging: skrivningen hamnar i pending/ — tillämpar INTE på arkivet.
    operation: 'write' (ersätt målfil) | 'patch' (djupt slå ihop) | 'append' (lista/sträng)"""
    if target not in ALLOWED_TARGETS:
        return {"error": f"Målfil ej tillåten: {target}", "code": "VALIDATION_FAILED"}
    text = json.dumps(payload, ensure_ascii=False)
    hits = secret_scan(text)
    if hits:
        _audit("stage_blocked_secret", user=user, target=target, ok=False, note=";".join(hits[:3]))
        return {"error": f"Blockerad av sekretfilter ({hits[0]})", "code": "SECRET_FILTERED"}

    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    pid = uuid.uuid4().hex[:12]
    item = {
        "id": pid, "target": target, "operation": operation, "payload": payload,
        "status": "pending", "created": _now(), "user": user,
    }
    _pending_path(pid).write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    _audit("stage", user=user, target=target, pending_id=pid, ok=True, note=operation)
    return {"status": "pending", "pending_id": pid, "target": target,
            "meddelande": f"Väntar på Johns godkännande (approve {pid})"}

def list_pending() -> list[dict]:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for f in sorted(PENDING_DIR.glob("*.json")):
        try:
            items.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return items

def approve(pending_id: str, *, user: str = "john") -> dict:
    """John ✅ → tillämpar staging på arkivet (R1: JSON först). Enda 'direktskrivaren'."""
    p = _pending_path(pending_id)
    if not p.exists():
        return {"error": f"pending {pending_id} finns inte", "code": "NOT_FOUND"}
    item = json.loads(p.read_text(encoding="utf-8"))
    if item["status"] != "pending":
        return {"error": f"redan {item['status']}", "code": "STATE_CONFLICT"}

    target = item["target"]
    path = ALLOWED_TARGETS[target]
    current = {}
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))

    try:
        if item["operation"] == "write":
            new = item["payload"]
        elif item["operation"] == "patch":
            new = _deep_merge(current, item["payload"])
        elif item["operation"] == "append":
            new = _deep_merge(current, item["payload"], append_lists=True)
        else:
            return {"error": f"okänd operation {item['operation']}", "code": "VALIDATION_FAILED"}
    except Exception as exc:
        return {"error": f"tillämpning misslyckades: {exc}", "code": "APPLY_FAILED"}

    size = len(json.dumps(new, ensure_ascii=False))
    limit = FILE_LIMITS.get(target)
    if limit and size > limit:
        _audit("approve_blocked_full", user=user, target=target, pending_id=pending_id, ok=False, note=f"{size}>{limit}")
        return {"error": f"FILE_FULL: {target} skulle bli {size} tecken (tak {limit}). Konsolidera först.", "code": "FILE_FULL"}

    path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    item["status"] = "approved"
    item["approved_at"] = _now()
    item["approved_by"] = user
    p.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    _audit("approve", user=user, target=target, pending_id=pending_id, ok=True)
    return {"status": "approved", "pending_id": pending_id, "target": target,
            "size": size, "meddelande": "JSON-arkivet uppdaterat (git-commit görs enligt commit-regeln)"}

def reject(pending_id: str, *, user: str = "john", reason: str = "") -> dict:
    p = _pending_path(pending_id)
    if not p.exists():
        return {"error": f"pending {pending_id} finns inte", "code": "NOT_FOUND"}
    item = json.loads(p.read_text(encoding="utf-8"))
    item["status"] = "rejected"
    item["rejected_at"] = _now()
    item["rejected_by"] = user
    item["reason"] = reason
    p.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    _audit("reject", user=user, target=item["target"], pending_id=pending_id, ok=False, note=reason)
    return {"status": "rejected", "pending_id": pending_id}

def clear_old_pending(*, days: int = MAX_PENDING_AGE_DAYS, user: str = "system") -> int:
    """Rensar pending-förslag äldre än `days` dagar (livscykel-rutinens uppgift)."""
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    n = 0
    for it in list_pending():
        try:
            created = datetime.fromisoformat(it["created"]).timestamp()
        except Exception:
            created = 0
        if created < cutoff:
            p = _pending_path(it["id"])
            if p.exists():
                p.unlink()
                _audit("pending_cleared", user=user, target=it["target"], pending_id=it["id"], ok=True, note="ålder")
                n += 1
    return n

# ------------------------------------------------- substring-replace/remove (komponent 13)
def _read_target(target: str) -> dict:
    if target not in ALLOWED_TARGETS:
        raise ValueError(f"ej tillåten: {target}")
    path = ALLOWED_TARGETS[target]
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

def _write_target(target: str, data: dict, *, user: str) -> dict:
    path = ALLOWED_TARGETS[target]
    size = len(json.dumps(data, ensure_ascii=False))
    limit = FILE_LIMITS.get(target)
    if limit and size > limit:
        return {"error": f"FILE_FULL: {target} skulle bli {size} tecken (tak {limit})", "code": "FILE_FULL"}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _audit("substring_apply", user=user, target=target, ok=True, note=f"{size}B")
    return {"status": "ok", "target": target, "size": size}

def _find_key_path(obj, needle: str, prefix: str = "") -> list[str]:
    """Hittar (djup) sökväg till ett strängvärde som matchar needle exakt. Returnerar alla träffar."""
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else k
            found += _find_key_path(v, needle, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += _find_key_path(v, needle, f"{prefix}[{i}]")
    elif isinstance(obj, str) and obj == needle:
        found = [prefix]
    return found

def update_substring(target: str, old_value: str, new_value: str, *, user: str = "system") -> dict:
    """Precis uppdatering: ersätter ett unikt strängvärde på djupet. Kräver unikhet."""
    data = _read_target(target)
    paths = _find_key_path(data, old_value)
    if not paths:
        return {"error": f"'{old_value[:30]}' hittades inte i {target}", "code": "NOT_FOUND"}
    if len(paths) > 1:
        return {"error": f"'{old_value[:30]}' finns på {len(paths)} ställen — ange unikt värde", "code": "NOT_UNIQUE"}
    parts = paths[0].split(".")
    ref = data
    for part in parts[:-1]:
        m = part
        if "[" in m:  # lista-index
            name, idx = m.split("[")
            ref = ref[name][int(idx.rstrip("]"))]
        else:
            ref = ref[part]
    last = parts[-1]
    if "[" in last:
        name, idx = last.split("[")
        ref[name][int(idx.rstrip("]"))] = new_value
    else:
        ref[last] = new_value
    return _write_target(target, data, user=user)

def remove_substring(target: str, old_value: str, *, user: str = "system") -> dict:
    """Precis borttagning av ett unikt strängvärde."""
    data = _read_target(target)
    paths = _find_key_path(data, old_value)
    if not paths:
        return {"error": f"'{old_value[:30]}' hittades inte i {target}", "code": "NOT_FOUND"}
    if len(paths) > 1:
        return {"error": f"'{old_value[:30]}' finns på {len(paths)} ställen — ange unikt värde", "code": "NOT_UNIQUE"}
    parts = paths[0].split(".")
    ref = data
    for part in parts[:-1]:
        if "[" in part:
            name, idx = part.split("[")
            ref = ref[name][int(idx.rstrip("]"))]
        else:
            ref = ref[part]
    last = parts[-1]
    if "[" in last:
        name, idx = last.split("[")
        del ref[name][int(idx.rstrip("]"))]
    else:
        del ref[last]
    return _write_target(target, data, user=user)

# ---------------------------------------------------------------- hjälp
def _deep_merge(base: dict, patch: dict, append_lists: bool = False) -> dict:
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v, append_lists)
        elif isinstance(v, list) and append_lists and isinstance(out.get(k), list):
            out[k] = out[k] + v
        else:
            out[k] = v
    return out

# ---------------------------------------------------------------- CLI (för John / verktyg)
def _cli() -> None:
    import sys
    args = sys.argv[1:]
    if not args:
        print("Användning: write_gate.py stage|approve|reject|list|update|remove [args]")
        return
    cmd = args[0]
    if cmd == "list":
        for it in list_pending():
            print(f"{it['id']}  {it['target']}  {it['operation']}  {it['created']}  status={it['status']}")
    elif cmd == "stage" and len(args) >= 4:
        print(json.dumps(stage(args[1], args[2], json.loads(args[3])), ensure_ascii=False))
    elif cmd == "approve" and len(args) >= 2:
        print(json.dumps(approve(args[1]), ensure_ascii=False))
    elif cmd == "reject" and len(args) >= 2:
        reason = args[2] if len(args) > 2 else ""
        print(json.dumps(reject(args[1], reason=reason), ensure_ascii=False))
    elif cmd == "update" and len(args) == 4:
        print(json.dumps(update_substring(args[1], args[2], args[3]), ensure_ascii=False))
    elif cmd == "remove" and len(args) == 3:
        print(json.dumps(remove_substring(args[1], args[2]), ensure_ascii=False))
    else:
        print("Argumentfel. Se toppen av filen.")

if __name__ == "__main__":
    _cli()

