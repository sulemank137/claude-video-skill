#!/usr/bin/env python3
"""A small PIL toolkit for composing a promo film out of plates.

A "plate" is a directory of PNG frames: a UI capture (capture_ui.py), a cut of
camera footage (plates.py), or anything else you can render to a sequence. This
module gives you the page around them — palette, background, cards with
shadows, lower thirds, chips — plus a beat timeline and a CLI, so a film is a
list of `(name, function, length_in_frames)` and nothing else.

Write a film module:

    from promo_kit import *

    def b_title(i, n, g):
        img = background(g)
        wordmark(img, i, "MY PRODUCT", "FAST  ·  SAFE  ·  OPEN")
        return img

    def b_app(i, n, g):
        img = background(g)
        card(img, "app", i, 210, 90, 1500, alpha=ease(i / 20))
        caption(img, i / n, "ONE APP, THE WHOLE LOOP", "AND A SUBTITLE")
        return img

    BEATS = [("title", b_title, 100), ("app", b_app, 150)]
    if __name__ == "__main__":
        run(BEATS)

then:

    python film.py --theme dark --plates plates/dark --out frames/dark
    python film.py --only app --start 40 --end 41 --out /tmp/preview
    for k in 0 1 2 3 4 5 6 7; do python film.py --shard $k/8 --out frames & done; wait

Palettes are yours: `--palette my_theme.json` loads {"light": {...}, "dark":
{...}} with the keys below, so the film can carry the product's own colours.
"""
import argparse
import bisect
import json
import math
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

__all__ = [
    "W", "H", "FPS", "XF", "P", "THEME", "ease", "ease_out", "fade",
    "background", "tracked_text", "fit_font", "paste_card", "plate", "card",
    "caption", "chip", "wordmark", "font", "seq", "frame_at", "run",
    "glass", "sheen", "brackets", "scanbar", "backdrop", "pulse", "chroma",
    "flow_dots", "wipe", "transition", "push", "label", "arrow", "line_chart",
]

W, H = 1920, 1080
FPS = 30
XF = 12                                   # dissolve length between beats, frames
BPM = 118.0                               # only `pulse` uses it; --bpm overrides
BEAT_F = FPS * 60.0 / BPM                 # frames per quarter note

# Brand-neutral defaults. Override with --palette to use the product's own
# theme table; every key here is required.
PALETTES = {
    "light": dict(BG=(244, 245, 250), SURFACE=(255, 255, 255), TEXT=(8, 10, 16),
                  TEXT2=(46, 52, 70), TEXT3=(90, 97, 120),
                  BORDER=(201, 205, 220), ACCENT=(8, 81, 159),
                  ACCENT2=(47, 138, 232), GRID=(150, 160, 200),
                  PARTICLE=(80, 140, 220), SHADOW=(24, 34, 64, 58),
                  FLASH=(255, 255, 255)),
    "dark":  dict(BG=(7, 7, 13), SURFACE=(15, 15, 24), TEXT=(238, 238, 255),
                  TEXT2=(144, 144, 184), TEXT3=(80, 80, 112),
                  BORDER=(62, 62, 88), ACCENT=(32, 144, 255),
                  ACCENT2=(32, 144, 255), GRID=(30, 40, 90),
                  PARTICLE=(40, 130, 255), SHADOW=(0, 0, 0, 150),
                  FLASH=(0, 0, 0)),
}

# P is MUTATED in place by run(), never rebound. Films are told to do
# `from promo_kit import *`, and a rebind would leave every caller holding the
# light palette forever — the film would render dark-on-dark and only the text
# drawn inside this module would follow --theme.
P = dict(PALETTES["light"])
THEME = "light"
PLATES = "plates"
FONTS = {                                  # override with --fonts fontdir
    "display": "DejaVuSans-Bold",
    "title": "DejaVuSans-Bold",
    "body": "DejaVuSans",
    "mono": "DejaVuSansMono",
}
FONT_DIRS = ["/usr/share/fonts/truetype/dejavu"]

_font_cache, _seq_cache, _img_cache, _shadow_cache = {}, {}, {}, {}
_grid_tile = _edge = _base = None


# ── assets ────────────────────────────────────────────────────────────────────

def font(role_or_file, size):
    """`font("title", 52)` or `font("Inter-Bold", 52)` — roles map through FONTS."""
    name = FONTS.get(role_or_file, role_or_file)
    key = (name, size)
    if key not in _font_cache:
        for d in FONT_DIRS:
            for ext in (".ttf", ".otf", ".ttc"):
                p = os.path.join(d, name + ext)
                if os.path.exists(p):
                    _font_cache[key] = ImageFont.truetype(p, size)
                    return _font_cache[key]
        raise SystemExit(f"font {name!r} not found in {FONT_DIRS} — pass --fonts")
    return _font_cache[key]


def seq(name):
    """Frame paths of a plate directory, resolved under --plates."""
    if name not in _seq_cache:
        d = name if os.path.isabs(name) else os.path.join(PLATES, name)
        if not os.path.isdir(d):
            raise SystemExit(f"no plate directory {d!r}")
        _seq_cache[name] = [os.path.join(d, f) for f in sorted(os.listdir(d))
                            if f.endswith(".png")]
    return _seq_cache[name]


def _load(path):
    if path not in _img_cache:
        if len(_img_cache) > 40:               # plates are big; cap the cache
            _img_cache.clear()
        _img_cache[path] = Image.open(path).convert("RGBA")
    return _img_cache[path]


def frame_at(name, i):
    """A plate frame at a FRACTIONAL index.

    A 60-frame capture stretched over a 185-frame beat otherwise shows each
    captured frame three times, which reads as judder. Blending the two
    neighbours turns the repeat into continuous motion, so always index a plate
    as `i * (len(seq(name)) - 1) / (n - 1)` rather than with an int."""
    files = seq(name)
    last = len(files) - 1
    i = max(0.0, min(float(last), float(i)))
    lo = int(i)
    frac = i - lo
    a = _load(files[lo])
    if frac < 0.02 or lo >= last:
        return a
    return Image.blend(a, _load(files[lo + 1]), frac)


# ── easing ────────────────────────────────────────────────────────────────────

def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def fade(t, up=0.12, down=0.12):
    """In/out envelope across a normalised beat time."""
    return min(ease(t / up), ease((1 - t) / down))


# ── background ────────────────────────────────────────────────────────────────

def _grid():
    global _grid_tile
    if _grid_tile is None:
        step, a = 60, 44 if THEME == "light" else 90
        t = Image.new("RGBA", (W + step, H + step), (0, 0, 0, 0))
        d = ImageDraw.Draw(t)
        for x in range(0, t.width, step):
            d.line([(x, 0), (x, t.height)], fill=P["GRID"] + (a,), width=1)
        for y in range(0, t.height, step):
            d.line([(0, y), (t.width, y)], fill=P["GRID"] + (a,), width=1)
        _grid_tile = t
    return _grid_tile


def _edge_shade():
    global _edge
    if _edge is None:
        m = Image.new("L", (W // 4, H // 4), 0)
        ImageDraw.Draw(m).ellipse([-W // 10, -H // 10, W // 4 + W // 10,
                                   H // 4 + H // 10], fill=255)
        m = m.filter(ImageFilter.GaussianBlur(52)).resize((W, H))
        tint = (206, 212, 232) if THEME == "light" else (0, 0, 0)
        k = 0.55 if THEME == "light" else 0.85
        v = Image.new("RGBA", (W, H), tint + (255,))
        v.putalpha(Image.eval(m, lambda p: int((255 - p) * k)))
        _edge = v
    return _edge


def background(g):
    """The moving brand plate. The static half is built once and copied, and the
    glow is painted at quarter resolution — a full-size Gaussian per frame is
    the single most expensive thing a compositor like this can do."""
    global _base
    if _base is None:
        b = Image.new("RGBA", (W, H), P["BG"] + (255,))
        if THEME == "light":
            top = Image.new("RGBA", (W, H), P["SURFACE"] + (0,))
            td = ImageDraw.Draw(top)
            for y in range(0, H, 4):
                td.rectangle([0, y, W, y + 4],
                             fill=P["SURFACE"] + (int(150 * (1 - y / H)),))
            b.alpha_composite(top)
        b.alpha_composite(_edge_shade())
        _base = b
    img = _base.copy()

    off = (g * 0.35) % 60
    img.alpha_composite(_grid(), dest=(0, 0),
                        source=(int(off), int(off), W + int(off), H + int(off)))

    gw, gh = W // 4, H // 4
    glow = Image.new("RGBA", (gw, gh), (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    sweep = (g / (FPS * 11.0)) % 1.0
    x = (-300 + sweep * (W + 600)) / 4
    d.rectangle([x - 60, 0, x + 60, gh],
                fill=P["ACCENT2"] + (12 if THEME == "light" else 18,))
    for k in range(22):
        px = ((k * 137 + g * (0.5 + 0.04 * (k % 5))) % (W + 200) - 100) / 4
        py = ((k * 311 + 36 * math.sin(g / 44.0 + k)) % H) / 4
        r = (1.5 + (k % 3)) / 2
        d.ellipse([px - r, py - r, px + r, py + r],
                  fill=P["PARTICLE"] + (54 if THEME == "light" else 70,))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(2.5))
                        .resize((W, H), Image.BILINEAR))
    return img


# ── drawing ───────────────────────────────────────────────────────────────────

def tracked_text(img, xy, text, fnt, fill, tracking=0, anchor="lt", alpha=255,
                 prog=1.0, stagger=0.0, rise=0.0):
    """PIL has no letter-spacing, and display type needs it.

    `stagger` > 0 makes the line kinetic: character k starts arriving once
    `prog >= k * stagger` and rises `rise` px into place as it fades up. The
    layout is measured from the FINISHED string, so nothing reflows while the
    letters land. Keep `stagger * len(text) + 0.22 <= 1.0` — otherwise `prog`
    saturates before the tail has finished its own ramp and the line settles
    with its last few letters permanently half-lit."""
    d = ImageDraw.Draw(img)
    widths = [d.textlength(ch, font=fnt) for ch in text]
    total = sum(widths) + tracking * max(0, len(text) - 1)
    asc, desc = fnt.getmetrics()
    x, y = xy
    if anchor[0] == "m":
        x -= total / 2
    elif anchor[0] == "r":
        x -= total
    if anchor[1] == "m":
        y -= (asc + desc) / 2
    elif anchor[1] == "b":
        y -= asc + desc
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    cx = x
    for k, (ch, wd) in enumerate(zip(text, widths)):
        if stagger:
            p = ease((prog - k * stagger) / 0.22)
            if p > 0.004:
                ld.text((cx, y + rise * (1 - p)), ch, font=fnt,
                        fill=fill + (int(alpha * p),))
        else:
            ld.text((cx, y), ch, font=fnt, fill=fill + (int(alpha),))
        cx += wd + tracking
    img.alpha_composite(layer)
    return total


def fit_font(role_or_file, text, size, limit, tracking=0.0, floor=13):
    """Largest size ≤ `size` at which `text` fits inside `limit` px.

    Any label laid into a fixed-width box has to be measured, not guessed —
    product names and translated strings are never the width you assumed, and
    the overflow is silent."""
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    s = size
    while s > floor:
        f = font(role_or_file, s)
        if d.textlength(text, font=f) + tracking * max(0, len(text) - 1) <= limit:
            return f
        s -= 1
    return font(role_or_file, floor)


def _rounded_mask(size, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1],
                                        radius, fill=255)
    return m


def paste_card(img, im, x, y, radius=16, alpha=1.0, shadow=28, lift=14,
               border=True):
    """Drop an image on the page as a product card: rounded, hairline border,
    soft shadow. The shadow is what keeps a white card off a white background,
    and it is cached by (size, radius) because it is a Gaussian."""
    if alpha <= 0.01:
        return
    im = im.convert("RGBA")
    # sub-pixel placement: a 40 px push over 150 frames moves 0.27 px/frame, and
    # pasting at integer coordinates turns that into a visible stair-step
    fx, fy = x - math.floor(x), y - math.floor(y)
    if fx > 0.02 or fy > 0.02:
        im = im.transform(im.size, Image.AFFINE, (1, 0, -fx, 0, 1, -fy),
                          resample=Image.BICUBIC)
        x, y = math.floor(x), math.floor(y)
    m = _rounded_mask(im.size, radius)
    if alpha < 1.0:
        m = m.point(lambda v: int(v * alpha))
    if shadow:
        key = (im.size, radius, shadow, THEME)
        if key not in _shadow_cache:
            sh = Image.new("RGBA", (im.width + shadow * 2, im.height + shadow * 2),
                           (0, 0, 0, 0))
            ImageDraw.Draw(sh).rounded_rectangle(
                [shadow, shadow, shadow + im.width, shadow + im.height],
                radius + 4, fill=P["SHADOW"])
            _shadow_cache[key] = sh.filter(ImageFilter.GaussianBlur(shadow * .55))
        sh = _shadow_cache[key]
        if alpha < 1.0:
            sh = sh.copy()
            sh.putalpha(sh.getchannel("A").point(lambda v: int(v * alpha)))
        img.alpha_composite(sh, dest=(int(x - shadow), int(y - shadow + lift)))
    body = im.copy()
    body.putalpha(m)
    img.alpha_composite(body, dest=(int(x), int(y)))
    if border:
        ol = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(ol).rounded_rectangle([0, 0, im.width - 1, im.height - 1],
                                             radius,
                                             outline=P["BORDER"] + (int(230 * alpha),),
                                             width=2)
        img.alpha_composite(ol, dest=(int(x), int(y)))


def push(im, zoom=1.0, focus=(0.5, 0.5), size=None):
    """Crop into `im` by `zoom` around `focus` (fractions of width and height)
    and resample to `size` — default `im.size` — in one affine op.

    Works on any image: a still (a product shot, a generated picture, a slide)
    or one frame of a plate. The window takes the OUTPUT aspect, so nothing is
    ever stretched, and it is clamped INSIDE the image: `Image.crop` with a box
    past the edge does not fail, it pads with black, and that lands as a dark
    band along one side of the card on exactly the frames where the focus
    drifts near an edge. Floats all the way down, so a 1.0 -> 1.1 push over 150
    frames glides instead of stepping a pixel at a time."""
    zoom = max(1.0, float(zoom))
    ow, oh = size or im.size
    ar = ow / oh

    def window(w, h):
        cw, ch = (w, w / ar) if w / h <= ar else (h * ar, h)
        return cw / zoom, ch / zoom

    cw, ch = window(*im.size)
    f = int(cw / ow)
    if f >= 2:                # an affine resample does not antialias a big shrink
        im = im.reduce(f)
        cw, ch = window(*im.size)
    cx = min(max(im.width * focus[0], cw / 2), im.width - cw / 2)
    cy = min(max(im.height * focus[1], ch / 2), im.height - ch / 2)
    return im.transform((int(ow), int(oh)), Image.AFFINE,
                        (cw / ow, 0, cx - cw / 2, 0, ch / oh, cy - ch / 2),
                        resample=Image.BICUBIC)


def plate(name, i, width=None, height=None, box=None, zoom=1.0):
    """One frame of a plate, optionally cropped, zoomed and scaled."""
    im = frame_at(name, i)
    if box:
        im = im.crop(box)
    if zoom != 1.0:
        im = push(im, zoom)
    # scale on a float and resample in one affine op, so a slow zoom ramps
    # smoothly instead of jumping a whole pixel every few frames
    if height and not width:
        width = im.width * height / im.height
    if width:
        height = height or im.height * width / im.width
        w_i, h_i = max(1, int(round(width))), max(1, int(round(height)))
        im = im.transform((w_i, h_i), Image.AFFINE,
                          (im.width / width, 0, 0, 0, im.height / height, 0),
                          resample=Image.BICUBIC)
    return im


def card(img, name, i, x, y, width, alpha=1.0, radius=14, slide=0, box=None,
         shine=None):
    """Paste a plate frame as a card; returns its height so the next one can
    stack under it. Pass the card's own entry ramp as `shine` and a specular
    band crosses it exactly as it lands."""
    p = plate(name, i, width=width, box=box)
    paste_card(img, p, x + slide, y, radius=radius, alpha=alpha)
    if shine is not None:
        sheen(img, x + slide, y, p.width, p.height, shine, radius=radius,
              strength=alpha)
    return p.height


# ── effects ───────────────────────────────────────────────────────────────────
# Everything here is cheap on purpose. A full-size Gaussian per frame is the one
# thing that will make a 2000-frame film take an hour, so each of these either
# works at a fraction of the resolution, caches its expensive part, or paints
# into a layer the size of the thing it decorates rather than the whole page.

def glass(img, box, radius=20, alpha=1.0, strength=1.0, blur=20, border=True,
          accent=None):
    """A frosted panel: whatever is already behind `box`, blurred and tinted.

    This is how you keep a caption legible over a busy UI plate without a flat
    slab covering it. Blurred at quarter resolution — a 20 px Gaussian over a
    1920x200 region costs more than the rest of the frame, and after the upscale
    nobody can tell."""
    if alpha <= 0.01:
        return
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x1), min(H, y1)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return
    reg = img.crop((x0, y0, x1, y1))
    sw, sh = max(1, (x1 - x0) // 4), max(1, (y1 - y0) // 4)
    reg = (reg.resize((sw, sh), Image.BILINEAR)
              .filter(ImageFilter.GaussianBlur(blur / 4.0))
              .resize((x1 - x0, y1 - y0), Image.BICUBIC))
    tint = P["SURFACE"] if THEME == "light" else (10, 12, 22)
    reg.alpha_composite(Image.new("RGBA", reg.size, tint + (
        int((186 if THEME == "light" else 200) * strength),)))
    m = _rounded_mask(reg.size, radius)
    if alpha < 1.0:
        m = m.point(lambda v: int(v * alpha))
    reg.putalpha(m)
    img.alpha_composite(reg, dest=(x0, y0))
    ol = Image.new("RGBA", reg.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(ol)
    if border:
        od.rounded_rectangle([0, 0, reg.width - 1, reg.height - 1], radius,
                             outline=P["BORDER"] + (int(190 * alpha),), width=2)
    if accent:
        od.rounded_rectangle([0, 14, 5, reg.height - 15], 3,
                             fill=accent + (int(240 * alpha),))
    img.alpha_composite(ol, dest=(x0, y0))


def sheen(img, x, y, w, h, prog, radius=14, strength=1.0):
    """A specular band sweeping once across a card as it lands. `prog` outside
    0..1 draws nothing, so you can hand it a raw `(i - 14) / 30.0`."""
    if prog <= 0.0 or prog >= 1.0 or strength <= 0.01:
        return
    peak = math.sin(math.pi * prog) ** 0.7             # brightest mid-sweep
    layer = Image.new("RGBA", (int(w), int(h)), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx = -w * 0.45 + prog * (w * 1.9)
    band = max(40, w * 0.06)
    for k in range(-int(band), int(band) + 1, 5):
        a = int(120 * strength * peak * (1 - abs(k) / band) ** 2)
        if a <= 1:
            continue
        d.line([(cx + k, h), (cx + k + h * 0.55, 0)], fill=(255, 255, 255, a),
               width=7)
    layer = layer.filter(ImageFilter.GaussianBlur(7))
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"),
                                       _rounded_mask(layer.size, radius)))
    img.alpha_composite(layer, dest=(int(x), int(y)))


def brackets(img, x, y, w, h, alpha=1.0, arm=38, colour=None, width=4):
    """Four corner ticks — reads as a viewfinder over live footage, and tells
    the eye that this plate is camera and not UI."""
    if alpha <= 0.01:
        return
    colour = colour or P["ACCENT2"]
    layer = Image.new("RGBA", (int(w) + 4, int(h) + 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c = colour + (int(225 * alpha),)
    for cx, cy, sx, sy in ((0, 0, 1, 1), (w, 0, -1, 1), (0, h, 1, -1),
                           (w, h, -1, -1)):
        d.line([(cx, cy), (cx + sx * arm, cy)], fill=c, width=width)
        d.line([(cx, cy), (cx, cy + sy * arm)], fill=c, width=width)
    img.alpha_composite(layer, dest=(int(x) - 2, int(y) - 2))


def scanbar(img, x, y, w, h, g, alpha=1.0, radius=16, period=70.0, colour=None):
    """A soft bright line travelling down a footage plate."""
    if alpha <= 0.01:
        return
    colour = colour or P["ACCENT2"]
    w, h = int(w), int(h)
    yy = ((g % period) / period) * (h + 60) - 30
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for k in range(-10, 11, 2):
        d.line([(0, yy + k), (w, yy + k)],
               fill=colour + (int(46 * alpha * (1 - abs(k) / 11.0)),), width=3)
    layer = layer.filter(ImageFilter.GaussianBlur(4))
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"),
                                       _rounded_mask((w, h), radius)))
    img.alpha_composite(layer, dest=(int(x), int(y)))


_backdrop_cache = {}


def backdrop(img, name, g, alpha=0.20, blur=30, zoom=1.5, drift=26.0):
    """A big, blurred, slowly drifting copy of a plate behind the cards — depth
    for free, in either theme.

    ONE captured frame, blurred once and cached. Blurring a fresh frame every
    tick costs more than every other effect here combined, and a 30 px blur of a
    moving UI looks identical to a 30 px blur of a still one."""
    if alpha <= 0.01:
        return
    key = (name, blur, zoom, THEME)
    if key not in _backdrop_cache:
        src = frame_at(name, 0)
        tw = int(W * zoom)
        src = src.resize((tw, int(src.height * tw / src.width)), Image.LANCZOS)
        small = src.resize((tw // 6, max(1, src.height // 6)), Image.BILINEAR)
        _backdrop_cache[key] = (small.filter(ImageFilter.GaussianBlur(blur / 6.0))
                                     .resize(src.size, Image.BICUBIC))
    b = _backdrop_cache[key]
    dx = max(0, min(b.width - W,
                    int((b.width - W) / 2 + drift * math.sin(g / 190.0))))
    dy = max(0, min(b.height - H,
                    int((b.height - H) / 2 + drift * 0.6 * math.cos(g / 240.0))))
    reg = b.crop((dx, dy, dx + W, dy + H)).copy()
    reg.putalpha(int(255 * alpha))
    img.alpha_composite(reg)


_pulse_cache = {}


def pulse(img, g, depth=0.055):
    """A vignette that breathes on the musical beat, so the picture moves with
    the score instead of alongside it. Set BPM (or --bpm) to the score's tempo.

    Eight quantised levels, each cached — recomputing an alpha ramp over a
    1920x1080 mask a couple of thousand times is pure waste and the step between
    levels is invisible."""
    phase = (g % BEAT_F) / BEAT_F
    amt = depth * max(0.0, math.cos(phase * math.pi * 0.9)) ** 2
    lvl = int(amt / depth * 7.99)
    if lvl <= 0:
        return
    if lvl not in _pulse_cache:
        v = _edge_shade().copy()
        v.putalpha(v.getchannel("A").point(lambda p: int(p * lvl / 7.0 * 0.85)))
        _pulse_cache[lvl] = v
    img.alpha_composite(_pulse_cache[lvl])


def chroma(img, amt):
    """Split the channels a couple of pixels. Accent frames only — a handful at
    a hard section landing, never continuous."""
    if amt < 0.35:
        return img
    r, g, b, a = img.split()
    px = int(round(amt))
    return Image.merge("RGBA", (ImageChops.offset(r, px, 0), g,
                                ImageChops.offset(b, -px, 0), a))


def flow_dots(img, pts, g, alpha=1.0, colour=None, speed=0.011, count=5,
              radius=5):
    """Dots running along a polyline — data moving through a pipeline diagram.
    Draw one call per gap between nodes rather than one long line, or the dots
    track straight across the nodes themselves."""
    if alpha <= 0.01 or len(pts) < 2:
        return
    colour = colour or P["ACCENT2"]
    segs = [(pts[k], pts[k + 1]) for k in range(len(pts) - 1)]
    lens = [math.dist(a, b) for a, b in segs]
    total = sum(lens) or 1.0
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for k in range(count):
        want = (((g * speed) + k / count) % 1.0) * total
        for (a, b), ln in zip(segs, lens):
            if want <= ln or (a, b) is segs[-1]:
                f = min(1.0, want / max(1e-6, ln))
                x, y = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
                r = radius * (0.7 + 0.3 * math.sin(g / 6.0 + k))
                d.ellipse([x - r, y - r, x + r, y + r],
                          fill=colour + (int(235 * alpha),))
                break
            want -= ln
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(2)))


def caption(img, t, title, sub=None, x=120, y=880, colour=None, size=52,
            step=None):
    """Lower third: a rule that wipes out, then the line rising under it.
    Keep `y` at 930 or less when there is a subtitle — 1080 comes fast.

    `step` ("01", "02", ...) is set in mono ahead of the first title line, so a
    walk through a sequence — a pipeline, a checkout, an onboarding flow — reads
    as one numbered story rather than a run of unrelated shots."""
    colour = colour or P["ACCENT"]
    a = fade(t, 0.16, 0.14)
    if a <= 0.01:
        return
    rule_w = int(300 * ease(t / 0.35))
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rectangle([x, y - 28, x + rule_w, y - 23],
                                    fill=colour + (int(235 * a),))
    img.alpha_composite(layer)
    rise = int(18 * (1 - ease(t / 0.3)))
    lines = title.split("\n")
    sx = x
    if step:
        sx += tracked_text(img, (x, y + rise + int(size * 0.25)), str(step),
                           font("mono", int(size * 0.56)), colour, tracking=1,
                           alpha=255 * a) + int(size * 0.42)
    for k, line in enumerate(lines):
        tracked_text(img, (sx if k == 0 else x, y + rise + k * int(size * 1.18)),
                     line, font("title", size), P["TEXT"], tracking=0.5,
                     alpha=255 * a)
    if sub:
        tracked_text(img, (x, y + int(size * 1.18) * (len(lines) - 1) + size + 20
                           + rise), sub, font("body", 26), P["TEXT3"],
                     tracking=2.4, alpha=225 * a)


def chip(img, x, y, text, colour=None, alpha=1.0, size=24, mono=True,
         anchor="l"):
    """A small outlined tag. `anchor` is l / m / r on `x`, so a column of chips
    can hang off a right edge without measuring each one first. Returns the
    width even while invisible, so `x += chip(...) + gap` rows never shift as
    their chips fade in."""
    colour = colour or P["ACCENT"]
    f = font("mono" if mono else "body", size)
    d = ImageDraw.Draw(img)
    w = d.textlength(text, font=f)
    box = Image.new("RGBA", (int(w) + 34, size + 22), (0, 0, 0, 0))
    bd = ImageDraw.Draw(box)
    bd.rounded_rectangle([0, 0, box.width - 1, box.height - 1], 11,
                         fill=P["SURFACE"] + (int(240 * alpha),),
                         outline=colour + (int(160 * alpha),), width=2)
    bd.text((17, 10), text, font=f, fill=colour + (int(255 * alpha),))
    if alpha > 0.01:
        if anchor[0] == "m":
            x -= box.width / 2
        elif anchor[0] == "r":
            x -= box.width
        img.alpha_composite(box, dest=(int(x), int(y)))
    return box.width


def label(img, cx, y, title, sub=None, alpha=1.0, colour=None, size=28):
    """Two short lines centred under a card, naming what the plate IS — BEFORE /
    AFTER, SOURCE / RESULT, a language under its translation. Captions tell the
    story; labels name the pieces of a side-by-side."""
    if alpha <= 0.01:
        return
    tracked_text(img, (cx, y), title, font("title", size), colour or P["TEXT"],
                 tracking=0.5, anchor="mt", alpha=255 * alpha)
    if sub:
        tracked_text(img, (cx, y + int(size * 1.42)), sub,
                     font("body", int(size * 0.68)), P["TEXT3"], tracking=3,
                     anchor="mt", alpha=220 * alpha)


def arrow(img, x0, x1, y, prog, colour=None, width=5, head=14):
    """A horizontal arrow drawing itself from `x0` to `x1` as `prog` runs 0 -> 1
    — the "this becomes that" between two cards. `prog` is clamped, so a raw
    `(i - 14) / 20` is fine; pass `x1 < x0` to point left."""
    if prog <= 0.01:
        return
    colour = colour or P["ACCENT"]
    s = 1 if x1 >= x0 else -1
    xe = x0 + (x1 - x0) * ease_out(prog)
    c = colour + (int(230 * min(1.0, prog * 3)),)
    ox = min(x0, x1) - head - 8                  # a layer the size of the arrow
    oy = y - head - 4
    layer = Image.new("RGBA", (int(abs(x1 - x0) + 2 * head + 16), 2 * head + 8),
                      (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.line([(x0 - ox, y - oy), (xe - ox, y - oy)], fill=c, width=width)
    d.polygon([(xe + s * head - ox, y - oy), (xe - s * 6 - ox, y - head - oy),
               (xe - s * 6 - ox, y + head - oy)], fill=c)
    img.alpha_composite(layer, dest=(int(ox), int(oy)))


_chart_cache = {}


def line_chart(xs, ys, w, h, prog=1.0, title="", sub="", ymin=None, ymax=None,
               xticks=(), yticks=(), xfmt=str, yfmt=str, readout=None,
               colour=None, key=None):
    """A metric chart as a card-sized image: the line draws itself left to right
    as `prog` runs 0 -> 1, with a dot riding the front. Paste it with
    `paste_card`.

    Everything static — title, ticks, grid, the whole filled line — is drawn
    ONCE at 2x and cached; a frame is the empty axes plus a crop of the finished
    line. Redrawing a 500-point polyline and its fill every frame is slow, and
    at 1x it aliases. Thin the data to a few hundred points before passing it.
    `readout(x, y)` returns the text shown top-right as the front advances, e.g.
    `lambda x, y: f"{x:,.0f} USERS"`.

    A chart on screen is a claim. Plot the metric as it was logged. If you
    bridge or smooth anything — a restart artefact, an outage gap, a backfill —
    check both sides meet at the same level, and say so in the notes that ship
    with the film."""
    colour = colour or P["ACCENT"]
    key = key or (len(xs), xs[0], xs[-1], sum(ys), w, h, title, THEME)
    if key not in _chart_cache:
        s = 2
        lo = min(ys) if ymin is None else ymin
        hi = max(ys) * 1.1 if ymax is None else ymax
        x0, y0 = 110 * s, (118 if title else 50) * s
        x1, y1 = (w - 50) * s, (h - 78) * s

        def px(v):
            return x0 + (x1 - x0) * (v - xs[0]) / ((xs[-1] - xs[0]) or 1)

        def py(v):
            return y1 - (y1 - y0) * (min(hi, max(lo, v)) - lo) / ((hi - lo) or 1)

        base = Image.new("RGBA", (w * s, h * s), P["SURFACE"] + (255,))
        d = ImageDraw.Draw(base)
        if title:
            tf = font("title", 30 * s)
            d.text((40 * s, 32 * s), title, font=tf, fill=P["TEXT"])
            if sub:
                d.text((40 * s + d.textlength(title, font=tf) + 24 * s, 42 * s),
                       sub, font=font("body", 17 * s), fill=P["TEXT3"])
        tick = font("mono", 16 * s)
        for v in yticks:
            d.line([(x0, py(v)), (x1, py(v))], fill=P["BORDER"] + (255,), width=s)
            d.text((x0 - 20 * s, py(v)), yfmt(v), font=tick, fill=P["TEXT3"],
                   anchor="rm")
        for v in xticks:
            d.text((px(v), y1 + 16 * s), xfmt(v), font=tick, fill=P["TEXT3"],
                   anchor="mt")
        axes = base.copy()
        poly = [(px(a), py(b)) for a, b in zip(xs, ys)]
        fill = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(fill).polygon(poly + [(poly[-1][0], y1), (poly[0][0], y1)],
                                     fill=P["ACCENT2"] + (40,))
        base.alpha_composite(fill)
        ImageDraw.Draw(base).line(poly, fill=colour + (255,), width=4 * s,
                                  joint="curve")
        _chart_cache[key] = dict(axes=axes.resize((w, h), Image.LANCZOS),
                                 full=base.resize((w, h), Image.LANCZOS),
                                 box=(x0 / s, y0 / s, x1 / s, y1 / s), lo=lo, hi=hi)
    c = _chart_cache[key]
    x0, y0, x1, y1 = c["box"]
    prog = max(0.0, min(1.0, prog))
    im = c["axes"].copy()
    fx = x0 + (x1 - x0) * prog
    im.alpha_composite(c["full"].crop((0, 0, int(fx) + 2, h)), dest=(0, 0))
    if prog > 0.0:
        xv = xs[0] + (xs[-1] - xs[0]) * prog
        j = min(len(xs) - 1, max(1, bisect.bisect_left(xs, xv)))
        span = (xs[j] - xs[j - 1]) or 1
        yv = ys[j - 1] + (ys[j] - ys[j - 1]) * min(1.0, max(0.0, (xv - xs[j - 1]) / span))
        fy = y1 - (y1 - y0) * (min(c["hi"], max(c["lo"], yv)) - c["lo"]) / (
            (c["hi"] - c["lo"]) or 1)
        d = ImageDraw.Draw(im)
        d.ellipse([fx - 8, fy - 8, fx + 8, fy + 8], fill=colour + (255,))
        d.ellipse([fx - 15, fy - 15, fx + 15, fy + 15],
                  outline=P["ACCENT2"] + (120,), width=3)
        if readout:
            d.text((w - 44, 40), readout(xv, yv), font=font("mono", 20),
                   fill=colour, anchor="ra")
    return im


def wordmark(img, i, title, tagline=None, logo=None, url=None, y=None):
    """The intro card. Use the same function for the closing card — a film that
    ends where it opened reads as finished rather than cut off."""
    y = H / 2 if y is None else y
    a = ease(i / 24.0)
    bar_w = int(1120 * ease_out(i / 32.0))
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rectangle([W / 2 - bar_w / 2, y - 98,
                                     W / 2 + bar_w / 2, y - 93],
                                    fill=P["ACCENT"] + (int(220 * a),))
    img.alpha_composite(layer)
    if logo and os.path.exists(logo):
        la = ease((i - 6) / 24.0)
        if la > 0:
            lg = Image.open(logo).convert("RGBA")
            lw = 300
            lg = lg.resize((lw, int(lg.height * lw / lg.width)), Image.LANCZOS)
            lg.putalpha(lg.getchannel("A").point(lambda v: int(v * la)))
            img.alpha_composite(lg, dest=(int(W / 2 - lw / 2),
                                          int(y - 98 - lg.height - 54)))
    tracked_text(img, (W / 2, y - 12), title, font("display", 82), P["TEXT"],
                 tracking=6, anchor="mm", alpha=255 * a)
    if tagline:
        sa = ease((i - 24) / 26.0)
        if sa > 0:
            tracked_text(img, (W / 2, y + 78), tagline, font("body", 30),
                         P["TEXT3"], tracking=9, anchor="mm", alpha=230 * sa)
    if url:
        ua = ease((i - 40) / 24.0)
        if ua > 0:
            tracked_text(img, (W / 2, y + 168), url, font("mono", 24),
                         P["TEXT3"], tracking=3, anchor="mm", alpha=200 * ua)


def wipe(img, a_img, b_img, x, y, frac, radius=12, alpha=1.0):
    """Reveal `b_img` over `a_img` with a hard vertical edge. Use this — never a
    cross-dissolve — when both plates carry text (two languages, two themes):
    overlapping glyphs are unreadable mush."""
    cut = int(a_img.width * max(0.0, min(1.0, frac)))
    p = a_img.copy()
    if cut > 0:
        p.paste(b_img.crop((0, 0, cut, b_img.height)), (0, 0))
    paste_card(img, p, x, y, radius=radius, alpha=alpha)
    if 0 < cut < a_img.width:
        edge = Image.new("RGBA", (6, p.height), P["ACCENT"] + (int(200 * alpha),))
        img.alpha_composite(edge, dest=(int(x + cut - 3), int(y)))


def transition(a, b, t, kind="dissolve"):
    """Blend two beats across a seam, `t` running 0 → 1 over XF frames.

    A film where every seam cross-dissolves reads as one long even wash. Name a
    `kind` on the beats that start a new section and the structure lands:

    * `dissolve` — the default, for beats inside a section;
    * `wipe` — `b` comes in from the left behind a lit edge;
    * `flash` — through the palette's FLASH colour, i.e. white in light and
      black in dark. Note the midpoint is a FULLY flat frame; if that reads as
      an encoding glitch in your cut rather than as a beat, blend the flash over
      a dissolve instead:
      `blend(blend(a, b, ease(t)), f, 0.82 * ease(1 - abs(2 * t - 1)))`.
    """
    if kind == "wipe":
        cut = int(W * ease_out(t))
        out = a.copy()
        if cut > 0:
            out.paste(b.crop((0, 0, cut, H)), (0, 0))
        if 0 < cut < W:
            band = Image.new("RGBA", (170, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(band)
            hue = (255, 255, 255) if THEME == "light" else P["ACCENT2"]
            for k in range(0, 170, 4):
                d.rectangle([k, 0, k + 4, H],
                            fill=hue + (int(165 * (k / 170.0) ** 2),))
            out.alpha_composite(band.filter(ImageFilter.GaussianBlur(9)),
                                dest=(max(0, cut - 162), 0))
        return out
    if kind == "flash":
        f = Image.new("RGBA", a.size, P["FLASH"] + (255,))
        if t < 0.5:
            return Image.blend(a, f, ease(t / 0.5) * 0.88)
        return Image.blend(f, b, ease((t - 0.5) / 0.5))
    return Image.blend(a, b, ease(t))


# ── timeline + CLI ────────────────────────────────────────────────────────────

def timeline(beats):
    """(start, name, fn, length, kind) per beat, overlapping by XF.

    A beat is `(name, fn, length)` or `(name, fn, length, transition_kind)`,
    where the kind describes how THIS beat arrives."""
    out, cur = [], 0
    for beat in beats:
        name, fn, ln = beat[0], beat[1], beat[2]
        kind = beat[3] if len(beat) > 3 else "dissolve"
        out.append((cur, name, fn, ln, kind))
        cur += ln - XF
    return out, cur + XF


def run(beats, argv=None):
    global THEME, PLATES, FONTS, FONT_DIRS, BPM, BEAT_F
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default="light")
    ap.add_argument("--bpm", type=float, default=BPM,
                    help="score tempo, for pulse(); match score.py --bpm")
    ap.add_argument("--map", action="store_true",
                    help="print the beat map in frames and seconds, then exit")
    ap.add_argument("--palette", default="", help="json {theme: {KEY: [r,g,b]}}")
    ap.add_argument("--plates", default="plates", help="directory of plate dirs")
    ap.add_argument("--fonts", default="", help="extra font directory")
    ap.add_argument("--font-map", default="", help="json {role: filename}")
    ap.add_argument("--out", default="")
    ap.add_argument("--only", default="", help="render a single beat by name")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--shard", default="",
                    help="K/N: render only slice K (0-based) of N — run N at "
                         "once, one per core, into the same --out")
    args = ap.parse_args(argv)

    THEME = args.theme
    BPM = args.bpm
    BEAT_F = FPS * 60.0 / BPM
    if args.palette:
        loaded = json.load(open(args.palette))
        if THEME not in loaded:
            raise SystemExit(f"palette file has no {THEME!r} theme")
        PALETTES[THEME] = {k: tuple(v) for k, v in loaded[THEME].items()}
    if THEME not in PALETTES:
        raise SystemExit(f"no {THEME!r} palette; pass --palette")
    P.clear()
    P.update(PALETTES[THEME])
    PLATES = args.plates
    if args.fonts:
        FONT_DIRS.insert(0, args.fonts)
    if args.font_map:
        FONTS.update(json.load(open(args.font_map)))

    tl, total = timeline(beats)
    if args.map:
        for s, nm, _fn, ln, kind in tl:
            print(f"{nm:12s} {s:5d} {s / FPS:7.2f}s  len {ln:4d}  {kind}")
        print(f"{'TOTAL':12s} {total:5d} {total / FPS:7.2f}s")
        return
    out = args.out or f"frames_{THEME}"
    os.makedirs(out, exist_ok=True)
    if args.only:
        tl = [(0, nm, fn, ln, kind) for _s, nm, fn, ln, kind in tl
              if nm == args.only]
        if not tl:
            raise SystemExit(f"no beat named {args.only!r}; "
                             f"have {[b[0] for b in beats]}")
        total = tl[0][3]
    end = args.end or total
    start = args.start
    if args.shard:
        k, nsh = (int(v) for v in args.shard.split("/"))
        if not 0 <= k < nsh:
            raise SystemExit("--shard K/N needs 0 <= K < N")
        start, end = (args.start + (end - args.start) * k // nsh,
                      args.start + (end - args.start) * (k + 1) // nsh)
    print(f"[{THEME}] {total} frames = {total / FPS:.1f}s -> {out}"
          f"  (rendering {start}..{end})", flush=True)

    for g in range(start, end, args.stride):
        active = [b for b in tl if b[0] <= g < b[0] + b[3]]
        if not active:
            continue
        s0, _nm0, fn0, ln0, _k0 = active[0]
        img = fn0(g - s0, ln0, g)
        for s1, _nm1, fn1, ln1, kind in active[1:]:
            # +1 so the last overlapping frame reaches a full 1.0; without it the
            # dissolve stops at (XF-1)/XF and the next frame jumps the remainder
            img = transition(img, fn1(g - s1, ln1, g),
                             (g - s1 + 1) / float(XF), kind)
        img.convert("RGB").save(os.path.join(out, f"{g:05d}.png"),
                                compress_level=1)
        if g % 60 == 0:
            print(f"  {g}/{end}", flush=True)
    print("frames done", flush=True)
