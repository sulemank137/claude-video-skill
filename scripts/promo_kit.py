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

Palettes are yours: `--palette my_theme.json` loads {"light": {...}, "dark":
{...}} with the keys below, so the film can carry the product's own colours.
"""
import argparse
import json
import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

__all__ = [
    "W", "H", "FPS", "XF", "P", "THEME", "ease", "ease_out", "fade",
    "background", "tracked_text", "paste_card", "plate", "card", "caption",
    "chip", "wordmark", "font", "seq", "frame_at", "run",
]

W, H = 1920, 1080
FPS = 30
XF = 12                                   # dissolve length between beats, frames

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

P = PALETTES["light"]
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


def frame_at(name, i):
    files = seq(name)
    p = files[max(0, min(len(files) - 1, int(i)))]
    if p not in _img_cache:
        if len(_img_cache) > 40:               # plates are big; cap the cache
            _img_cache.clear()
        _img_cache[p] = Image.open(p).convert("RGBA")
    return _img_cache[p]


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

def tracked_text(img, xy, text, fnt, fill, tracking=0, anchor="lt", alpha=255):
    """PIL has no letter-spacing, and display type needs it."""
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
    for ch, wd in zip(text, widths):
        ld.text((cx, y), ch, font=fnt, fill=fill + (int(alpha),))
        cx += wd + tracking
    img.alpha_composite(layer)
    return total


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


def plate(name, i, width=None, height=None, box=None, zoom=1.0):
    """One frame of a plate, optionally cropped, zoomed and scaled."""
    im = frame_at(name, i)
    if box:
        im = im.crop(box)
    if zoom != 1.0:
        z = im.resize((int(im.width * zoom), int(im.height * zoom)), Image.LANCZOS)
        l, t = (z.width - im.width) // 2, (z.height - im.height) // 2
        im = z.crop((l, t, l + im.width, t + im.height))
    if width:
        height = height or int(im.height * width / im.width)
        im = im.resize((width, height), Image.LANCZOS)
    elif height:
        im = im.resize((int(im.width * height / im.height), height), Image.LANCZOS)
    return im


def card(img, name, i, x, y, width, alpha=1.0, radius=14, slide=0, box=None):
    """Paste a plate frame as a card; returns its height so the next one can
    stack under it."""
    p = plate(name, i, width=width, box=box)
    paste_card(img, p, x + slide, y, radius=radius, alpha=alpha)
    return p.height


def caption(img, t, title, sub=None, x=120, y=880, colour=None, size=52):
    """Lower third: a rule that wipes out, then the line rising under it.
    Keep `y` at 930 or less when there is a subtitle — 1080 comes fast."""
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
    for k, line in enumerate(lines):
        tracked_text(img, (x, y + rise + k * int(size * 1.18)), line,
                     font("title", size), P["TEXT"], tracking=0.5, alpha=255 * a)
    if sub:
        tracked_text(img, (x, y + int(size * 1.18) * (len(lines) - 1) + size + 20
                           + rise), sub, font("body", 26), P["TEXT3"],
                     tracking=2.4, alpha=225 * a)


def chip(img, x, y, text, colour=None, alpha=1.0, size=24, mono=True):
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
    img.alpha_composite(box, dest=(int(x), int(y)))
    return box.width


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


# ── timeline + CLI ────────────────────────────────────────────────────────────

def timeline(beats):
    """(start, name, fn, length) per beat, overlapping by XF so cuts dissolve."""
    out, cur = [], 0
    for name, fn, ln in beats:
        out.append((cur, name, fn, ln))
        cur += ln - XF
    return out, cur + XF


def run(beats, argv=None):
    global P, THEME, PLATES, FONTS, FONT_DIRS
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default="light")
    ap.add_argument("--palette", default="", help="json {theme: {KEY: [r,g,b]}}")
    ap.add_argument("--plates", default="plates", help="directory of plate dirs")
    ap.add_argument("--fonts", default="", help="extra font directory")
    ap.add_argument("--font-map", default="", help="json {role: filename}")
    ap.add_argument("--out", default="")
    ap.add_argument("--only", default="", help="render a single beat by name")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    ap.add_argument("--stride", type=int, default=1)
    args = ap.parse_args(argv)

    THEME = args.theme
    if args.palette:
        loaded = json.load(open(args.palette))
        if THEME not in loaded:
            raise SystemExit(f"palette file has no {THEME!r} theme")
        PALETTES[THEME] = {k: tuple(v) for k, v in loaded[THEME].items()}
    P = PALETTES[THEME]
    PLATES = args.plates
    if args.fonts:
        FONT_DIRS.insert(0, args.fonts)
    if args.font_map:
        FONTS.update(json.load(open(args.font_map)))

    out = args.out or f"frames_{THEME}"
    os.makedirs(out, exist_ok=True)
    tl, total = timeline(beats)
    if args.only:
        tl = [(0, nm, fn, ln) for nm, fn, ln in beats if nm == args.only]
        if not tl:
            raise SystemExit(f"no beat named {args.only!r}; "
                             f"have {[b[0] for b in beats]}")
        total = tl[0][3]
    end = args.end or total
    print(f"[{THEME}] {total} frames = {total / FPS:.1f}s -> {out}", flush=True)

    for g in range(args.start, end, args.stride):
        active = [(s, fn, ln) for s, _nm, fn, ln in tl if s <= g < s + ln]
        if not active:
            continue
        img = None
        for s, fn, ln in active:
            i = g - s
            f = fn(i, ln, g)
            img = f if img is None else Image.blend(img, f, ease(i / XF))
        img.convert("RGB").save(os.path.join(out, f"{g:05d}.png"),
                                compress_level=1)
        if g % 60 == 0:
            print(f"  {g}/{end}", flush=True)
    print("frames done", flush=True)
