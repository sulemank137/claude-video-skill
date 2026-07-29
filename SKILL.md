---
name: claude-video-skill
description: >
  Build a short HD product film two ways: cut one from an existing screen
  recording with ffmpeg, or — when no usable recording exists — compose it frame
  by frame from offscreen captures of the real UI (Qt, web/Electron, or any X11
  window) plus real camera footage. Covers auditing footage for dynamic moments,
  aspect-correct crops and push-ins, animated lower thirds, crossfades, light and
  dark cuts from one compositor, and a numeric check that a captured UI panel is
  animating rather than flickering. Use when asked to make a promo/teaser/demo
  video, cut a highlight reel, film a product "without screen capture", or fix
  pacing, zoom, aspect-ratio, caption or flickering-UI problems in an edit.
---

# claude-video-skill

Two ways to make a ~60 s product film, no paid tools and no MCP:

* **Mode A — cut a recording.** ffmpeg `filter_complex`, driven by
  `scripts/build_promo.py`. Use it when a recording already contains the shots.
* **Mode B — compose the film.** Frames built in PIL (`scripts/promo_kit.py`)
  from plates: offscreen captures of the real UI (`scripts/capture_ui.py`) and
  cuts of real footage (`scripts/plates.py`). Use it when there is no usable
  recording, when the UI has moved on since the last one, or when the film has
  to show the product exactly as it ships today.

Mode B is also the answer when a Mode A cut keeps failing on "the UI is stale /
that page doesn't exist any more".

**Read this whole file before cutting a film.** Every pitfall below was hit in
production and cost a full redo — none of them are hypothetical.
## Workflow (do these in order)

### 1. Probe the source
```
ffprobe -v error -show_entries format=duration -show_entries stream=width,height,r_frame_rate \
  -of default=noprint_wrappers=1 SRC.mp4
```
Screen recordings are frequently variable-frame-rate (e.g. `r_frame_rate=1000/1`)
and odd dimensions (e.g. `1922x1077`). Always normalize with `fps=30` (or your
target) inside the filter chain and scale to an exact even output size — never
assume the source is clean CFR 1920x1080.

### 2. Audit the footage — do not skip this
Use `scripts/contact_sheet.py` to tile frames across the timeline and **look
at them** before picking any timestamp:
```
python3 scripts/contact_sheet.py SRC.mp4 --start 0 --end 60 --step 2 --out sheet1.jpg
```
Then read the resulting jpg. Repeat over the full runtime, denser (`--step
0.5`–`1`) around anything that looks promising.

**Why this matters:** the single biggest failure mode in these edits is
picking "meaningless" content — idle forms, empty state ("no data yet"),
`STOPPED` buttons, warning banners, dropdown menus mid-click. All of this
looks fine in a script/outline but reads as dead/unfinished on screen. The
actual dynamic, cinematic moments (a robot mid-motion, hands reaching toward
camera, a dashboard mid-populate) are usually just a few seconds away from
the boring ones and are easy to miss without literally looking at tiled
frames first. Re-scan aggressively — the first pass is very often wrong.

Sort timestamps **numerically** when eyeballing a tiled sheet, not by
filename string — `"8.3"` sorts after `"22.1"` lexically. `contact_sheet.py`
handles this for you; if you tile frames some other way, watch for it.

### 3. Pick disjoint, exact-aspect crops
For each shot you want to highlight, note the ROI as `(x, y, w, h)` in source
pixel coordinates. Don't worry about hitting the exact output aspect ratio by
hand — `build_promo.py`'s `fit_crop_to_aspect()` re-fits every crop box to
the exact output ratio automatically, centered on your ROI. **Never** scale a
crop with `force_original_aspect_ratio=disable` — that stretches the image
(warped UI text, distorted proportions) and was the #1 visible defect in the
first few attempts of this workflow.

### 4. Write a config and generate
See `scripts/build_promo.py`'s config schema (below). Then:
```
python3 scripts/build_promo.py config.json          # generates + renders
python3 scripts/build_promo.py config.json --filter-only   # just the graph, for inspection
```

### 5. Verify by re-extracting frames from the OUTPUT
Never trust the encode log alone. After rendering:
```
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1 OUT.mp4
```
and confirm it matches the generator's printed "expected total duration"
**exactly**. If it doesn't, stop and read the pitfall below before doing
anything else — a mismatch here means the file is silently broken even
though ffmpeg exited 0 with no errors. Then pull a few frames from the
output itself (not the source) to confirm crops aren't distorted, captions
render, and cuts land where intended.

## Config schema (`build_promo.py`)

```jsonc
{
  "source": "/path/to/raw.webm",
  "output": "/path/to/promo.mp4",
  "source_width": 1920, "source_height": 1080,   // for crop clamping
  "width": 1920, "height": 1080, "fps": 30,
  "accent": "0xE0A94B",                           // MUST be a string, not a bare hex int (see pitfall)
  "crossfade": 0.3,
  "segments": [
    {"start": 6.2, "end": 11.0, "crop": null},    // no crop/caption = plain full-frame shot (e.g. a branded intro)
    {
      "start": 42.0, "end": 45.5,
      "crop": [180, 140, 1000, 563],              // [x, y, w, h] in SOURCE pixels, any aspect — auto-fitted
      "style": "push_in",                          // default; "static_zoom" or "none" also available
      "kicker": "DIGITAL TWIN",                    // small letter-spaced label
      "title": "Real-Time Teleoperation, 34-DOF"   // main caption line
    }
  ],
  "closing": {
    "start": 147.3, "end": 148.0,                 // a short still moment to freeze — MUST be disjoint from every segment above
    "hold": 3.6,                                   // total closing-card duration after freezing
    "title": "WEGO HUMANOID STUDIO",
    "subtitle": "The Complete End-to-End Humanoid Physical AI Platform"
  }
}
```

Every `segments[].{start,end}` and `closing.{start,end}` must be a **disjoint**
window of source time — see the overlap pitfall below. The script prints a
warning if it detects two windows overlapping; don't ignore it.

## Pitfalls (all hit for real — read before you improvise around this script)

### Overlapping source-time trims silently corrupt output duration
If two `trim` branches read overlapping windows of the same `[0:v]` input and
both eventually feed the same `xfade` chain, the final output duration comes
out **wildly wrong** (observed: a 24.8s expected cut rendered as 144.3s) with
**zero errors or warnings from ffmpeg** — it just silently produces a broken
file. This reproduces even when the second branch is derived via `split`
from the first rather than a second direct `trim` on `[0:v]` — the fix is
not "avoid double-trimming," it's "every branch's source time window must be
disjoint from every other branch's, period." This is why a closing freeze
frame should come from a distinct late timestamp, not from re-using/splitting
the intro. `build_promo.py` checks this automatically and warns; don't
silence or bypass that check.

### `force_original_aspect_ratio=disable` on a crop stretches the image
Any crop whose `w:h` isn't already exactly the output ratio needs to either
be letterboxed (`decrease` + `pad`) or — better — re-fit to the exact ratio
before scaling (what `fit_crop_to_aspect()` does). `disable` forces a
non-uniform stretch and it is very easy to not notice until you look closely
at rendered text/UI elements and see them warped.

### Starting a shot already zoomed in reads as abrupt
A shot that opens directly on a tight crop, with only a mild secondary zoom
inside that crop, never shows the viewer the wide establishing context — it
reads as if the "real" opening was clipped off. Use the `push_in` style
(default): animate from the full frame (zoom=1, centered) to the target ROI
crop (exact zoom to fill frame, centered on ROI) over the shot's duration,
eased (ease-out cubic). This also directly fixes "the interesting bit got
clipped" complaints on branded intro/logo animations — find the actual start
of the reveal animation (scan frame-by-frame around where you *think* it
starts; it's usually a couple seconds earlier than assumed) rather than
starting on its resting/settled frame.

### Bare hex color literals
`BORDER = 0xE0A94B` (Python int) silently prints as a decimal string when
interpolated into an ffmpeg filter string (`"14713419"`), which ffmpeg
either rejects or misinterprets — no crash, just a wrong-colored element
that's easy to miss in a quick render check. Always keep color values as
strings: `BORDER = "0xE0A94B"`.

### Asymmetric drop shadows read as "inconsistent border"
If you add a soft shadow behind a bordered inset/frame, offset it (dx, dy)
from center and it reads as an uneven/inconsistent border even when the
border stroke itself is uniform — the eye reads shadow-visible-on-two-sides
as "thicker there." Center shadows exactly behind their frame unless an
offset is a deliberate design choice.

### A constantly-blurred background reads as static even with content changing
Blurring a background for the full duration of a video (e.g. behind a
picture-in-picture inset) reads as "nothing is moving" regardless of what's
actually playing under the blur, because blur removes the legible detail
that signals motion. If layering a blurred backdrop, keep it brief/contextual
(e.g. a few seconds under a closing card) rather than the sustained state for
most of the runtime — or add a continuous slow zoom (Ken Burns, see
`push_in_zoompan`/`zoompan` usage in `build_promo.py`) so it visibly moves.
When in doubt, prefer a single clean full-screen cut over a blurred-backdrop
layering trick — it's the safer default and was the actual fix that turned a
rejected "trash" edit into an accepted one.

## Mode B — compose the film (no screen recording)

Frames are composed in PIL and encoded from a PNG sequence. Three kinds of plate
feed the compositor:

1. **The real UI, captured offscreen** — `scripts/capture_ui.py`. Three
   backends, one contract (a PNG sequence plus a per-frame driver hook):
   | backend | what it drives | grabs |
   |---|---|---|
   | `qt` | PyQt5/6, PySide2/6 — window built by your own factory function | whole window, or one panel by `attr:` / `name:` / `class:` / `text:` selector |
   | `web` | any URL, incl. an Electron renderer, via headless Chromium (Playwright) | page, or one element by CSS selector |
   | `x11` | anything on an X display (GTK, native, a game); run it under Xvfb | a region, via ffmpeg `x11grab` |
   This is not a screen recording: nobody's desktop, notifications or cursor get
   in, and the plates cannot go stale because they are made from the app itself.
2. **Real footage**, cut to the exact size the layout uses — `scripts/plates.py`.
   Mode A's auditing rules apply unchanged: look at a contact sheet first.
3. **The drawn layer** — background, cards, typography, transitions:
   `scripts/promo_kit.py`.

A film is then a list of `(name, function, length_in_frames)`; see
`examples/film_example.py`. `--only <beat>` and `--start/--end` re-render one
beat into an existing frame directory, so a fix costs a minute, not an hour.

### Drive the UI through its own entry points
Feed the state machine the way the product does — the stdout its subprocesses
print, the dicts its readers emit, the actions its store dispatches — instead of
setting label text. The capture then cannot disagree with the shipping product,
and progress bars, counters and charts animate for free.
`examples/drivers_example.py` shows the shape for both Qt and web.

### Grab PANELS, not pixel crops of a window
Cropping a fixed rectangle out of a window capture is what makes a film look
like jumping screenshots: any text whose width changes re-flows the layout under
your fixed box, and anything past the crop line — progress bars, ETA rows,
totals — is silently cut off. Grab the panel widget/element *itself*: whole,
stable, nothing clipped. Capture it at 2x device scale so the compositor can
blow it up and keep the type crisp.

### Capture window plates at DISPLAY aspect
A window sized to the app's natural shape (say 1500x1400) reads as a phone
screenshot and wastes half of a 16:9 frame. Capture full-window plates at
1920x1080 logical with ~1.25x device scale — it fills the cut like a real
monitor and still downsamples crisply.

### Silence the app's own data sources — EVERY FRAME
Real readers (a telemetry poller, a rate monitor, a websocket) keep publishing
"offline / 0 Hz" when no hardware or backend is attached, and they overwrite the
state you inject *between grabs*. On screen that is a panel flickering between
LIVE and "no data" every other frame — the single most common defect in this
mode. Stubbing the starter once at setup is not enough: if the app armed it with
something like `QTimer.singleShot(300, self._ensure_reader)` (or a `setInterval`
registered at import), that timer captured the original callable before your
stub existed and will resurrect the reader a moment later. Stop it in the
per-frame tick.

### Time-series widgets usually reject non-monotonic x
A rolling chart typically drops any point whose x is ≤ the last one. Two
consequences: a whole-window back-fill re-sent each frame silently does nothing,
and any *other* producer stamping points at the wall clock parks itself ahead of
your back-dated ones and rejects everything you feed. Stop that producer, clear
the series, then feed timestamps that march forward across frames, spread over
the chart's window so the line spans it instead of spiking at "now".

### Layout traps
* Chart panels are usually far taller than data panels (e.g. 858x976 vs
  1036x386 at 2x). Lay them side by side; stacking two pushes the second off
  frame.
* Two captures of the same UI in different languages or themes must be **wiped
  or cut**, never cross-dissolved — overlapping glyphs are unreadable mush.
  `promo_kit.wipe()` does a hard edge with a lit seam.
* Keep captions clear of the frame edge: a 52 px title at y=968 with a subtitle
  under it is already cut off at 1080.

### Motion: judder, stepping, and one-frame jolts
Three defects that all read as "the transitions are not smooth", with three
different causes:

* **Judder from stretched plates.** A 60-frame capture shown across a 185-frame
  beat repeats each captured frame three times. Index plates FRACTIONALLY —
  `i * (len(seq(name)) - 1) / (n - 1)` — and blend the two neighbours;
  `promo_kit.frame_at()` does the blend for you.
* **Stepping from integer geometry.** A 40 px push-in over 150 frames moves
  0.27 px per frame, so pasting at integer coordinates stair-steps every few
  frames. Scale on a float and place on a float; `promo_kit` resamples through
  one affine op so slow moves glide.
* **Jolts from captured state changes.** A theme swap or page switch that
  happens between two captured frames lands as a single-frame jump. Ease it
  across ~8 frames by blending the plate frames either side of it, and
  cross-dissolve wherever two halves of a beat meet rather than cutting.

Verify with `scripts/check_flicker.py FRAMES` (no `--box` = whole frame): it
reports repeated frames, jolts and A-B-A oscillation in one pass. Judge repeats
on the MAX pixel delta, not the mean — a title card with a slow background has a
near-zero mean diff and is not a repeated frame at all.

### Score
`scripts/score.py` synthesises an original cue at the film's exact length:

    score.py --seconds 63.4 --bpm 118 --energy drive --out score.wav

Written rather than downloaded on purpose — an original cue has no licence
question, no attribution line, and no "royalty free" claim to verify — and it
can be written to the edit instead of the edit being cut to a track. Sections
scale with `--seconds`: pad-only intro, arpeggio in early, drums in at ~19 %,
riser before the end, drums out for the closing card.

Energy is structural, not a mix decision: `--energy calm` is a half-time kick
and no bass pulse; `--energy drive` is four-on-the-floor, an eighth-note bass,
claps on 2 and 4 and sixteenth hats. If a cue "feels too calm", the fix is the
arrangement and where the drums enter — not the volume.

Mux with `loudnorm`, and check the result: `-15 LUFS` integrated with true peak
under `-1.5 dBTP` sits right for a music-only promo (`ffmpeg -i out.mp4 -af
loudnorm=print_format=summary -f null /dev/null`).

### Ship light and dark from one compositor
Take the palettes from the product's own theme table (`--palette theme.json`),
parameterise the film with `--theme`, and capture one plate set per theme. Dark
needs its own treatment: black shadows vanish, so raise the alpha and keep the
hairline border, and the closing flash fades to black rather than white.

### Keep the compositor fast enough to iterate
Naive PIL work runs ~2 s/frame — an hour per pass, which kills iteration.
~0.18 s/frame is achievable and `promo_kit.py` already does it: build the static
background once and copy it, paint glow/particles at quarter resolution then
upscale, cache card shadows by (size, radius), cap the decoded plate cache, and
save with `compress_level=1`.

### Verify flicker numerically, not by eye
`scripts/check_flicker.py FRAMES --box x0,y0,x1,y1` crops to the panel and looks
for A-B-A oscillation (this frame matches the one two back but differs from the
one before). Zero oscillations with a small residual per-frame delta is what
"animating smoothly" looks like; anything else is flicker you would have
shipped. Exit code 1 on failure, so it belongs in the build script.

## Render settings
`libx264`, `-crf 16` (visually near-lossless, fine for short films — raise
toward 20-23 if file size matters more than quality), `-pix_fmt yuv420p`
(compatibility), `-movflags +faststart` (streams before fully downloaded),
`-preset slow` for a deliverable (`ultrafast` only for throwaway debug renders).

For a Mode B PNG sequence: `scripts/encode.sh frames/ out.mp4 [fps]`. Keep crf
at 16 or below — UI plates are full of hairline borders and 1 px chart strokes
that a looser quantiser turns to mush.

## Fonts
`DejaVu Sans Bold` (`/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf`) is
reliably present on Debian/Ubuntu-family boxes and reads clean at both small
(kicker) and large (title) sizes; `promo_kit.py` defaults to it. Check with
`fc-list | grep -i bold` on other systems.

In Mode B, prefer the product's own fonts (`--fonts DIR --font-map map.json`) so
the film and the UI are one typeface family. PIL has no letter-spacing — draw
display type character by character and add tracking (`tracked_text`). CJK needs
a font that actually has the glyphs (Noto Sans CJK, Pretendard); Latin-only
faces render Hangul/Kanji as boxes, and `fc-list :lang=ko` tells you what is
installed.

## Beat structure that survived client review
Open on the wordmark — a cold open on footage was cut as "useless" — then: the
whole product in one shot → the range it supports → the live workflow → each
capability as its own beat → the settings that prove it is a real product (theme
toggle, language toggle) → close on the same card the film opened with. ~60 s,
beats of 5-7 s, 12-frame dissolves.

Two asks that come back every review: show *every* supported variant rather than
one example, and show the product's own chrome (a dropdown mid-switch, a toggle
being clicked) rather than only its output.
