"""Read-only folder analyzer and sorting proposal generator for C:\\juno-agy."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

CATEGORIES: dict[str, set[str]] = {
    "Dokument": {".pdf", ".doc", ".docx", ".txt", ".md", ".xlsx", ".csv", ".pptx"},
    "Bilder": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"},
    "Arkiv": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Installers": {".exe", ".msi", ".msix"},
    "Media": {".mp3", ".wav", ".mp4", ".mkv", ".mov"},
    "Kod": {".py", ".js", ".ts", ".json", ".yaml", ".yml", ".ps1", ".cmd"},
}


def categorize_extension(ext: str) -> str:
    """Map a file extension to a human-readable category."""
    ext_lower = ext.lower()
    for category, extensions in CATEGORIES.items():
        if ext_lower in extensions:
            return category
    return "Övrigt"


def scan_folder(target: Path, large_mb: int = 100) -> dict:
    """Analyze top-level files in target folder without modifying anything."""
    if not target.exists() or not target.is_dir():
        return {"error": f"Mappen finns inte: {target}"}

    counts: dict[str, int] = defaultdict(int)
    sizes_mb: dict[str, float] = defaultdict(float)
    large_files: list[dict[str, str | float]] = []
    total_files = 0
    total_dirs = 0

    for item in target.iterdir():
        if item.is_dir():
            total_dirs += 1
            continue
        if item.is_file():
            total_files += 1
            size_mb = item.stat().st_size / (1024 * 1024)
            cat = categorize_extension(item.suffix)
            counts[cat] += 1
            sizes_mb[cat] = round(sizes_mb[cat] + size_mb, 2)
            if size_mb >= large_mb:
                large_files.append({"name": item.name, "size_mb": round(size_mb, 1), "category": cat})

    large_files.sort(key=lambda x: x["size_mb"], reverse=True)
    return {
        "folder": str(target),
        "total_files": total_files,
        "total_subdirs": total_dirs,
        "by_category": {k: {"count": counts[k], "size_mb": sizes_mb[k]} for k in sorted(counts)},
        "large_files_over_mb": large_mb,
        "large_files": large_files[:10],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only folder organizer report")
    parser.add_argument(
        "path",
        nargs="?",
        default=str(Path.home() / "Downloads"),
        help="Folder to analyze (defaults to user Downloads)",
    )
    parser.add_argument("--large-mb", type=int, default=100, help="Threshold in MB for large files")
    args = parser.parse_args()

    result = scan_folder(Path(args.path), large_mb=args.large_mb)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
