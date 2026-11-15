"""Read-only Disk Librarian for C:\\juno-agy.

Inventories folders, builds a searchable catalog, detects exact duplicates
via size + SHA-256, and proposes safe cleanup/archiving plans without modifying files.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import os
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = ROOT / "logs" / "disk_catalog.json"
INSTALLER_EXTS = {".exe", ".msi", ".msix"}
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz"}
IGNORE_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".chrome-agent-profile"}


def _sha256(path: Path, chunk_size: int = 65536) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def _safe_stat(path: Path):
    try:
        return path.stat()
    except OSError:
        return None


def _walk_filtered(target: Path, max_depth: int | None = None, include_hidden: bool = False):
    """Walk target directory while pruning noise folders and respecting max_depth."""
    base_depth = len(target.parts)
    for root, dirs, files in os.walk(target):
        if not include_hidden:
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        root_path = Path(root)
        depth = len(root_path.parts) - base_depth
        if max_depth is not None and depth >= max_depth:
            dirs[:] = []
        yield root_path, dirs, files


def cmd_catalog(args: argparse.Namespace) -> dict:
    """Scan target folder and save a structured inventory catalog."""
    target = Path(args.path)
    if not target.exists() or not target.is_dir():
        return {"error": f"Mappen finns inte: {target}"}

    total_files = 0
    total_bytes = 0
    ext_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "bytes": 0})
    dir_sizes: dict[str, int] = defaultdict(int)
    top_heap: list[tuple[int, str]] = []

    for root_path, _dirs, files in _walk_filtered(target, args.max_depth, args.include_hidden):
        for fname in files:
            fpath = root_path / fname
            st = _safe_stat(fpath)
            if st is None:
                continue
            total_files += 1
            total_bytes += st.st_size
            ext = fpath.suffix.lower() or "(ingen)"
            ext_stats[ext]["count"] += 1
            ext_stats[ext]["bytes"] += st.st_size
            dir_sizes[str(root_path)] += st.st_size
            entry = (st.st_size, str(fpath))
            if len(top_heap) < 15:
                heapq.heappush(top_heap, entry)
            elif st.st_size > top_heap[0][0]:
                heapq.heapreplace(top_heap, entry)

    largest_files = [
        {"path": p, "size_mb": round(sz / (1024**2), 2)}
        for sz, p in sorted(top_heap, reverse=True)
    ]
    top_dirs = sorted(dir_sizes.items(), key=lambda x: x[1], reverse=True)[:10]
    top_exts = sorted(ext_stats.items(), key=lambda x: x[1]["bytes"], reverse=True)[:10]

    report = {
        "target": str(target),
        "total_files": total_files,
        "total_gb": round(total_bytes / (1024**3), 3),
        "top_folders": [{"path": p, "size_mb": round(b / (1024**2), 2)} for p, b in top_dirs],
        "top_extensions": {k: {"count": v["count"], "size_mb": round(v["bytes"] / (1024**2), 2)} for k, v in top_exts},
        "largest_files": largest_files,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["catalog_saved_to"] = str(out_path)
    return report


def cmd_duplicates(args: argparse.Namespace) -> dict:
    """Find exact duplicate files by grouping on size first, then SHA-256."""
    target = Path(args.path)
    if not target.exists() or not target.is_dir():
        return {"error": f"Mappen finns inte: {target}"}

    min_bytes = args.min_size_kb * 1024
    by_size: dict[int, list[Path]] = defaultdict(list)

    for root_path, _dirs, files in _walk_filtered(target, include_hidden=args.include_hidden):
        for fname in files:
            fpath = root_path / fname
            st = _safe_stat(fpath)
            if st and st.st_size >= min_bytes:
                by_size[st.st_size].append(fpath)

    dup_groups: list[dict] = []
    reclaimable_bytes = 0

    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        by_hash: dict[str, list[str]] = defaultdict(list)
        for p in paths:
            try:
                by_hash[_sha256(p)].append(str(p))
            except OSError:
                continue
        for digest, group in by_hash.items():
            if len(group) >= 2:
                reclaimable_bytes += size * (len(group) - 1)
                dup_groups.append({
                    "sha256_short": digest[:12],
                    "size_mb": round(size / (1024**2), 2),
                    "files": group,
                })

    dup_groups.sort(key=lambda g: g["size_mb"] * (len(g["files"]) - 1), reverse=True)
    return {
        "target": str(target),
        "duplicate_groups_count": len(dup_groups),
        "reclaimable_mb": round(reclaimable_bytes / (1024**2), 2),
        "duplicate_groups": dup_groups[:20],
    }


def cmd_cleanup_plan(args: argparse.Namespace) -> dict:
    """Generate a non-destructive cleanup proposal (old installers, archives, empty dirs)."""
    target = Path(args.path)
    if not target.exists() or not target.is_dir():
        return {"error": f"Mappen finns inte: {target}"}

    cutoff = time.time() - (args.days_old * 86400)
    old_installers: list[dict] = []
    old_archives: list[dict] = []
    empty_dirs: list[str] = []

    for root_path, dirs, files in _walk_filtered(target, include_hidden=args.include_hidden):
        if not dirs and not files and root_path != target:
            empty_dirs.append(str(root_path))
        for fname in files:
            fpath = root_path / fname
            st = _safe_stat(fpath)
            if not st or st.st_mtime >= cutoff:
                continue
            ext = fpath.suffix.lower()
            entry = {"path": str(fpath), "size_mb": round(st.st_size / (1024**2), 2)}
            if ext in INSTALLER_EXTS:
                old_installers.append(entry)
            elif ext in ARCHIVE_EXTS:
                old_archives.append(entry)

    return {
        "target": str(target),
        "days_old_threshold": args.days_old,
        "old_installers": old_installers[:20],
        "old_archives": old_archives[:20],
        "empty_dirs": empty_dirs[:30],
        "note": "Strikt läsläge: inga filer har flyttats eller raderats.",
    }


def cmd_search(args: argparse.Namespace) -> dict:
    """Search for files matching a case-insensitive substring and/or extension."""
    target = Path(args.path)
    if not target.exists() or not target.is_dir():
        return {"error": f"Mappen finns inte: {target}"}

    needle = (args.pattern or "").lower()
    ext_filter = args.ext.lower() if args.ext else None
    if ext_filter and not ext_filter.startswith("."):
        ext_filter = f".{ext_filter}"

    matches: list[dict] = []
    for root_path, _dirs, files in _walk_filtered(target, include_hidden=args.include_hidden):
        for fname in files:
            if needle and needle not in fname.lower():
                continue
            fpath = root_path / fname
            if ext_filter and fpath.suffix.lower() != ext_filter:
                continue
            st = _safe_stat(fpath)
            matches.append({
                "path": str(fpath),
                "size_kb": round(st.st_size / 1024, 1) if st else 0,
            })
            if len(matches) >= args.limit:
                return {"target": str(target), "matches_count": len(matches), "truncated": True, "matches": matches}

    return {"target": str(target), "matches_count": len(matches), "truncated": False, "matches": matches}


def main() -> None:
    parser = argparse.ArgumentParser(description="Juno-AGY Disk Librarian")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cat = sub.add_parser("catalog", help="Inventory folder and save searchable JSON catalog")
    p_cat.add_argument("path")
    p_cat.add_argument("--max-depth", type=int, default=None)
    p_cat.add_argument("--out", default=str(DEFAULT_CATALOG))
    p_cat.add_argument("--include-hidden", action="store_true")

    p_dup = sub.add_parser("duplicates", help="Find exact duplicate files")
    p_dup.add_argument("path")
    p_dup.add_argument("--min-size-kb", type=int, default=100)
    p_dup.add_argument("--include-hidden", action="store_true")

    p_plan = sub.add_parser("cleanup-plan", help="Propose safe cleanup candidates (read-only)")
    p_plan.add_argument("path")
    p_plan.add_argument("--days-old", type=int, default=90)
    p_plan.add_argument("--include-hidden", action="store_true")

    p_search = sub.add_parser("search", help="Find files by name substring and/or extension")
    p_search.add_argument("path")
    p_search.add_argument("pattern", nargs="?", default="")
    p_search.add_argument("--ext", default=None)
    p_search.add_argument("--limit", type=int, default=30)
    p_search.add_argument("--include-hidden", action="store_true")

    args = parser.parse_args()
    handlers = {
        "catalog": cmd_catalog,
        "duplicates": cmd_duplicates,
        "cleanup-plan": cmd_cleanup_plan,
        "search": cmd_search,
    }
    res = handlers[args.cmd](args)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
