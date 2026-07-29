#!/usr/bin/env python3
"""Generate throwaway plates so examples/film_example.py runs with no assets.

    python examples/make_sample_plates.py            # -> examples/plates/*
"""
import math
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SPECS = [("app", (2400, 1350), 60), ("panel", (1036, 386), 60),
         ("footage", (1180, 664), 60)]


def main():
    for name, size, n in SPECS:
        d = os.path.join(HERE, "plates", name)
        os.makedirs(d, exist_ok=True)
        for i in range(n):
            bg = (250, 250, 253) if name != "footage" else (40, 60, 90)
            im = Image.new("RGB", size, bg)
            dr = ImageDraw.Draw(im)
            dr.rectangle([0, 0, size[0] - 1, 56], fill=(238, 240, 246))
            dr.text((24, 20), f"{name.upper()}  sample plate  {i:03d}",
                    fill=(20, 24, 40))
            w = int(size[0] * 0.2 + size[0] * 0.6 * i / n)      # a moving bar
            dr.rectangle([24, size[1] - 60, w, size[1] - 30], fill=(60, 120, 220))
            cx = size[0] // 2 + int(size[0] * 0.22 * math.sin(i / 9.0))
            cy = size[1] // 2 + i * 6                            # and a mover
            dr.ellipse([cx - 40, cy - 40, cx + 40, cy + 40], fill=(120, 170, 240))
            im.save(os.path.join(d, f"{i:05d}.png"))
        print(f"{name}: {n} frames at {size[0]}x{size[1]}")


if __name__ == "__main__":
    main()
