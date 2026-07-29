#!/usr/bin/env python3
"""Extract a grid of frames from a video for visual auditing before cutting.

ALWAYS run this before picking timestamps for a promo edit. Screen recordings
are full of static/empty moments (idle forms, "no data yet", loading states)
that look meaningless once cropped in — the only way to find the genuinely
dynamic, cinematic moments is to look at a dense sample of the actual footage
first. Do not guess timestamps from memory or from a script/outline alone.

Usage:
  python3 contact_sheet.py SRC.mp4 --start 0 --end 60 --step 2 --out sheet.jpg
  python3 contact_sheet.py SRC.mp4 --times 12,14,16,18,20 --out sheet.jpg
  python3 contact_sheet.py SRC.mp4 --start 40 --end 52 --step 0.5 --cols 6 --out sheet.jpg

Output tiles are numbered left-to-right, top-to-bottom in the SAME order as
the timestamps you asked for (the script sorts numerically, not lexically —
this avoids the classic "8.3 sorts after 22.1" contact-sheet mislabeling bug).
"""
import argparse
import math
import os
import subprocess
import tempfile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--start", type=float)
    ap.add_argument("--end", type=float)
    ap.add_argument("--step", type=float, default=2.0)
    ap.add_argument("--times", type=str, help="comma-separated explicit timestamps")
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--tile-width", type=int, default=420)
    ap.add_argument("--out", default="contact_sheet.jpg")
    args = ap.parse_args()

    if args.times:
        times = [float(t) for t in args.times.split(",")]
    else:
        assert args.start is not None and args.end is not None, "need --start/--end or --times"
        n = int(round((args.end - args.start) / args.step)) + 1
        times = [round(args.start + i * args.step, 3) for i in range(n)]

    times = sorted(times)  # numeric sort — do NOT rely on filename glob order later
    rows = math.ceil(len(times) / args.cols)

    with tempfile.TemporaryDirectory() as td:
        frame_paths = []
        for i, t in enumerate(times):
            p = os.path.join(td, f"f_{i:04d}.jpg")
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(t), "-i", args.source,
                 "-frames:v", "1", "-q:v", "3", p, "-loglevel", "error"],
                check=True,
            )
            frame_paths.append(p)

        # numbered index inputs (f_0000, f_0001, ...) already in the right
        # numeric order, so a plain glob pattern tiles correctly
        pattern = os.path.join(td, "f_%04d.jpg")
        subprocess.run(
            ["ffmpeg", "-y", "-i", pattern,
             "-vf", f"scale={args.tile_width}:-1,tile={args.cols}x{rows}",
             "-frames:v", "1", args.out, "-loglevel", "error"],
            check=True,
        )

    print(f"wrote {args.out} — {len(times)} frames, order:")
    for i, t in enumerate(times):
        r, c = divmod(i, args.cols)
        print(f"  row{r+1} col{c+1}: t={t}")


if __name__ == "__main__":
    main()
