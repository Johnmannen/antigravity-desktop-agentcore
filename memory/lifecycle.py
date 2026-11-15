# lifecycle.py — Livscykel-rutinen för minnesarkivet (Fas 3.5.3, Minnearkitekturen)
#
# Källa: MINNESARKIV_UTREDNING_2026-08-10 §12.2 (komponenter 5–9) + §12.6 steg 3
# Regler (hybridspecen §12.5):
#   R2 En skrivare     — rutinen skriver ALDRIG direkt: förslag går via write_gate-staging
#   R3 history.db append-only — rutinen rör inte history.db
#   R5 Allt audit-loggas
#   K6 Ingen bakgrundsloop — periodisk, på-begäran (körs manuellt eller schemalagd)
#
# Design (Adaptive Memory-koncepten, egen kod):
#   - Importance 1–5: lexikala signaler justerar (always/love/name +1, today/maybe −1)
#   - Stability: stable (år) / fluid (månader) / transient (dagar) — styr förfall
#   - Dedup: textuell likhet >= 0.95 → UPDATE-instead-of-ADD (ny blir uppdatering av befintlig)
#   - Pruning: tiered_decay — konservativ, ALDRIG radera: förfallna förslag → staging för John
#   - Stale: 90 dagar utan access → förslag till John
#   - Summarisering: kluster av liknande poster → sammanfattning (manuell trigg)
#
# Post-format i JSON-arkivet (komponent 5):
#   {"id": "…", "text": "…", "importance": 1-5, "stability": "stable|fluid|transient",
#    "created": iso, "accessed": iso, "source": "chat|a2a|kalibrering|…"}

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

MEMORY_DIR = Path(__file__).resolve().parent
PROFILE_PATH = MEMORY_DIR / "profile.json"
LOGS_DIR = MEMORY_DIR.parent / "logs"
MEMORIES_KEY = "memories"  # sektion i profile.json (Lager 2, sanning)

# ---------------------------------------------------------------- stabilitet & förfall
STABILITY_HALF_LIFE_DAYS = {
    "stable": 365,
    "fluid": 180,
    "transient": 60,
}
STALE_AFTER_DAYS = 90          # utan access → stale-förslag
IMPORTANCE_DECAY_BONUS = 30    # +1 importance → +30 dagar extra livslängd
DEDUP_TEXTUAL_THRESHOLD = 0.95  # textuell likhet (K4)
SUMMARIZE_CLUSTER_SIM = 0.70    # klusterbildning för summarisering

# ---------------------------------------------------------------- lexikala signaler (importance)
_IMPORTANCE_UP = re.compile(r"(?i)\b(always|love|hate|name|förbjuden|förbjudet|måste|kritisk|viktigast|aldrig)\b")
_IMPORTANCE_DOWN = re.compile(r"(?i)\b(today|maybe|kanske|eventuellt|tillfälligt|just nu|idag)\b")

def score_importance(text: str, base: int = 3) -> int:
    """Importance 1–5: lexikala signaler justerar bas 3."""
    score = base
    score += len(_IMPORTANCE_UP.findall(text))
    score -= len(_IMPORTANCE_DOWN.findall(text))
    return max(1, min(5, score))

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

# ---------------------------------------------------------------- hjälp
def _load_profile() -> dict:
    if PROFILE_PATH.exists():
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    return {}

def _save_profile(data: dict) -> None:
    PROFILE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def get_memories() -> list[dict]:
    return _load_profile().get(MEMORIES_KEY, [])

def _set_memories(memories: list[dict]) -> None:
    data = _load_profile()
    data[MEMORIES_KEY] = memories
    _save_profile(data)

def _audit(event: str, note: str = "", ok: bool = True) -> None:
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        line = {
            "ts": _now(), "event": event, "user": "lifecycle", "target": "profile.json",
            "ok": ok, "note": note[:200],
        }
        with (LOGS_DIR / "juno_tools_audit.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:
        pass

def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()

# ---------------------------------------------------------------- 1. normalisera & märk
def normalize_entry(text: str, *, stability: str = "fluid", source: str = "chat",
                    importance: int | None = None, created: str | None = None) -> dict:
    """Bygger en post med livscykel-metadata (komponent 5)."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise ValueError("tom text")
    if stability not in STABILITY_HALF_LIFE_DAYS:
        raise ValueError(f"ogiltig stability: {stability}")
    return {
        "id": uuid.uuid4().hex[:12],
        "text": text,
        "importance": importance if importance is not None else score_importance(text),
        "stability": stability,
        "created": created or _now(),
        "accessed": _now(),
        "source": source,
    }

# ---------------------------------------------------------------- 2. dedup (K4)
def dedup(memories: list[dict]) -> tuple[list[dict], list[dict]]:
    """Textuell dedup: likhet >= 0.95 → ny blir UPDATE av befintlig (färskare text vinner).
    Returnerar (renade minnen, uppdateringar-applicerade). Ingen ändring sker utan caller."""
    cleaned: list[dict] = []
    updates: list[dict] = []
    for m in memories:
        text = m.get("text", "").strip()
        if not text:
            continue
        match = None
        for existing in cleaned:
            if _similarity(existing.get("text", ""), text) >= DEDUP_TEXTUAL_THRESHOLD:
                match = existing
                break
        if match is not None:
            # UPDATE-instead-of-ADD: nyare text + max(importance), samla ihop access
            merged = dict(match)
            merged["text"] = text  # färskaste formuleringen
            merged["importance"] = max(match.get("importance", 3), m.get("importance", 3))
            merged["accessed"] = max(match.get("accessed", ""), m.get("accessed", ""))
            merged["source"] = m.get("source", match.get("source"))
            updates.append({"ersatt": match.get("id"), "med": merged})
            cleaned = [merged if x.get("id") == match.get("id") else x for x in cleaned]
        else:
            cleaned.append(dict(m))
    return cleaned, updates

# ---------------------------------------------------------------- 3. pruning (tiered_decay, konservativ)
def _decayed(m: dict, *, ref: datetime | None = None) -> bool:
    """tiered_decay: livslängd = halveringstid(stability) + importance-bonus. Efter det → förfall."""
    ref = ref or datetime.now(timezone.utc)
    try:
        created = datetime.fromisoformat(m["created"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
    except Exception:
        return False  # saknar metadata → rör inte (konservativ)
    half = STABILITY_HALF_LIFE_DAYS.get(m.get("stability", "fluid"), 180)
    bonus = (m.get("importance", 3) - 3) * IMPORTANCE_DECAY_BONUS
    ttl_days = half + bonus
    return (ref - created).days > ttl_days

def prune(memories: list[dict]) -> tuple[list[dict], list[dict]]:
    """Förfallna poster flyttas UT ur arkivet till ett förslag (aldrig raderat).
    Returnerar (kvarvarande, förfallna-förslag). Förslagen ska gå via write_gate-staging."""
    kept: list[dict] = []
    decayed: list[dict] = []
    for m in memories:
        if _decayed(m):
            m = dict(m)
            m["decayed_at"] = _now()
            decayed.append(m)
            _audit("prune_decay", note=f"{m.get('id')} {m.get('stability')} imp={m.get('importance')}")
        else:
            kept.append(m)
    return kept, decayed

# ---------------------------------------------------------------- 4. stale-detection (komponent 9)
def find_stale(memories: list[dict], *, days: int = STALE_AFTER_DAYS) -> list[dict]:
    """90 dagar utan access → förslag till John (loggas, raderas inte)."""
    now = datetime.now(timezone.utc)
    stale: list[dict] = []
    for m in memories:
        try:
            accessed = datetime.fromisoformat(m.get("accessed", m.get("created", "")))
            if accessed.tzinfo is None:
                accessed = accessed.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if (now - accessed).days > days:
            stale.append(dict(m))
    return stale

def touch(memories: list[dict], entry_id: str) -> list[dict]:
    """Access-registrering: uppdaterar accessed (anropas av JunoMinne-tool vid läsning)."""
    out = []
    for m in memories:
        if m.get("id") == entry_id:
            m = dict(m)
            m["accessed"] = _now()
        out.append(m)
    return out

# ---------------------------------------------------------------- 5. summarisering (komponent 8)
def cluster(memories: list[dict], *, sim: float = SUMMARIZE_CLUSTER_SIM) -> list[list[dict]]:
    """Klustrar liknande poster (greedy, icke-överlappande) för summarisering."""
    remaining = [dict(m) for m in memories]
    clusters: list[list[dict]] = []
    while remaining:
        seed = remaining.pop(0)
        group = [seed]
        rest = []
        for m in remaining:
            if _similarity(seed.get("text", ""), m.get("text", "")) >= sim:
                group.append(m)
            else:
                rest.append(m)
        remaining = rest
        clusters.append(group)
    return clusters

def summarize_clusters(memories: list[dict], *, min_group: int = 3) -> list[dict]:
    """Kluster med >= min_group poster → en sammanfattningspost (förslag till John).
    Inga poster raderas här — resultatet är ett förslag som går via grinden."""
    proposals = []
    for group in cluster(memories):
        if len(group) < min_group:
            continue
        texts = [m.get("text", "") for m in group]
        summary = " • ".join(t[:120] for t in texts[:4])
        if len(texts) > 4:
            summary += f" … (+{len(texts)-4} till)"
        proposals.append({
            "id": uuid.uuid4().hex[:12],
            "text": f"[SAMMANFATTNING av {len(group)} poster] {summary}",
            "importance": max(m.get("importance", 3) for m in group),
            "stability": "stable",
            "created": _now(), "accessed": _now(), "source": "livscykel-summarisering",
            "group_ids": [m.get("id") for m in group],
        })
    return proposals

# ---------------------------------------------------------------- CLI (på-begäran, aldrig loop)
def _cli() -> None:
    import sys
    args = sys.argv[1:]
    cmd = args[0] if args else ""

    if cmd == "status":
        mems = get_memories()
        stale = find_stale(mems)
        kept, decayed = prune(mems)
        print(f"poster: {len(mems)}  |  förfallna (skulle flyttas): {len(decayed)}  |  stale (>90d utan access): {len(stale)}")
        print(f"importance-fördelning: { {i: sum(1 for m in mems if m.get('importance')==i) for i in range(1,6)} }")
        print(f"stability-fördelning:  { {s: sum(1 for m in mems if m.get('stability')==s) for s in STABILITY_HALF_LIFE_DAYS} }")

    elif cmd == "prune":
        mems = get_memories()
        kept, decayed = prune(mems)
        if not decayed:
            print("Inga förfallna poster. Arkivet är friskt.")
            return
        _set_memories(kept)
        # förslagen läggs i pending/ via write_gate (endast en skrivare, R2)
        import write_gate as wg
        for d in decayed:
            wg.stage("profile.json", "patch", {
                "livscykel_förslag": {
                    "typ": "prune_decay", "post": d,
                    "förslag": f"Förfallen post ({d.get('stability')}, imp {d.get('importance')}) — sammanfatta eller arkivera",
                }
            })
        print(f"{len(decayed)} förfallna poster flyttade → pending/ (väntar på John).")
        for d in decayed:
            print(f"  - [{d.get('stability')} imp{d.get('importance')}] {d.get('text','')[:90]}")

    elif cmd == "stale":
        mems = get_memories()
        stale = find_stale(mems)
        if not stale:
            print("Inga stale-poster (90 dagar utan access).")
            return
        print(f"{len(stale)} stale-poster:")
        for s in stale:
            print(f"  - [{s.get('stability')} imp{s.get('importance')}] {s.get('text','')[:90]} (senast {s.get('accessed','?')[:10]})")

    elif cmd == "dedup":
        mems = get_memories()
        cleaned, updates = dedup(mems)
        if not updates:
            print("Inga dubbletter (textuell likhet >= 0.95).")
            return
        _set_memories(cleaned)
        print(f"{len(updates)} dubbletter konsoliderade (UPDATE-instead-of-ADD).")
        for u in updates[:10]:
            print(f"  - {u['ersatt']} ← {u['med']['text'][:80]}")

    elif cmd == "summarize":
        mems = get_memories()
        proposals = summarize_clusters(mems)
        if not proposals:
            print("Inga kluster med >= 3 poster. Inget att sammanfatta.")
            return
        import write_gate as wg
        for p in proposals:
            wg.stage("profile.json", "patch", {
                "livscykel_förslag": {"typ": "summarisering", "post": p}
            })
        print(f"{len(proposals)} sammanfattningsförslag → pending/ (väntar på John).")

    elif cmd == "add":
        if len(args) < 3:
            print("add <text> <stability> [source]")
            return
        entry = normalize_entry(args[1], stability=args[2], source=args[3] if len(args) > 3 else "cli")
        mems = get_memories()
        mems.append(entry)
        _set_memories(mems)
        print(f"lade till post {entry['id']} (imp {entry['importance']}, {entry['stability']})")

    elif cmd == "touch" and len(args) == 2:
        mems = get_memories()
        _set_memories(touch(mems, args[1]))
        print(f"accessed uppdaterad för {args[1]}")

    else:
        print(__doc__)

if __name__ == "__main__":
    _cli()

