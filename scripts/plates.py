#!/usr/bin/env python3
"""Cut source footage into PNG plates at exactly the size the film uses.

Driven by a JSON list so the windows you picked (after actually looking at a
contact sheet — see contact_sheet.py) are written down and re-cuttable:

    [
      {"name": "teleop", "src": "lab.mp4", "start": 59.5, "dur": 7.2,
       "w": 1180, "h": 664, "crop": "1280:720:0:0"},
      {"name": "tool",   "src": "phone.mp4", "start": 336, "dur": 5.2,
       "w": 560, "h": 640, "crop": "700:800:10:300",
       "grade": "eq=contrast=1.12:brightness=0.06:saturation=1.05"}
    ]

    plates.py clips.json --src-dir footage --out plates

`crop` is ffmpeg's `w:h:x:y` in SOURCE pixels and is applied before scaling, so
the plate keeps the source aspect — never scale a crop whose aspect differs from
the target, it stretches faces and UI text.
"""
import argparse
import json
import os
import subprocess

DEFAULT_GRADE = "eq=contrast=1.04:brightness=0.012"
DEFAULT_SHARPEN = "unsharp=5:5:0.45:5:5:0.0"


def cut(clip, src_dir, out_dir, fps):
    name = clip["name"]
    d = os.path.join(out_dir, name)
    os.makedirs(d, exist_ok=True)
    src = clip["src"]
    if not os.path.isabs(src):
        src = os.path.join(src_dir, src)
    chain = []
    if clip.get("crop"):
        chain.append(f"crop={clip['crop']}")
    chain.append(f"scale={clip['w']}:{clip['h']}:flags=lanczos")
    chain.append(clip.get("sharpen", DEFAULT_SHARPEN))
    chain.append(clip.get("grade", DEFAULT_GRADE))
    if fps:
        chain.append(f"fps={fps}")
    cmd = ["ffmpeg", "-v", "error", "-ss", str(clip["start"]),
           "-t", str(clip["dur"]), "-i", src, "-vf", ",".join(chain),
           "-vsync", "0", "-start_number", "0",
           os.path.join(d, "%05d.png"), "-y"]
    subprocess.run(cmd, check=True)
    n = len([f for f in os.listdir(d) if f.endswith(".png")])
    print(f"{name}: {n} frames at {clip['w']}x{clip['h']}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config", help="json list of clips")
    ap.add_argument("--src-dir", default=".")
    ap.add_argument("--out", default="plates")
    ap.add_argument("--fps", type=float, default=30.0,
                    help="normalise here; screen recordings are often VFR")
    ap.add_argument("--only", default="", help="cut a single clip by name")
    args = ap.parse_args()

    clips = json.load(open(args.config))
    for clip in clips:
        if args.only and clip["name"] != args.only:
            continue
        cut(clip, args.src_dir, args.out, args.fps)


if __name__ == "__main__":
    main()
