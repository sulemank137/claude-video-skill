"""Explainer-film helpers on top of promo_kit: typeset equations, diagram nodes and edges that
draw themselves, animated bar charts with intervals, and the data-to-pixel map of a line_chart
so annotations land on the plotted values.

    from promo_kit import *
    from explain_kit import tex, node, edge, bars, chart_map
"""
import io
import math

from PIL import Image, ImageDraw, ImageFilter

import promo_kit as pk
from promo_kit import P, ease, ease_out, font, tracked_text

_tex_cache = {}


def tex(expr, px=48, colour=None):
    """A formula as an RGBA image in the given colour, typeset by matplotlib's mathtext with the
    Computer Modern set (no LaTeX install needed). `expr` is mathtext: `r"$F = m\\,a$"`.
    mathtext has no \\color and no cases/array environments: write a piecewise function as one
    expression (min/max/clip), and colour a term by drawing a mark under it (see tex_x)."""
    colour = colour or P["TEXT"]
    key = (expr, px, colour)
    if key not in _tex_cache:
        import warnings
        warnings.filterwarnings("ignore", message="Unable to import Axes3D")   # mixed pip/apt installs
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib import mathtext, rcParams
        from matplotlib.font_manager import FontProperties
        rcParams["mathtext.fontset"] = "cm"
        buf = io.BytesIO()
        # rendered black on white and turned into coverage: math_to_image paints an opaque
        # white background, so its own colour/transparency would leave a white box on the card
        mathtext.math_to_image(expr, buf, prop=FontProperties(size=px * 0.75), dpi=200, format="png")
        buf.seek(0)
        g = Image.open(buf).convert("L")
        g = g.resize((max(1, g.width // 2), max(1, g.height // 2)), Image.LANCZOS)
        a = g.point(lambda v: 255 - v)
        bbox = a.getbbox() or (0, 0, 1, 1)
        im = Image.new("RGBA", g.size, colour + (0,))
        im.putalpha(a)
        _tex_cache[key] = im.crop(bbox)
    return _tex_cache[key]


def tex_x(prefix, px=48):
    """Width of the typeset prefix (an unclosed "$..." is closed for you): where the next term
    starts inside tex(prefix + rest). Close, not exact, which is enough to mark a term."""
    return tex(prefix if prefix.endswith("$") else prefix + "$", px).width


def reveal(img, im, x, y, prog, alpha=1.0):
    """Paste `im` revealed left to right as prog runs 0 -> 1 (an equation being written)."""
    if prog <= 0.01 or alpha <= 0.01:
        return
    cut = max(1, int(im.width * min(1.0, prog)))
    part = im.crop((0, 0, cut, im.height))
    if alpha < 1.0:
        part = part.copy()
        part.putalpha(part.getchannel("A").point(lambda v: int(v * alpha)))
    img.alpha_composite(part, dest=(int(x), int(y)))


def node(img, box, title, sub=None, prog=1.0, accent=None, title_size=30, sub_size=19):
    """A diagram box that pops in (scale 0.94 -> 1 and fade) as prog runs 0 -> 1. Returns the
    box so edges can attach to its sides. Text is measured to the box, never past it."""
    if prog <= 0.01:
        return box
    accent = accent or P["ACCENT"]
    a = ease(min(1.0, prog))
    x0, y0, x1, y1 = box
    s = 0.94 + 0.06 * ease_out(min(1.0, prog))
    cx, cy, w, h = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) * s, (y1 - y0) * s
    bx = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    lay = Image.new("RGBA", (int(w) + 40, int(h) + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    d.rounded_rectangle([20, 26, 20 + w, 26 + h], 18, fill=P["SHADOW"][:3] + (int(P["SHADOW"][3] * 0.5 * a),))
    img.alpha_composite(lay.filter(ImageFilter.GaussianBlur(10)), dest=(int(bx[0] - 20), int(bx[1] - 20)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(bx, 18, fill=P["SURFACE"] + (int(250 * a),), outline=accent + (int(200 * a),), width=3)
    d.rounded_rectangle([bx[0], bx[1], bx[0] + 10, bx[3]], 6, fill=accent + (int(235 * a),))
    pad = 34
    tf = pk.fit_font("title", title, title_size, w - 2 * pad, 0.4)
    tracked_text(img, (bx[0] + pad, bx[1] + 24), title, tf, P["TEXT"], tracking=0.4, alpha=255 * a)
    if sub:
        for k, line in enumerate(sub.split("\n")):
            sf = pk.fit_font("body", line, sub_size, w - 2 * pad, 0.2)
            tracked_text(img, (bx[0] + pad, bx[1] + 32 + title_size + 8 + k * (sub_size + 9)), line, sf,
                         P["TEXT3"], tracking=0.2, alpha=235 * a)
    return box


def _polyline_upto(pts, frac):
    segs = list(zip(pts, pts[1:]))
    lens = [math.dist(a, b) for a, b in segs]
    want = sum(lens) * max(0.0, min(1.0, frac))
    out = [pts[0]]
    for (a, b), ln in zip(segs, lens):
        if want >= ln:
            out.append(b)
            want -= ln
        else:
            f = want / (ln or 1)
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
            break
    return out


def edge(img, pts, prog, g, colour=None, width=5, head=15, dashed=False, label=None, label_at=0.5,
         label_off=(0, -30), dots=True, alpha=1.0):
    """A diagram edge along polyline `pts` that draws itself as prog runs 0 -> 1, then carries
    flow dots once complete. The label rides at fraction `label_at` of the path, offset."""
    if prog <= 0.01 or alpha <= 0.01:
        return
    colour = colour or P["ACCENT"]
    A = int(235 * alpha * min(1.0, prog * 3))
    path = _polyline_upto(pts, ease_out(prog))
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    if dashed:
        for a, b in zip(path, path[1:]):
            ln = math.dist(a, b)
            for k in range(0, int(ln), 22):
                f0, f1 = k / ln, min(1.0, (k + 12) / ln)
                d.line([(a[0] + (b[0] - a[0]) * f0, a[1] + (b[1] - a[1]) * f0),
                        (a[0] + (b[0] - a[0]) * f1, a[1] + (b[1] - a[1]) * f1)], fill=colour + (A,), width=width)
    else:
        d.line(path, fill=colour + (A,), width=width, joint="curve")
    if len(path) >= 2:
        (ax, ay), (bx, by) = path[-2], path[-1]
        ang = math.atan2(by - ay, bx - ax)
        tip = (bx + math.cos(ang) * 4, by + math.sin(ang) * 4)
        d.polygon([tip, (bx - head * math.cos(ang - 0.45), by - head * math.sin(ang - 0.45)),
                   (bx - head * math.cos(ang + 0.45), by - head * math.sin(ang + 0.45))], fill=colour + (A,))
    img.alpha_composite(lay)
    if dots and prog >= 1.0 and not dashed:
        pk.flow_dots(img, pts, g, alpha=alpha, colour=colour, count=3, radius=5)
    if label:
        la = ease((prog - 0.6) / 0.4) * alpha
        if la > 0.01:
            lp = _polyline_upto(pts, label_at)[-1]
            tracked_text(img, (lp[0] + label_off[0], lp[1] + label_off[1]), label, font("mono", 19),
                         colour, tracking=0.8, anchor="mm", alpha=255 * la)


def chart_map(xs, w, h, lo, hi, title=True):
    """The data -> pixel map line_chart uses for a chart of size (w, h), so a band, a threshold
    or a marker drawn over the pasted chart lands on the plotted values. Returns f(x, y) giving
    card-relative pixels; add the card's paste position."""
    x0, y0, x1, y1 = 110, (118 if title else 50), w - 50, h - 78

    def f(x, y):
        return (x0 + (x1 - x0) * (x - xs[0]) / ((xs[-1] - xs[0]) or 1),
                y1 - (y1 - y0) * (min(hi, max(lo, y)) - lo) / ((hi - lo) or 1))
    return f


def bars(img, box, groups, prog, vmax, fmt=str, unit="", horizontal=False, gap=14, group_gap=56,
         label_size=22, value_size=22, stagger=0.08, mean=False):
    """Animated bar chart in `box` = (x0, y0, x1, y1). groups = [(name, colour, values, intervals)]
    where intervals is None or a list of (lo, hi) per value (drawn as whiskers once the bar is up).
    Bars grow in order with `stagger` of prog between them; values count up with the bar and land
    on the exact number. `mean=True` draws each group's mean as a dashed line across its bars."""
    x0, y0, x1, y1 = box
    n = sum(len(gr[2]) for gr in groups)
    ng = len(groups)
    span = (y1 - y0) if horizontal else (x1 - x0)
    bw = (span - group_gap * (ng - 1) - gap * (n - ng)) / max(1, n)
    d = ImageDraw.Draw(img)
    base = x0 if horizontal else y1
    d.line([(x0, y0), (x0, y1)] if horizontal else [(x0, y1), (x1, y1)], fill=P["BORDER"] + (255,), width=3)
    pos, k, later = (y0 if horizontal else x0), 0, []
    for name, col, vals, ivs in groups:
        g0 = pos
        for j, v in enumerate(vals):
            p = ease_out(max(0.0, min(1.0, (prog - k * stagger) / 0.45)))
            vv = v * p
            ln = (x1 - x0 if horizontal else y1 - y0) * vv / vmax
            if p > 0:
                if horizontal:
                    d.rounded_rectangle([base, pos, base + ln, pos + bw], 8, fill=col + (255,))
                else:
                    d.rounded_rectangle([pos, base - ln, pos + bw, base], 8, fill=col + (255,))
                if ivs and p >= 1.0:
                    lo, hi = ivs[j]
                    a0 = (x1 - x0 if horizontal else y1 - y0) * lo / vmax
                    a1 = (x1 - x0 if horizontal else y1 - y0) * hi / vmax
                    c = P["TEXT2"] + (255,)
                    if horizontal:
                        m = pos + bw / 2
                        d.line([(base + a0, m), (base + a1, m)], fill=c, width=3)
                        for e in (a0, a1):
                            d.line([(base + e, m - 9), (base + e, m + 9)], fill=c, width=3)
                    else:
                        m = pos + bw / 2
                        d.line([(m, base - a0), (m, base - a1)], fill=c, width=3)
                        for e in (a0, a1):
                            d.line([(m - 9, base - e), (m + 9, base - e)], fill=c, width=3)
                txt = fmt(vv if p < 1.0 else v) + unit
                vf = font("display", value_size)
                tw = d.textlength(txt, font=vf)
                if horizontal:
                    off = (x1 - x0) * (ivs[j][1] / vmax) - ln if (ivs and p >= 1.0) else 0
                    tracked_text(img, (base + ln + off + 16, pos + bw / 2), txt, vf, P["TEXT"], anchor="lm",
                                 alpha=255 * min(1.0, p * 2))
                else:                    # drawn last, on a pill, so a mean line never crosses a number
                    later.append((pos + bw / 2, base - ln - 14, txt, tw, min(1.0, p * 2)))
            pos += bw + gap
            k += 1
        pos -= gap
        la = ease(min(1.0, prog / 0.3))
        lf = font("title", label_size)
        if horizontal:
            tracked_text(img, (x0 - 18, (g0 + pos) / 2), name, lf, P["TEXT2"], anchor="rm", alpha=255 * la)
        else:
            for li, line in enumerate(name.split("\n")):
                tracked_text(img, ((g0 + pos) / 2, y1 + 18 + li * (label_size + 6)), line, lf, P["TEXT2"],
                             anchor="mt", alpha=255 * la)
        if mean and prog >= stagger * (k - 1) + 0.45:
            mv = sum(vals) / len(vals)
            ln = (x1 - x0 if horizontal else y1 - y0) * mv / vmax
            for xx in range(int(g0) - 10, int(pos) + 10, 18):
                if horizontal:
                    d.line([(base + ln, xx), (base + ln, xx + 9)], fill=P["TEXT"] + (200,), width=3)
                else:
                    d.line([(xx, base - ln), (xx + 9, base - ln)], fill=P["TEXT"] + (200,), width=3)
        pos += group_gap
    vf = font("display", value_size)
    for cx, ty, txt, tw, la in later:
        d.rounded_rectangle([cx - tw / 2 - 8, ty - value_size - 6, cx + tw / 2 + 8, ty + 6], 8,
                            fill=P["SURFACE"] + (int(235 * la),))
        tracked_text(img, (cx, ty), txt, vf, P["TEXT"], anchor="mb", alpha=255 * la)


if __name__ == "__main__":
    # self-check: each helper draws onto a frame, and chart_map lands on line_chart's plot box
    img = Image.new("RGBA", (pk.W, pk.H), P["BG"] + (255,))
    eq = tex(r"$E = m c^2$", 60)
    assert eq.mode == "RGBA" and eq.getchannel("A").getextrema()[1] > 200, "tex drew nothing"
    assert 0 < tex_x(r"$E = ", 60) < eq.width
    node(img, (100, 100, 500, 260), "NODE", "a sub line", 1.0)
    edge(img, [(500, 180), (800, 180), (800, 400)], 1.0, 0, label="EDGE")
    bars(img, (200, 500, 1000, 900), [("A", (90, 90, 90), [3, 4], None),
                                      ("B", (230, 100, 50), [1, 2], [(0.5, 1.5), (1.5, 2.5)])], 1.0, 5, mean=True)
    bars(img, (1200, 500, 1800, 900), [("C", (90, 90, 90), [3], [(2, 4)])], 1.0, 5, horizontal=True)
    m = chart_map([0, 10], 800, 400, 0, 1)
    assert m(0, 0) == (110, 322) and m(10, 1) == (750, 118), (m(0, 0), m(10, 1))
    print("ok")
