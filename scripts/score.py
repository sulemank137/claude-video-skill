#!/usr/bin/env python3
"""Synthesise an original background score for a film, in the film's own length.

Written rather than downloaded, for two reasons: an original cue has no licence
question attached to it at all — no attribution line, no platform terms, no
"royalty free" claim you cannot verify — and it can be written to the edit
instead of the edit being cut to fit a track.

    score.py --seconds 63.4 --out score.wav              # driving, default
    score.py --seconds 90 --bpm 96 --energy calm --key D --out bed.wav

Sections scale with `--seconds`: pad-only intro, arpeggio in at 6%, drums in at
19%, hats thicken at half way, riser before the end, drums out for the closing
card so the last few seconds resolve.

Mux it under a cut with:

    ffmpeg -i film.mp4 -i score.wav \\
      -filter_complex "[1:a]loudnorm=I=-15:TP=-1.5:LRA=9,afade=t=out:st=61.5:d=1.7[a]" \\
      -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -shortest out.mp4
"""
import argparse
import wave

import numpy as np

SR = 48000

# minor-key i – VI – III – VII, as semitone offsets from the tonic
DEGREES = [(0, [0, 3, 7]), (-4, [0, 4, 7]), (-9, [0, 4, 7]), (-2, [0, 4, 7])]
KEYS = {"A": 220.0, "B": 246.94, "C": 261.63, "D": 293.66, "E": 329.63,
        "F": 349.23, "G": 392.00}


def semis(base, n):
    return base * 2 ** (n / 12.0)


def env(n, attack, decay, sustain=0.0, release=0.0):
    a = max(1, int(attack * SR))
    d = max(1, int(decay * SR))
    r = max(1, int(release * SR)) if release else 0
    s = max(0, n - a - d - r)
    parts = [np.linspace(0, 1, a, endpoint=False),
             np.linspace(1, sustain if s or r else 0, d, endpoint=False)]
    if s:
        parts.append(np.full(s, sustain))
    if r:
        parts.append(np.linspace(sustain, 0, r, endpoint=False))
    return np.resize(np.concatenate(parts), n)


def lowpass(x, cutoff):
    """One-pole lowpass; `cutoff` may be an array for a moving filter."""
    a = np.resize(np.exp(-2 * np.pi * np.asarray(cutoff, dtype=float) / SR), len(x))
    y = np.empty_like(x)
    prev = 0.0
    for i in range(len(x)):
        prev = (1 - a[i]) * x[i] + a[i] * prev
        y[i] = prev
    return y


def saw(freq, n, detune=0.0, harmonics=8):
    """Additive saw — no aliasing scream from a naive ramp."""
    t = np.arange(n) / SR
    out = np.zeros(n)
    f = freq * (1 + detune)
    for h in range(1, harmonics + 1):
        if f * h > SR / 2.5:
            break
        out += np.sin(2 * np.pi * f * h * t) / h
    return out / harmonics ** 0.5


def pluck(freq, n, decay=0.16):
    t = np.arange(n) / SR
    return (np.sin(2 * np.pi * freq * t)
            + 0.35 * np.sin(2 * np.pi * freq * 2 * t)
            + 0.15 * np.sin(2 * np.pi * freq * 3 * t)) * np.exp(-t / decay)


def kick(n):
    t = np.arange(n) / SR
    f = 110 * np.exp(-t / 0.045) + 42
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.16)


def hat(n, rng):
    t = np.arange(n) / SR
    return rng.standard_normal(n) * np.exp(-t / 0.018) * 0.5


def clap(rng):
    n = int(0.22 * SR)
    out = np.zeros(n)
    for off, g in ((0.0, 1.0), (0.011, 0.7), (0.023, 0.5)):
        i0 = int(off * SR)
        tail = n - i0
        out[i0:] += g * rng.standard_normal(tail) * np.exp(-np.arange(tail) / (0.045 * SR))
    return lowpass(out, 5200) * 0.9


def add(buf, sig, at, gain=1.0, pan=0.0):
    i = int(at * SR)
    if i >= len(buf):
        return
    m = min(len(sig), len(buf) - i)
    buf[i:i + m, 0] += sig[:m] * gain * (1 - max(0.0, pan))
    buf[i:i + m, 1] += sig[:m] * gain * (1 + min(0.0, pan))


def build(seconds, bpm, tonic, energy):
    beat = 60.0 / bpm
    bar = 4 * beat
    drive = energy == "drive"
    rng = np.random.default_rng(7)
    n = int(seconds * SR)
    bed = np.zeros((n, 2))
    drums = np.zeros((n, 2))

    chords = [(semis(tonic / 2, root), [semis(tonic, root + iv) for iv in ivs])
              for root, ivs in DEGREES]

    t_in_arp = seconds * 0.06
    t_in_drum = seconds * 0.19
    t_in_16 = seconds * 0.52
    t_out = seconds - 4.2                       # drums stop for the last card

    # pad + sub, two bars per chord, the whole way
    at, k = 0.0, 0
    while at < seconds:
        root, notes = chords[k % len(chords)]
        m = min(int(2 * bar * SR) + int(0.6 * SR), n - int(at * SR))
        if m <= 0:
            break
        e = env(m, 0.9, 0.5, 0.75, 0.9)
        pos = at / seconds
        cut = 700 + 1500 * min(1.0, pos * 1.6) * (1.0 if pos < 0.86 else 0.45)
        for j, f in enumerate(notes):
            voice = saw(f, m, detune=0.004 * (j - 1)) + 0.5 * saw(f * 2, m,
                                                                  detune=-0.003 * j)
            add(bed, lowpass(voice * e, cut), at, gain=0.16, pan=-0.35 + 0.35 * j)
        sub = np.sin(2 * np.pi * root * np.arange(m) / SR) * env(m, 0.05, 0.4, 0.7, 0.6)
        add(bed, sub, at, gain=0.22 * min(1.0, at / 6.0))
        at += 2 * bar
        k += 1

    # arpeggio
    t, idx = t_in_arp, 0
    while t < seconds - 5.0:
        _root, notes = chords[int(t // (2 * bar)) % len(chords)]
        seq = notes + [notes[1] * 2, notes[2] * 2, notes[1] * 2]
        f = seq[idx % len(seq)] * (2 if (idx // len(seq)) % 2 else 1)
        g = (0.13 if drive else 0.10) * min(1.0, (t - t_in_arp) / 5.0)
        add(bed, pluck(f, int(0.4 * SR)), t, gain=g * (1.0 if t < seconds - 9 else 0.4),
            pan=-0.5 if idx % 2 else 0.5)
        t += beat / 4
        idx += 1

    if drive:                                    # eighth-note bass pulse
        t = t_in_drum - 4 * beat
        while t < t_out:
            root, _notes = chords[int(t // (2 * bar)) % len(chords)]
            m = int(beat * 0.46 * SR)
            tt = np.arange(m) / SR
            voice = (np.sin(2 * np.pi * root * tt)
                     + 0.30 * np.sin(2 * np.pi * root * 2 * tt)
                     + 0.12 * np.sin(2 * np.pi * root * 3 * tt))
            add(bed, voice * env(m, 0.004, 0.10, 0.55, 0.06), t, gain=0.30)
            t += beat / 2

    # drums
    kick_sig = kick(int(0.35 * SR))
    t = t_in_drum
    while t < t_out:
        add(drums, kick_sig, t, gain=0.62 if drive else 0.55)
        t += beat if drive else 2 * beat
    if drive:
        clap_sig = clap(rng)
        t = t_in_drum + beat
        while t < t_out:
            add(drums, clap_sig, t, gain=0.34)
            t += 2 * beat
    t = t_in_drum
    while t < t_out:
        step_i = int(round((t - t_in_drum) / (beat / 2)))
        openish = drive and step_i % 4 == 3
        add(drums, hat(int((0.16 if openish else 0.08) * SR), rng), t,
            gain=0.085 if openish else 0.055,
            pan=0.28 if step_i % 2 else -0.28)
        if drive and t > t_in_16:
            add(drums, hat(int(0.05 * SR), rng), t + beat / 4, gain=0.032,
                pan=-0.2 if step_i % 2 else 0.2)
        t += beat / 2

    if drive:                                    # fills into each section
        for frac in (0.31, 0.51, 0.72, 0.83):
            at = seconds * frac
            for j in range(4):
                m = int(0.22 * SR)
                tt = np.arange(m) / SR
                f = (150 - 18 * j) * np.exp(-tt / 0.09) + (110 - 12 * j)
                tom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.13)
                add(drums, tom, at + j * beat / 4, gain=0.28, pan=-0.4 + 0.27 * j)

    ln = int(2.5 * SR)                           # riser into the closing card
    sweep = lowpass(rng.standard_normal(ln), np.linspace(300, 6000, ln))
    add(bed, sweep * np.linspace(0, 1, ln) ** 2, seconds - 10.5,
        gain=0.13 if drive else 0.09)

    # sidechain: the bed breathes around the kick
    duck = np.ones(n)
    step_n = int(0.28 * SR)
    shape = 1 - (0.38 if drive else 0.30) * np.exp(-np.arange(step_n) / (0.08 * SR))
    t = t_in_drum
    while t < t_out:
        i = int(t * SR)
        m = min(step_n, n - i)
        if m > 0:
            duck[i:i + m] = np.minimum(duck[i:i + m], shape[:m])
        t += beat if drive else 2 * beat
    bed *= duck[:, None]

    mix = np.tanh((bed + drums) * 1.25) * 0.72
    fade_in = np.minimum(1.0, np.arange(n) / (1.2 * SR))
    fade_out = np.minimum(1.0, (n - np.arange(n)) / (3.2 * SR))
    return mix * (fade_in * fade_out)[:, None]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="score.wav")
    ap.add_argument("--seconds", type=float, default=63.4)
    ap.add_argument("--bpm", type=float, default=118.0)
    ap.add_argument("--key", default="A", choices=sorted(KEYS))
    ap.add_argument("--energy", default="drive", choices=["drive", "calm"],
                    help="drive: four-on-the-floor, bass pulse, claps, fills. "
                         "calm: half-time kick, no bass pulse, softer hats")
    args = ap.parse_args()

    mix = build(args.seconds, args.bpm, KEYS[args.key], args.energy)
    peak = np.abs(mix).max()
    if peak > 0:
        mix = mix / peak * 0.89
    with wave.open(args.out, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((mix * 32767).astype("<i2").tobytes())
    print(f"{args.out}: {len(mix) / SR:.2f}s  {args.bpm:.0f} BPM  "
          f"{args.key} minor  {args.energy}  peak {peak:.3f}")


if __name__ == "__main__":
    main()
