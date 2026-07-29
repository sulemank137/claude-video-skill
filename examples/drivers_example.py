"""Driver examples for capture_ui.py — the hook that makes a captured UI move.

The rule that matters: push the app through the entry points it already has
(the stdout its subprocesses print, the dicts its data readers emit, the store
actions the frontend dispatches) instead of setting label text. Then the capture
cannot disagree with the shipping product, and progress bars, counters and
charts animate for free.

    capture_ui.py --backend qt --factory myapp:build_window \
        --setup drivers_example:qt_setup --driver drivers_example:qt_tick ...
"""
import math


# ── Qt ────────────────────────────────────────────────────────────────────────

def qt_setup(ctx):
    """Runs once. Put the app in the state the beat is about — and silence the
    background readers that would otherwise overwrite it."""
    win = ctx.window
    _quiet(win)
    # e.g. win.on_process_status("WORKER", "running")
    # e.g. win.on_process_output("WORKER", "MODE=LIVE\nengaged\n")


def qt_tick(ctx, t, i):
    """Runs every frame. `t` goes 0→1 across the capture.

    Values move monotonically on purpose: a panel whose numbers jitter frame to
    frame reads as a stack of screenshots, not as live telemetry."""
    win = ctx.window
    _quiet(win)                       # EVERY frame — see the note in _quiet
    temp = 48 + 14 * t
    win.on_telemetry({"link": "LIVE", "soc": 76 - 4 * t, "voltage": 55.6,
                      "current": 6.4, "max_temp": temp,
                      "hottest": [("left_knee", temp)], "faults": []})


def _quiet(win):
    """Stop the app's own data readers.

    They are the authority when hardware is attached; in a capture there is
    none, so they publish "offline / 0 Hz" and stomp the state you inject
    between grabs — on screen, a panel flickering every other frame.

    Called per frame, not once: if the app armed its starter with
    `QTimer.singleShot(300, self._ensure_reader)`, that timer captured the BOUND
    method before your stub existed and will resurrect the reader ~300 ms in.
    """
    win._ensure_reader = lambda: None          # rename to your app's starter
    reader = getattr(win, "_reader", None)
    if reader is not None:
        try:
            reader.stop()
        except Exception:
            pass
        win._reader = None


def qt_tick_chart(ctx, t, i):
    """Feeding a rolling chart.

    Most chart widgets drop any point whose x is ≤ the last one, so timestamps
    must march forward ACROSS frames — a per-frame back-fill of the whole window
    silently does nothing — and any other producer stamping at the wall clock
    will park itself ahead of you and reject everything. Stop it, clear the
    curve, then spread your points across the chart's window so the line spans
    it instead of spiking at "now".
    """
    span, state = 118.0, ctx.__dict__.setdefault("_chart", {})
    if not state:
        import time
        state["t0"] = time.time() - span
        state["u"] = 0.0
    prev, steps = state["u"], 8
    for k in range(1, steps + 1):
        u = prev + (t - prev) * k / steps
        ctx.window.chart.add_point(state["t0"] + span * u,
                                   30.0 * min(1.0, u * 3) + 0.4 * math.sin(u * 30))
    state["u"] = t


# ── web / Electron ────────────────────────────────────────────────────────────

def web_setup(ctx):
    """Same idea through the page: dispatch into the app's own store, or stub
    the poller that would overwrite it."""
    ctx.page.evaluate("""() => {
        window.__capture = true;               // your app can honour this
        if (window.store) window.store.dispatch({type: 'session/start'});
    }""")


def web_tick(ctx, t, i):
    ctx.page.evaluate("""(t) => {
        if (window.store) {
            window.store.dispatch({type: 'telemetry/set', payload: {
                link: 'LIVE', battery: 76 - 4 * t, temp: 48 + 14 * t,
            }});
        }
    }""", t)
