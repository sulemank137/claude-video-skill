#!/usr/bin/env python3
"""Generic screen-capture -> promo-video builder (ffmpeg filter_complex generator + renderer).

Takes a JSON config describing a sequence of source clips (each optionally
cropped to a region of interest with a "push-in" reveal), animated lower-third
captions, crossfades, and a closing card — and renders a single HD mp4.

Run: python3 build_promo.py config.json [--filter-only]

--filter-only writes the generated filter_complex script next to the config
and skips the ffmpeg render (useful for inspecting/debugging the graph).

See ../SKILL.md for the full method, the config schema, and — importantly —
the pitfalls this script already avoids (aspect-ratio distortion, the
overlapping-source-trim duration bug, starting shots pre-zoomed).
"""
import argparse
import json
import os
import subprocess
import sys

DEFAULT_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def esc(s):
    return s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def spaced(s):
    """Letter-space a short kicker label: 'DATA CAPTURE' -> 'D A T A   C A P T U R E'."""
    return " ".join(list(s))


def fit_crop_to_aspect(x, y, w, h, out_w, out_h, src_w, src_h):
    """Recompute (x,y,w,h) to exactly match out_w:out_h, centered on the same
    ROI center, clamped inside the source frame.

    This is the fix for the #1 recurring bug in these edits: a crop box whose
    aspect ratio doesn't match the output and gets forced to fit via
    force_original_aspect_ratio=disable, which STRETCHES the image (warped
    UI text, distorted robot proportions). Never use that flag on a crop.
    Either letterbox (pad) or — better, what this does — re-fit the crop
    itself to the exact target ratio so no padding or stretching is needed.
    """
    target_ratio = out_w / out_h
    cur_ratio = w / h
    cx, cy = x + w / 2.0, y + h / 2.0
    if cur_ratio > target_ratio:
        new_h = h
        new_w = h * target_ratio
    else:
        new_w = w
        new_h = w / target_ratio
    nx = cx - new_w / 2.0
    ny = cy - new_h / 2.0
    nx = max(0, min(nx, src_w - new_w))
    ny = max(0, min(ny, src_h - new_h))
    return round(nx), round(ny), round(new_w), round(new_h)


def ease_exprs(dur, ein, eout):
    """Ease-out-cubic alpha (fade in, hold, fade out) + a slide-distance
    expression for lower-third captions. All in terms of the clip's own
    relative time `t` (valid because every clip is setpts=PTS-STARTPTS'd)."""
    xin = f"min(max(t/{ein}\\,0)\\,1)"
    ease_in = f"(1-pow(1-{xin}\\,3))"
    xout = f"min(max((t-({dur}-{eout}))/{eout}\\,0)\\,1)"
    ease_out = f"(1-pow(1-{xout}\\,3))"
    alpha = f"({ease_in}*(1-{ease_out}))"
    slide = f"((1-{ease_in})*SLIDE)"
    return alpha, slide


def push_in_zoompan(crop, d, W, H, scale, fps):
    """The 'first show whole screen, then zoom in' reveal.

    Naive Ken-Burns (crop first, then zoompan a mild 1.0->1.1 *inside* the
    crop) starts every shot already tight — it never shows the wide
    establishing view, which reads as abrupt/disorienting. This instead
    zoompans the FULL frame, animating BOTH the zoom level (1.0 -> z_end)
    AND the view center (frame-center -> ROI-center) together, so at t=0 the
    whole screen is visible and at t=dur the view exactly fills the ROI.

    Uses zoompan's `on` (output frame index) for progress instead of `t`,
    since it's the value zoompan documents/guarantees is available.
    """
    x, y, w, h = crop
    roi_cx, roi_cy = x + w / 2.0, y + h / 2.0
    full_cx, full_cy = W / 2.0, H / 2.0
    z_end = round(W / w, 5)
    nframes = max(int(round(d * fps)), 2)
    prog = f"min(on/{nframes - 1},1)"
    ease = f"(1-pow(1-{prog},3))"
    zoom_e = f"(1+({z_end}-1)*{ease})"
    ccx = f"({full_cx}+({roi_cx}-{full_cx})*{ease})"
    ccy = f"({full_cy}+({roi_cy}-{full_cy})*{ease})"
    x_e = f"({ccx}*{scale}-(iw/zoom/2))"
    y_e = f"({ccy}*{scale}-(ih/zoom/2))"
    return (
        f"scale={W*scale}:{H*scale},"
        f"zoompan=z='{zoom_e}':x='{x_e}':y='{y_e}':d=1:s={W}x{H}:fps={fps},"
    )


def build(cfg):
    W = cfg.get("width", 1920)
    H = cfg.get("height", 1080)
    FPS = cfg.get("fps", 30)
    FONT = cfg.get("font", DEFAULT_FONT)
    ACCENT = cfg.get("accent", "0xE0A94B")
    XF = cfg.get("crossfade", 0.3)
    EIN = cfg.get("caption_ease_in", 0.35)
    EOUT = cfg.get("caption_ease_out", 0.3)
    SCALE = cfg.get("push_in_scale", 3)
    src_w = cfg.get("source_width", W)
    src_h = cfg.get("source_height", H)

    lines = []
    clip_labels = []
    clip_durs = []
    used_ranges = []  # for the overlap-safety check, see below

    def check_overlap(s, e, tag):
        for (os_, oe, otag) in used_ranges:
            if s < oe and os_ < e:
                print(
                    f"WARNING: segment '{tag}' [{s},{e}] overlaps '{otag}' [{os_},{oe}] "
                    f"in SOURCE time. Two [0:v] branches feeding the same xfade chain "
                    f"with overlapping source ranges corrupts xfade's duration tracking "
                    f"(confirmed ffmpeg bug, see SKILL.md). Pick a disjoint time range.",
                    file=sys.stderr,
                )
        used_ranges.append((s, e, tag))

    segments = cfg["segments"]
    for i, seg in enumerate(segments):
        s, e = seg["start"], seg["end"]
        tag = f"c{i}"
        check_overlap(s, e, tag)
        d = round(e - s, 3)
        chain = f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS,"

        crop = seg.get("crop")
        if crop:
            crop = fit_crop_to_aspect(*crop, W, H, src_w, src_h)
            style = seg.get("style", "push_in")
            if style == "push_in":
                chain += push_in_zoompan(crop, d, W, H, SCALE, FPS)
            elif style == "static_zoom":
                x, y, w, h = crop
                target_zoom = seg.get("zoom", 1.08)
                nframes = max(int(round(d * FPS)), 1)
                step = round((target_zoom - 1.0) / nframes, 6)
                chain += (
                    f"crop={w}:{h}:{x}:{y},scale={W}:{H},fps={FPS},"
                    f"scale={W*2}:{H*2},"
                    f"zoompan=z='min(zoom+{step},{target_zoom})':"
                    f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},"
                )
            else:  # static crop, no motion
                x, y, w, h = crop
                chain += f"crop={w}:{h}:{x}:{y},scale={W}:{H},fps={FPS},"
        else:
            chain += f"scale={W}:{H},fps={FPS},"
        chain += "format=yuv420p"

        if seg.get("title"):
            alpha, slide = ease_exprs(d, EIN, EOUT)
            alpha_e = alpha
            slide_e = slide.replace("SLIDE", "30")
            barw = alpha  # reuse same envelope shape, scaled below
            chain += f",drawbox=x=0:y=776:w={W}:h=304:color=black@0.42:t=fill"
            chain += f",drawbox=x=90:y=846:w='({barw}*260)':h=3:color={ACCENT}@0.95:t=fill"
            if seg.get("kicker"):
                chain += (
                    f",drawtext=fontfile={FONT}:text='{esc(spaced(seg['kicker']))}':"
                    f"x=90:y='818+{slide_e}':fontsize=21:fontcolor={ACCENT}:alpha='{alpha_e}'"
                )
            chain += (
                f",drawtext=fontfile={FONT}:text='{esc(seg['title'])}':"
                f"x=90:y='858+{slide_e}':fontsize=44:fontcolor=white:alpha='{alpha_e}'"
            )
        chain += f"[{tag}]"
        lines.append(chain)
        clip_labels.append(tag)
        clip_durs.append(d)

    # ---- Closing card ----
    if cfg.get("closing"):
        cl = cfg["closing"]
        check_overlap(cl["start"], cl["end"], "closing")
        close_dur = cl.get("hold", 3.6)
        real_dur = round(cl["end"] - cl["start"], 3)
        ce_alpha, ce_slide = ease_exprs(close_dur, 0.5, 0.4)
        title_slide = ce_slide.replace("SLIDE", "24")
        sub_delay = 0.18
        xin_sub = f"min(max((t-{sub_delay})/0.5\\,0)\\,1)"
        ease_sub = f"(1-pow(1-{xin_sub}\\,3))"
        xout_sub = f"min(max((t-({close_dur}-0.4))/0.4\\,0)\\,1)"
        easeout_sub = f"(1-pow(1-{xout_sub}\\,3))"
        alpha_sub = f"({ease_sub}*(1-{easeout_sub}))"
        slide_sub = f"((1-{ease_sub})*18)"
        closing = (
            f"[0:v]trim=start={cl['start']}:end={cl['end']},setpts=PTS-STARTPTS,"
            f"tpad=stop_mode=clone:stop_duration={round(close_dur - real_dur, 3)},"
            f"scale={W}:{H},fps={FPS},boxblur=6:1,eq=brightness=-0.12:saturation=0.9,format=yuv420p,"
            f"drawbox=x=0:y=0:w={W}:h={H}:color=black@0.2:t=fill,"
            f"drawtext=fontfile={FONT}:text='{esc(cl.get('title', ''))}':"
            f"x=(w-text_w)/2:y='(h/2)-50+{title_slide}':fontsize=64:fontcolor=white:alpha='{ce_alpha}',"
            f"drawtext=fontfile={FONT}:text='{esc(cl.get('subtitle', ''))}':"
            f"x=(w-text_w)/2:y='(h/2)+34+{slide_sub}':fontsize=28:fontcolor={ACCENT}:alpha='{alpha_sub}'"
            f"[closing]"
        )
        lines.append(closing)
        clip_labels.append("closing")
        clip_durs.append(close_dur)

    # ---- Crossfade chain ----
    running = clip_durs[0]
    prev = clip_labels[0]
    for i in range(1, len(clip_labels)):
        d_i = clip_durs[i]
        cur = clip_labels[i]
        outtag = f"x{i}" if i < len(clip_labels) - 1 else "outv"
        offset = round(running - XF, 3)
        lines.append(f"[{prev}][{cur}]xfade=transition=fade:duration={XF}:offset={offset}[{outtag}]")
        running = round(running + d_i - XF, 3)
        prev = outtag

    return ";\n".join(lines) + "\n", round(running, 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--filter-only", action="store_true")
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)

    script, total = build(cfg)
    filter_path = os.path.splitext(args.config)[0] + ".filter.txt"
    with open(filter_path, "w") as f:
        f.write(script)
    print(f"filter graph written: {filter_path}")
    print(f"expected total duration: {total}s")

    if args.filter_only:
        return

    src = cfg["source"]
    out = cfg["output"]
    crf = cfg.get("crf", 16)
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-filter_complex_script", filter_path,
        "-map", "[outv]",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        out,
    ]
    print("running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"rendered: {out}")


if __name__ == "__main__":
    main()
