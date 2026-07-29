#!/usr/bin/env python3
"""A four-beat film, to show the shape. Run it against the sample plates:

    python examples/film_example.py --plates examples/plates --out /tmp/frames
    python examples/film_example.py --theme dark --plates examples/plates \
        --out /tmp/frames_dark

Every beat is a function of (frame_in_beat, beat_length, global_frame) that
returns a full 1920x1080 image. The runner dissolves neighbours automatically.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scripts"))
from promo_kit import (  # noqa: E402
    H, W, background, caption, card, chip, ease, fade, font, plate, paste_card,
    run, seq, tracked_text, wipe, wordmark, P,
)

TITLE = "ACME STUDIO"
TAGLINE = "CAPTURE   ·   TRAIN   ·   DEPLOY"


def b_title(i, n, g):
    img = background(g)
    wordmark(img, i, TITLE, TAGLINE, y=H / 2 + 30)
    return img


def b_app(i, n, g):
    """The whole product in one shot, pushing in slightly."""
    img = background(g)
    t = i / n
    a = ease(i / 20.0)
    wid = 1500 + 40 * ease(t)                 # float: the zoom ramps smoothly
    p = plate("app", i * (len(seq("app")) - 1) / max(1, n - 1), width=wid)
    paste_card(img, p, W / 2 - p.width / 2, 74 - int(14 * ease(t)), radius=12,
               alpha=a)
    caption(img, t, "ONE APP, THE WHOLE LOOP",
            "CAPTURE  ·  REVIEW  ·  TRAIN  ·  SHIP", x=118, y=986, size=44)
    return img


def b_panel(i, n, g):
    """A live panel beside real footage: the panel is a whole widget grab, so
    its progress bars are present and its layout cannot shift under a crop."""
    img = background(g)
    t = i / n
    # index plates FRACTIONALLY across the beat: a 60-frame capture shown over
    # 150 frames would otherwise repeat every frame 2-3 times and judder
    fi = i * (len(seq("panel")) - 1) / max(1, n - 1)
    card(img, "panel", fi, 110, 300, 900, alpha=ease(i / 18.0))
    fa = ease((i - 14) / 22.0)
    fp = plate("footage", i * (len(seq("footage")) - 1) / max(1, n - 1), width=700)
    paste_card(img, fp, 1096, 330 + int(30 * (1 - fa)), radius=14, alpha=fa)
    chip(img, 1096, 330 + fp.height + 26, "LIVE  ·  30 Hz", P["ACCENT"],
         alpha=ease((i - 40) / 20.0))
    caption(img, t, "WATCH IT WORK", "REAL DATA  ·  REAL HARDWARE",
            x=118, y=800)
    return img


def b_close(i, n, g):
    """End where the film opened."""
    img = background(g)
    t = i / n
    wordmark(img, i, TITLE, TAGLINE, url="example.com", y=H / 2 + 10)
    out = ease(1 - (t - 0.86) / 0.14) if t > 0.86 else 1.0
    if out < 1.0:
        from PIL import Image
        img = Image.blend(Image.new("RGBA", img.size, P["FLASH"] + (255,)),
                          img, out)
    return img


BEATS = [
    ("title", b_title, 90),
    ("app", b_app, 140),
    ("panel", b_panel, 150),
    ("close", b_close, 110),
]


if __name__ == "__main__":
    run(BEATS)
