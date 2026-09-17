#!/usr/bin/env python3
"""Capture a UI as a PNG frame sequence, without recording anyone's screen.

Three backends, one contract: each writes `out/00000.png …` at the size you ask
for, and calls your driver once per frame so the UI is in a real, changing state
while it is being grabbed.

    # a Qt (PyQt5/6, PySide2/6) desktop app, offscreen
    capture_ui.py --backend qt --factory myapp.main:build_window \
        --frames 200 --size 1920x1080 --scale 1.25 --out plates/app

    # one widget of that app, whole, at 2x
    capture_ui.py --backend qt --factory myapp.main:build_window \
        --widget "text:ROBOT HEALTH" --scale 2 --frames 190 --out plates/health

    # a web app or an Electron renderer, headless Chromium
    capture_ui.py --backend web --url http://localhost:3000 \
        --selector "#health-card" --scale 2 --frames 190 --out plates/health

    # anything else, from a real X display (Xvfb or a spare one)
    capture_ui.py --backend x11 --display :99 --region 0,0,1920,1080 \
        --frames 200 --out plates/app

`--driver module:function` is the hook that makes the UI move. It is called as
`fn(ctx, t, i)` where `t` runs 0→1 across the capture; `--setup module:function`
runs once before the first frame. `ctx` carries the backend name and whatever
that backend exposes (`ctx.window` / `ctx.app` for Qt, `ctx.page` for web), so a
driver can push the app through its OWN entry points rather than faking labels.
"""
import argparse
import importlib
import os
import subprocess
import sys
import time


class Ctx:
    """What a driver gets. Backend-specific handles are attached as attributes."""

    def __init__(self, backend, **kw):
        self.backend = backend
        self.frame = 0
        for k, v in kw.items():
            setattr(self, k, v)


def load_callable(spec):
    """'package.module:attribute' → the attribute."""
    if not spec:
        return None
    if ":" not in spec:
        raise SystemExit(f"--driver/--setup/--factory want module:attr, got {spec!r}")
    mod, attr = spec.split(":", 1)
    sys.path.insert(0, os.getcwd())
    return getattr(importlib.import_module(mod), attr)


def parse_size(s):
    w, h = s.lower().split("x")
    return int(w), int(h)


# ── Qt ────────────────────────────────────────────────────────────────────────

def find_qt_widget(window, spec):
    """Locate a sub-widget to grab.

    `attr:_hand_preview`  — an attribute of the window
    `name:healthCard`     — objectName
    `class:QGroupBox`     — first widget of that class
    `text:ROBOT HEALTH`   — the panel whose header label carries this text; the
                            match ignores case and non-alphanumerics, because UI
                            titles carry padding spaces and go through i18n
    """
    kind, _, value = spec.partition(":")
    if not value:
        kind, value = "text", spec

    if kind == "attr":
        w = getattr(window, value, None)
        if w is None:
            raise SystemExit(f"no attribute {value!r} on the window")
        return w

    QtWidgets = _qt_widgets()
    widgets = window.findChildren(QtWidgets.QWidget)

    if kind == "name":
        for w in widgets:
            if w.objectName() == value:
                return w
        raise SystemExit(f"no widget with objectName {value!r}")

    if kind == "class":
        for w in widgets:
            if type(w).__name__ == value:
                return w
        raise SystemExit(f"no widget of class {value!r}")

    if kind == "text":
        QLabel = _qt_widgets().QLabel
        key = lambda s: "".join(c for c in s.upper() if c.isalnum())
        want = key(value)
        for lab in window.findChildren(QLabel):
            if key(lab.text()) != want:
                continue
            # climb to the panel that owns the header: the first ancestor that is
            # meaningfully bigger than the label itself
            w = lab.parentWidget()
            while w is not None and w is not window:
                if w.width() > lab.width() * 1.5 or w.height() > lab.height() * 2:
                    return w
                w = w.parentWidget()
            return lab.parentWidget() or lab
        raise SystemExit(f"no panel whose header reads {value!r}")

    raise SystemExit(f"unknown --widget selector kind {kind!r}")


def _qt_widgets():
    for mod in ("PyQt6.QtWidgets", "PySide6.QtWidgets",
                "PyQt5.QtWidgets", "PySide2.QtWidgets"):
        try:
            return importlib.import_module(mod)
        except ImportError:
            continue
    raise SystemExit("no Qt binding found (PyQt6 / PySide6 / PyQt5 / PySide2)")


def capture_qt(args, driver, setup):
    # both must be set before the QApplication exists
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if args.scale != 1.0:
        os.environ["QT_SCALE_FACTOR"] = str(args.scale)

    QtWidgets = _qt_widgets()
    factory = load_callable(args.factory)
    if factory is None:
        raise SystemExit("--backend qt needs --factory module:function")

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    made = factory()
    window = made[1] if isinstance(made, tuple) else made
    w, h = parse_size(args.size)
    window.resize(w, h)
    window.show()

    ctx = Ctx("qt", app=app, window=window)
    if setup:
        setup(ctx)

    target = find_qt_widget(window, args.widget) if args.widget else window

    def pump(seconds):
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.005)

    pump(args.warmup)
    os.makedirs(args.out, exist_ok=True)
    for i in range(args.frames):
        ctx.frame = i
        if driver:
            driver(ctx, i / max(1, args.frames - 1), i)
        pump(1.0 / args.fps)
        target.grab().save(os.path.join(args.out, f"{i:05d}.png"))
        if i % 30 == 0:
            print(f"  {i}/{args.frames}", flush=True)
    print(f"qt -> {args.out}", flush=True)
    sys.stdout.flush()
    # background threads an app started (readers, render loops) keep Qt alive
    os._exit(0)


# ── web / Electron renderer ───────────────────────────────────────────────────

def capture_web(args, driver, setup):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("--backend web needs playwright: pip install playwright "
                         "&& playwright install chromium")
    if not args.url:
        raise SystemExit("--backend web needs --url (file:// works)")

    w, h = parse_size(args.size)
    os.makedirs(args.out, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--force-color-profile=srgb"])
        page = browser.new_page(viewport={"width": w, "height": h},
                                device_scale_factor=args.scale)
        page.goto(args.url, wait_until="networkidle")
        ctx = Ctx("web", page=page, browser=browser)
        if setup:
            setup(ctx)
        page.wait_for_timeout(int(args.warmup * 1000))

        target = page.locator(args.selector) if args.selector else page
        for i in range(args.frames):
            ctx.frame = i
            if driver:
                driver(ctx, i / max(1, args.frames - 1), i)
            page.wait_for_timeout(int(1000 / args.fps))
            target.screenshot(path=os.path.join(args.out, f"{i:05d}.png"))
            if i % 30 == 0:
                print(f"  {i}/{args.frames}", flush=True)
        browser.close()
    print(f"web -> {args.out}", flush=True)


# ── any X11 window (GTK, Electron shell, a game, a native app) ────────────────

def capture_x11(args, driver, setup):
    """Grab a region of an X display with ffmpeg.

    Unlike the other two backends this one cannot step the UI frame by frame —
    ffmpeg owns the clock. So `--setup` arranges the window before the grab, and
    `--driver` is called ONCE, after the first frame has landed, to start the
    action (play the animation, open the page, start the demo). Triggered before
    the grab, the opening of the action is already over by the first frame.
    Run the app under Xvfb (`Xvfb :99 -screen 0 1920x1080x24`) for a clean,
    fixed-size, invisible display.

    The cursor is never drawn. For a GL window (a 3D viewer, a game engine, a
    CAD or map view — anything on GLFW) drive it with XTEST — `xdotool key` /
    `click` with no `--window` — after `windowactivate`: `--window` sends
    synthetic events, and GLFW drops them without a word.
    """
    if not args.region:
        raise SystemExit("--backend x11 needs --region x,y,w,h")
    x, y, w, h = (int(v) for v in args.region.split(","))
    ctx = Ctx("x11", display=args.display)
    if setup:
        setup(ctx)
    os.makedirs(args.out, exist_ok=True)
    first = os.path.join(args.out, "00000.png")
    if os.path.exists(first):                 # a stale frame would fire the
        os.remove(first)                      # driver before the grab began
    cmd = ["ffmpeg", "-v", "error", "-f", "x11grab", "-draw_mouse", "0",
           "-framerate", str(args.fps),
           "-video_size", f"{w}x{h}", "-i", f"{args.display}+{x},{y}",
           "-frames:v", str(args.frames), "-start_number", "0",
           os.path.join(args.out, "%05d.png"), "-y"]
    proc = subprocess.Popen(cmd)
    if driver:
        t0 = time.time()
        while (not os.path.exists(first) and proc.poll() is None
               and time.time() - t0 < 15):
            time.sleep(0.05)
        driver(ctx, 0.0, 0)
    if proc.wait() != 0:
        raise SystemExit(f"ffmpeg exited {proc.returncode}")
    print(f"x11 -> {args.out}", flush=True)


BACKENDS = {"qt": capture_qt, "web": capture_web, "x11": capture_x11}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", required=True, choices=sorted(BACKENDS))
    ap.add_argument("--out", required=True)
    ap.add_argument("--frames", type=int, default=150)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--size", default="1920x1080",
                    help="logical window/viewport size, WxH (default 1920x1080 "
                         "— capture at DISPLAY aspect, not at the app's natural "
                         "shape, or the cut looks like a phone screenshot)")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="device pixel ratio; 2 keeps type crisp when the cut "
                         "blows a panel up")
    ap.add_argument("--warmup", type=float, default=2.0,
                    help="seconds to let the UI settle before the first frame")
    ap.add_argument("--driver", default="", help="module:fn called as fn(ctx, t, i)")
    ap.add_argument("--setup", default="", help="module:fn called once as fn(ctx)")
    # qt
    ap.add_argument("--factory", default="",
                    help="qt: module:fn returning the window (or (app, window))")
    ap.add_argument("--widget", default="",
                    help="qt: grab one panel — attr:/name:/class:/text: selector")
    # web
    ap.add_argument("--url", default="", help="web: page to open (file:// ok)")
    ap.add_argument("--selector", default="", help="web: CSS selector to grab")
    # x11
    ap.add_argument("--display", default=os.environ.get("DISPLAY", ":0"))
    ap.add_argument("--region", default="", help="x11: x,y,w,h")
    args = ap.parse_args()

    BACKENDS[args.backend](args, load_callable(args.driver),
                           load_callable(args.setup))


if __name__ == "__main__":
    main()
