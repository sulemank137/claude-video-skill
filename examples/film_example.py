#!/usr/bin/env python3
"""A five-beat film, to show the shape. Run it against the sample plates:

    python examples/film_example.py --plates examples/plates --out /tmp/frames
    python examples/film_example.py --theme dark --plates examples/plates \
        --out /tmp/frames_dark
    python examples/film_example.py --plates examples/plates --map

Every beat is a function of (frame_in_beat, beat_length, global_frame) that
returns a full 1920x1080 image. The runner blends neighbours automatically —
`("app", b_app, 140, "wipe")` names how a beat ARRIVES, so the seams that start
a new section land instead of washing into each other.

`--map` prints the beat starts in seconds; feed those to score.py --cue/--fills
and the music lands on the cuts.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scripts"))
from promo_kit import (  # noqa: E402
    H, W, backdrop, background, brackets, caption, card, chip, ease, ease_out,
    fade, fit_font, flow_dots, font, glass, plate, paste_card, pulse, run, seq,
    scanbar, sheen, tracked_text, wipe, wordmark, P,
)

TITLE = "ACME STUDIO"
TAGLINE = "CAPTURE   ·   TRAIN   ·   DEPLOY"

# A pipeline for the diagram beat. Boxes are a fixed width, so the labels are
# measured to fit rather than trusted.
STAGES = [("CAPTURE", "GLOVES"), ("REVIEW", "TAGGED"), ("DATASET", "ONE CLICK"),
          ("TRAIN", "8 POLICIES"), ("SHIP", "SAME APP")]
NODE_W, NODE_H, NODE_GAP = 300, 132, 45
NODE_X0 = (W - (len(STAGES) * NODE_W + (len(STAGES) - 1) * NODE_GAP)) // 2


def b_title(i, n, g):
    img = background(g)
    wordmark(img, i, TITLE, TAGLINE, y=H / 2 + 30)
    pulse(img, g)                             # vignette breathing on the beat
    return img


def b_loop(i, n, g):
    """A diagram beat: frosted nodes, a spine that draws itself, dots carrying
    data along it, and a caption panel that stays legible over the backdrop.

    This is the beat to copy when the film has to explain something rather than
    just show it."""
    img = background(g)
    backdrop(img, "app", g, alpha=0.13, blur=34, zoom=1.35)
    t = i / n
    y = 420
    cy = y + NODE_H / 2

    sa = ease((i - 26) / 26.0)                # spine first, nodes sit on it
    if sa > 0.01:
        from PIL import Image, ImageDraw, ImageFilter
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        x_end = NODE_X0 + NODE_W + (len(STAGES) - 1) * (NODE_W + NODE_GAP) * sa
        ImageDraw.Draw(layer).line([(NODE_X0 + NODE_W, cy), (x_end, cy)],
                                   fill=P["ACCENT2"] + (int(150 * sa),), width=4)
        img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(2)))

    for k, (name, note) in enumerate(STAGES):
        a = ease((i - 12 - k * 10) / 22.0)
        if a <= 0.01:
            continue
        x = NODE_X0 + k * (NODE_W + NODE_GAP)
        yy = y + int(20 * (1 - a))
        glass(img, (x, yy, x + NODE_W, yy + NODE_H), radius=18, alpha=a,
              accent=P["ACCENT"])
        sheen(img, x, yy, NODE_W, NODE_H, min(1.0, a * 1.25), radius=18,
              strength=a * 0.8)
        chip(img, x + NODE_W / 2 - 24, yy - 20, f"0{k + 1}", P["ACCENT"],
             alpha=a, size=19)
        tracked_text(img, (x + NODE_W / 2, yy + 54), name,
                     fit_font("title", name, 27, NODE_W - 40, 2.2), P["TEXT"],
                     tracking=2.2, anchor="mm", alpha=255 * a)
        tracked_text(img, (x + NODE_W / 2, yy + 96), note,
                     fit_font("mono", note, 18, NODE_W - 40, 0.8), P["ACCENT"],
                     tracking=0.8, anchor="mm", alpha=235 * a)

    if sa > 0.4:                              # one call per gap, not one long
        for k in range(len(STAGES) - 1):      # line, or dots cross the nodes
            x = NODE_X0 + k * (NODE_W + NODE_GAP)
            flow_dots(img, [(x + NODE_W, cy), (x + NODE_W + NODE_GAP, cy)], g,
                      alpha=sa, count=2, radius=6, speed=0.017)

    # a caption block on a frosted panel, headline typing in per character
    a = fade(t, 0.16, 0.14)
    if a > 0.01:
        prog = ease_out(min(1.0, max(0.0, (t - 0.07) / 0.30)))
        head, sub = "IT IS ONE LOOP, NOT FIVE TOOLS", "NOTHING TO WIRE UP"
        hf, sf = font("title", 46), font("body", 22)
        from PIL import ImageDraw
        d = ImageDraw.Draw(img)
        widest = max(d.textlength(head, font=hf), d.textlength(sub, font=sf) + 60)
        glass(img, (84, 78, 158 + widest * ease_out(min(1.0, t / 0.10)), 240),
              radius=22, alpha=a, accent=P["ACCENT"])
        tracked_text(img, (118, 108), head, hf, P["TEXT"], tracking=0.5,
                     alpha=255 * a, prog=prog, stagger=0.72 / len(head), rise=16)
        ra = ease((prog - 0.5) / 0.30)
        if ra > 0.01:
            tracked_text(img, (118, 180), sub, sf, P["TEXT3"], tracking=2.2,
                         alpha=235 * a * ra)
    pulse(img, g)
    return img


def b_app(i, n, g):
    """The whole product in one shot, pushing in slightly."""
    img = background(g)
    t = i / n
    a = ease(i / 20.0)
    wid = 1500 + 40 * ease(t)                 # float: the zoom ramps smoothly
    p = plate("app", i * (len(seq("app")) - 1) / max(1, n - 1), width=wid)
    x = W / 2 - p.width / 2
    paste_card(img, p, x, 74 - int(14 * ease(t)), radius=12, alpha=a)
    sheen(img, x, 74, p.width, p.height, (i - 14) / 30.0, radius=12,
          strength=a * 0.9)
    caption(img, t, "ONE APP, THE WHOLE LOOP",
            "CAPTURE  ·  REVIEW  ·  TRAIN  ·  SHIP", x=118, y=986, size=44)
    pulse(img, g)
    return img


def b_panel(i, n, g):
    """A live panel beside real footage: the panel is a whole widget grab, so
    its progress bars are present and its layout cannot shift under a crop."""
    img = background(g)
    t = i / n
    # index plates FRACTIONALLY across the beat: a 60-frame capture shown over
    # 150 frames would otherwise repeat every frame 2-3 times and judder
    fi = i * (len(seq("panel")) - 1) / max(1, n - 1)
    card(img, "panel", fi, 110, 300, 900, alpha=ease(i / 18.0),
         shine=(i - 8) / 26.0)
    fa = ease((i - 14) / 22.0)
    fp = plate("footage", i * (len(seq("footage")) - 1) / max(1, n - 1), width=700)
    fy = 330 + int(30 * (1 - fa))
    paste_card(img, fp, 1096, fy, radius=14, alpha=fa)
    # brackets + scan bar say "this plate is a camera, the other one is UI"
    scanbar(img, 1096, fy, fp.width, fp.height, g, alpha=fa * 0.8, radius=14)
    brackets(img, 1096, fy, fp.width, fp.height, alpha=fa, arm=30)
    chip(img, 1096, fy + fp.height + 26, "LIVE  ·  30 Hz", P["ACCENT"],
         alpha=ease((i - 40) / 20.0))
    caption(img, t, "WATCH IT WORK", "REAL DATA  ·  REAL HARDWARE",
            x=118, y=800)
    pulse(img, g)
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


# The fourth item is how the beat ARRIVES: "dissolve" (default) inside a
# section, "wipe" or "flash" where a new section starts.
BEATS = [
    ("title", b_title, 90),
    ("loop", b_loop, 210, "flash"),
    ("app", b_app, 140, "wipe"),
    ("panel", b_panel, 150),
    ("close", b_close, 110),
]


if __name__ == "__main__":
    run(BEATS)
