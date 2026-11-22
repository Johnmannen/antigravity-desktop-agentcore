"""Interactive Desktop Screen Recorder for C:\\juno-agy.

Runs inside the user's interactive Windows session (via desktop_bridge.py) so
ffmpeg gdigrab has full desktop capture permission at native 1920x1080.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture real desktop screen video via ffmpeg gdigrab.")
    parser.add_argument("--output", required=True, help="Output MP4 file path")
    parser.add_argument("--duration", type=float, default=12.0, help="Recording duration in seconds")
    parser.add_argument("--fps", type=int, default=30, help="Framerate (default: 30)")
    parser.add_argument("--delay", type=float, default=0.0, help="Optional countdown delay before recording")
    parser.add_argument("--local", action="store_true", help="Compatibility flag from desktop_bridge")
    args = parser.parse_args()

    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = out_path.with_suffix(".ffmpeg.log")

    if args.delay > 0:
        time.sleep(args.delay)

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "gdigrab",
        "-framerate", str(args.fps),
        "-draw_mouse", "1",
        "-i", "desktop",
        "-t", f"{args.duration:.2f}",
        "-vf", "scale=1920:1080:flags=lanczos,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "16",
        "-pix_fmt", "yuv420p",
        "-color_range", "tv",
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-movflags", "+faststart",
        "-map_metadata", "-1",
        str(out_path),
    ]

    with log_path.open("w", encoding="utf-8") as logf:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=logf,
            timeout=max(30.0, args.duration + 30.0),
        )

    if proc.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        err_tail = log_path.read_text(encoding="utf-8", errors="replace")[-500:] if log_path.exists() else ""
        print(json.dumps({"status": "error", "returncode": proc.returncode, "error": err_tail}))
        return 1

    print(json.dumps({
        "status": "ok",
        "output": str(out_path),
        "bytes": out_path.stat().st_size,
        "duration": args.duration,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
