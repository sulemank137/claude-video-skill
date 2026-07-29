#!/usr/bin/env python3
"""Prove a rendered sequence is smooth: no flicker, no judder, no hard jolts.

Three defects, one pass over the frames:

* **flicker** — the panel alternates A-B-A because the app's own data source
  overwrote the state you injected between grabs;
* **judder** — repeated frames, usually a short capture stretched over a longer
  beat (60 captured frames across 185 output frames shows each one three times);
* **jolts** — single-frame jumps where a dissolve should be.

    check_flicker.py frames_light --box 110,300,1010,640 --start 800 --end 880
    check_flicker.py frames_light                     # whole frame, whole film

Crop to the PANEL when hunting flicker — leave moving footage out of the box, or
its legitimate motion drowns the signal. Exit code is 1 if oscillation is found,
so it can sit in a build script.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", help="directory of rendered PNG frames")
    ap.add_argument("--box", default="", help="x0,y0,x1,y1 of the panel "
                    "(default: the whole frame)")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    ap.add_argument("--same", type=float, default=0.05,
                    help="mean abs diff below which two frames count as equal")
    ap.add_argument("--differ", type=float, default=0.5,
                    help="mean abs diff above which two frames count as different")
    ap.add_argument("--jolt", type=float, default=8.0,
                    help="mean abs diff above which a cut counts as a jolt")
    ap.add_argument("--repeat", type=float, default=2.0,
                    help="max pixel delta below which a frame counts as repeated")
    args = ap.parse_args()

    box = tuple(int(v) for v in args.box.split(",")) if args.box else None
    files = sorted(f for f in os.listdir(args.frames) if f.endswith(".png"))
    if args.end:
        files = files[args.start:args.end]
    elif args.start:
        files = files[args.start:]
    if len(files) < 3:
        raise SystemExit("need at least three frames")

    def load(f):
        im = Image.open(os.path.join(args.frames, f)).convert("RGB")
        return np.asarray(im.crop(box) if box else im.resize((320, 180))).astype(int)

    fr = [load(f) for f in files]
    d1 = [np.abs(fr[i] - fr[i - 1]).mean() for i in range(1, len(fr))]
    # a REPEATED frame is one no pixel moved in. Mean diff cannot tell that from
    # a legitimately static composition (a title card with a slow background),
    # so duplicates are judged on the max pixel delta instead.
    dmax = [np.abs(fr[i] - fr[i - 1]).max() for i in range(1, len(fr))]
    # A-B-A: this frame matches the one two back but differs from the one before
    osc = [i for i in range(2, len(fr))
           if np.abs(fr[i] - fr[i - 2]).mean() < args.same
           and np.abs(fr[i] - fr[i - 1]).mean() > args.differ]

    dupes = [i for i, d in enumerate(dmax, 1) if d <= args.repeat]
    jolts = [i for i, d in enumerate(d1, 1) if d > args.jolt]
    print(f"frames        {len(fr)}")
    print(f"max Δ         {max(d1):.3f}")
    print(f"mean Δ        {sum(d1) / len(d1):.3f}")
    print(f"duplicates    {len(dupes)}  ({100 * len(dupes) / len(d1):.1f}%)"
          + (f"  at {dupes[:8]}{'…' if len(dupes) > 8 else ''}" if dupes else ""))
    print(f"jolts >{args.jolt:g}      {len(jolts)}"
          + (f"  at {jolts[:8]}{'…' if len(jolts) > 8 else ''}" if jolts else ""))
    print(f"oscillations  {len(osc)}"
          + (f"  at {osc[:8]}{'…' if len(osc) > 8 else ''}" if osc else ""))
    if len(dupes) > len(d1) * 0.03:
        print("\nJUDDER: too many repeated frames. A plate sequence is probably "
              "shorter than the beat that shows it — index it fractionally and "
              "blend the two neighbouring frames instead of repeating one.")
    if jolts:
        print("\nJOLTS: single-frame jumps. If a captured state change (a theme "
              "swap, a page switch) lands in one frame, ease it across ~8, and "
              "cross-dissolve where two halves of a beat meet.")
    if osc:
        print("\nFLICKER. Something is overwriting the state between grabs — "
              "usually a background reader the app restarts on a timer. Stop it "
              "in the per-frame tick, not once at setup.")
        sys.exit(1)
    print("\nno flicker: changes are monotonic frame to frame")


if __name__ == "__main__":
    main()
