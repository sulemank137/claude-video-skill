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

# 4. prove the panels animate instead of flickering
python scripts/check_flicker.py frames/light --box 110,300,1010,640
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
| `scripts/promo_kit.py` | PIL toolkit: palettes, background, cards, captions, chips, wipes, beat timeline, CLI |
| `scripts/check_flicker.py` | numeric A-B-A oscillation check on a rendered panel |
| `scripts/encode.sh` | PNG sequence → H.264 at sane settings |
| `examples/` | a runnable 4-beat film, driver examples, clip/palette configs, sample-plate generator |

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
