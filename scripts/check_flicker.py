#!/usr/bin/env python3
"""Prove a UI panel is animating rather than flickering.

A panel that alternates between two states every other frame (because the app's
own data source overwrote the state you injected between grabs) looks "live" in
a still and awful in motion. This is the check:

    check_flicker.py frames_light --box 110,300,1010,640 --start 800 --end 880

Crop to the PANEL only — leave moving footage out of the box, or its legitimate
motion drowns the signal. Exit code is 1 if oscillation is found, so it can sit
in a build script.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", help="directory of rendered PNG frames")
    ap.add_argument("--box", required=True, help="x0,y0,x1,y1 of the panel")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    ap.add_argument("--same", type=float, default=0.05,
                    help="mean abs diff below which two frames count as equal")
    ap.add_argument("--differ", type=float, default=0.5,
                    help="mean abs diff above which two frames count as different")
    args = ap.parse_args()

    box = tuple(int(v) for v in args.box.split(","))
    files = sorted(f for f in os.listdir(args.frames) if f.endswith(".png"))
    if args.end:
        files = files[args.start:args.end]
    elif args.start:
        files = files[args.start:]
    if len(files) < 3:
        raise SystemExit("need at least three frames")

    fr = [np.asarray(Image.open(os.path.join(args.frames, f)).convert("RGB")
                     .crop(box)).astype(int) for f in files]
    d1 = [np.abs(fr[i] - fr[i - 1]).mean() for i in range(1, len(fr))]
    # A-B-A: this frame matches the one two back but differs from the one before
    osc = [i for i in range(2, len(fr))
           if np.abs(fr[i] - fr[i - 2]).mean() < args.same
           and np.abs(fr[i] - fr[i - 1]).mean() > args.differ]

    print(f"frames        {len(fr)}")
    print(f"max Δ         {max(d1):.3f}")
    print(f"mean Δ        {sum(d1) / len(d1):.3f}")
    print(f"oscillations  {len(osc)}"
          + (f"  at {osc[:8]}{'…' if len(osc) > 8 else ''}" if osc else ""))
    if osc:
        print("\nFLICKER. Something is overwriting the state between grabs — "
              "usually a background reader the app restarts on a timer. Stop it "
              "in the per-frame tick, not once at setup.")
        sys.exit(1)
    print("\nno flicker: changes are monotonic frame to frame")


if __name__ == "__main__":
    main()
