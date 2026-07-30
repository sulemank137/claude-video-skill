# claude-video-skill

Make a ~60-second product film without paid tools — either by cutting an
existing screen recording, or by composing the film frame by frame from
**offscreen captures of the real UI** plus real camera footage.

Ships as a [Claude Code](https://claude.com/claude-code) skill (`SKILL.md`), but
every script runs standalone with Python + ffmpeg.

## Why the second mode exists

Screen recordings age badly. The app moves on, the recording doesn't, and you
end up shipping a film of a product that no longer exists — or re-recording the
whole thing by hand every release. Mode B builds each frame from the application
itself, driven through its own entry points, so the film always shows what
actually ships. As a side effect there is no cursor, no notification, no
desktop, and no "please don't move the mouse for six minutes".

## Install

```bash
git clone https://github.com/sulemank137/claude-video-skill.git
cd claude-video-skill
pip install pillow numpy                 # both modes
pip install playwright && playwright install chromium   # web capture only
# ffmpeg must be on PATH
```

As a Claude Code skill:

```bash
mkdir -p ~/.claude/skills/claude-video-skill
cp -r SKILL.md scripts examples ~/.claude/skills/claude-video-skill/
```

## Mode A — cut an existing recording

```bash
python scripts/contact_sheet.py raw.mp4 --start 0 --end 60 --step 2 --out sheet.jpg
# look at sheet.jpg, pick real moments, write config.json
python scripts/build_promo.py config.json
```

`build_promo.py` re-fits every crop to the exact output aspect, animates a
push-in from the wide frame, draws lower thirds, crossfades the shots and builds
a closing card. Config schema is documented in `SKILL.md`.

## Mode B — compose the film

```bash
# 1. capture the real UI (pick a backend)
python scripts/capture_ui.py --backend qt  --factory myapp.main:build_window \
    --widget "text:ROBOT HEALTH" --scale 2 --frames 190 \
    --driver mydrivers:tick --out plates/health

python scripts/capture_ui.py --backend web --url http://localhost:3000 \
    --selector "#health-card" --scale 2 --frames 190 \
    --driver mydrivers:tick --out plates/health

python scripts/capture_ui.py --backend x11 --display :99 \
    --region 0,0,1920,1080 --frames 200 --out plates/app

# 2. cut the footage
python scripts/plates.py clips.json --src-dir footage --out plates

# 3. compose and encode
python film.py --theme light --plates plates --out frames/light
./scripts/encode.sh frames/light promo_light.mp4

# 4. add an original score, cut to the film's length
python scripts/score.py --seconds 63.4 --bpm 118 --energy drive --out score.wav
ffmpeg -i promo_light.mp4 -i score.wav \
  -filter_complex "[1:a]loudnorm=I=-15:TP=-1.5:LRA=9[a]" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -shortest final.mp4

# 5. prove it is smooth: no flicker, no judder, no one-frame jolts
python scripts/check_flicker.py frames/light                       # whole frame
python scripts/check_flicker.py frames/light --box 110,300,1010,640  # one panel
```

Try it with no assets of your own:

```bash
python examples/make_sample_plates.py
python examples/film_example.py --plates examples/plates --out /tmp/frames
./scripts/encode.sh /tmp/frames /tmp/demo.mp4
```

## What's in here

| file | what it does |
|---|---|
| `SKILL.md` | the method: workflow, config schema, and every pitfall that cost a redo |
| `scripts/contact_sheet.py` | tile frames across a clip so you pick real moments, not dead ones |
| `scripts/build_promo.py` | Mode A: JSON → ffmpeg `filter_complex` → cut film |
| `scripts/capture_ui.py` | Mode B: capture a UI as PNG frames — `qt`, `web`, `x11` backends |
| `scripts/plates.py` | cut footage into plates at the exact size the layout uses |
| `scripts/promo_kit.py` | PIL toolkit: palettes, background, cards, captions, chips, effects, seam transitions, beat timeline, CLI |
| `scripts/score.py` | synthesise an original, licence-free cue at the film's exact length |
| `scripts/check_flicker.py` | numeric smoothness audit: flicker, judder, one-frame jolts |
| `scripts/encode.sh` | PNG sequence → H.264 at sane settings |
| `examples/` | a runnable 5-beat film, driver examples, clip/palette configs, sample-plate generator |

### Finish, beyond the layout

`promo_kit` covers the page; these cover the polish that separates a slide deck
from a film. All of them work in both themes, and all are written to stay cheap —
each caches its expensive part or paints at a fraction of full resolution,
because a full-size Gaussian per frame is what turns a 2000-frame render into an
hour.

| call | what it is for |
|---|---|
| `glass(img, box, accent=…)` | frosted panel of whatever is behind it — a caption stays readable over a busy UI plate without a flat slab covering it |
| `sheen(img, x, y, w, h, prog)` | specular band sweeping once across a card as it lands; `card(..., shine=ramp)` wires it up |
| `brackets()` / `scanbar()` | viewfinder corners and a travelling scan line: tells the eye this plate is camera and that one is UI |
| `backdrop(img, plate, g)` | blurred, slowly drifting copy of a plate behind the cards — depth for free |
| `pulse(img, g)` | vignette breathing on the musical beat; set `--bpm` to the score's tempo |
| `chroma(img, amt)` | channel split for a handful of frames at a hard landing, never continuous |
| `flow_dots(img, pts, g)` | dots running a polyline — data moving through a pipeline diagram |
| `transition(a, b, t, kind)` | `dissolve` / `wipe` / `flash` on a seam; name it as a 4th item on a beat |
| `fit_font(role, text, size, limit)` | largest size at which a label actually fits its box |
| `tracked_text(..., prog=, stagger=)` | per-character kinetic type that does not reflow as it lands |

Name a transition on the beats that start a new section and let the rest
dissolve:

```python
BEATS = [
    ("title", b_title, 90),
    ("loop",  b_loop, 210, "flash"),   # how THIS beat arrives
    ("app",   b_app, 140, "wipe"),
    ("panel", b_panel, 150),           # "dissolve" is the default
]
```

Then align the music to the actual edit instead of to guessed fractions:

```bash
python film.py --map          # prints every beat's start in seconds
python scripts/score.py --seconds 75.0 \
    --cue arp=2.9,drums=7.8,hats16=41.8,riser=67.8 \
    --fills 7.6,14.8,25.0,41.6,52.4,64.0 --out score.wav
```

## The failure modes it encodes

Most of the value here is negative knowledge — things that look fine in a still
and wrong in motion:

- **Fixed crop boxes over a live UI** re-flow under changing text and clip
  progress bars → grab the panel widget/element whole instead.
- **The app's own data readers** overwrite injected state between grabs, and a
  timer-armed starter resurrects them after you stub it → stop them every frame,
  and verify with `check_flicker.py`.
- **Rolling charts drop non-monotonic timestamps**, so a per-frame back-fill
  does nothing and a rival producer at wall-clock time blocks you entirely.
- **Window plates at the app's natural aspect** read as phone screenshots →
  capture at display aspect (1920x1080 @1.25x).
- **Cross-dissolving two text screenshots** (two languages, two themes) is
  unreadable → wipe or cut.
- **Cross-dissolving every seam** makes a film read as one long even wash with no
  structure → name `wipe`/`flash` on the beats that open a section.
- **`from promo_kit import P`** used to freeze the light palette at import time,
  so a film's own `P[...]` draws stayed light in `--theme dark` while text drawn
  inside the kit followed the flag. `P` is now mutated in place, never rebound.
- **Per-character kinetic type** with `stagger * len(text) + 0.22 > 1.0` settles
  with its last letters permanently half-lit — the ramp never completes.
- **Labels laid into fixed-width boxes** overflow silently as soon as the string
  is not the one you designed for → `fit_font()`.
- **A short plate stretched over a long beat** repeats each frame two or three
  times and judders → index plates fractionally and blend the neighbours.
- **Integer pasting of a slow push-in** stair-steps at ~0.3 px/frame → scale and
  place on floats, resampled in one affine op.
- **A captured state change** (theme swap, page switch) lands in a single frame
  and jolts → ease it across ~8 frames.
- **Starting a shot already zoomed in** reads as if the opening was clipped off
  → push in from the wide frame.
- Overlapping source-time trims in one ffmpeg graph silently produce a
  wrong-length file with no error at all.

## Requirements

- Python 3.9+, `pillow`, `numpy`
- `ffmpeg` / `ffprobe` on PATH
- Mode B, per backend: a Qt binding (PyQt6/PySide6/PyQt5/PySide2), or
  `playwright` + Chromium, or an X server (Xvfb is ideal)

Tested on Linux. The `qt` and `web` backends are platform-independent in
principle; `x11` is Linux-only by nature.

## License

MIT — see `LICENSE`.
