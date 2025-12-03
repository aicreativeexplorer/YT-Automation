# generate_video.py
"""
Dummy video generator for YT-Automation.

- Creates a vertical 720x1280 mp4 using ffmpeg
- Solid dark background
- Shows:
    - "TinyShort AI" at top
    - prompt text in the middle
- Prints logs + final JSON: {"output": "<path>"}
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def slugify(text: str, max_len: int = 40) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if not text:
        text = "video"
    return text[:max_len] or "video"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=str, default="tiny glowing fox")
    parser.add_argument("--duration", type=int, default=10)
    parser.add_argument("--outdir", type=str, default="work")
    parser.add_argument("--seed_url", type=str, default=None)
    args = parser.parse_args()

    prompt = args.prompt or "tiny glowing fox"
    duration = max(1, min(int(args.duration), 30))  # clamp 1–30s
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    base = slugify(prompt)
    ts = int(time.time())
    outfile = outdir / f"{base}-{ts}.mp4"

    safe_prompt = prompt.replace("'", "").replace("\n", " ")[:80]

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", "color=size=720x1280:rate=24:color=0x050816",
        "-t", str(duration),
        "-vf",
        (
            "drawtext=text='TinyShort AI':fontsize=26:fontcolor=0x38bdf8:"
            "x=20:y=40,"
            f"drawtext=text='{safe_prompt}':fontsize=24:fontcolor=white:"
            "x=(w-text_w)/2:y=(h-text_h)/2"
        ),
        str(outfile),
    ]

    print("[generate_video] running ffmpeg...", file=sys.stderr)
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if proc.returncode != 0:
            print("[generate_video] ffmpeg failed", file=sys.stderr)
            print(proc.stderr[:500], file=sys.stderr)
            print(json.dumps({"error": "ffmpeg_failed"}))
            sys.exit(1)
    except Exception as e:
        print("[generate_video] exception:", repr(e), file=sys.stderr)
        print(json.dumps({"error": "exception"}))
        sys.exit(1)

    # Last line: JSON with output path
    print(json.dumps({"output": str(outfile)}))


if __name__ == "__main__":
    main()
