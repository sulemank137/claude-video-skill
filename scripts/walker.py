"""A side-view walker for explainer films, drawn from a sagittal-plane gait model in two styles
on one skeleton: a person and a humanoid robot. Same joints, same phase, so a wipe from one
style to the other reads as the same body changing, not a cut.

    lay, pts = render("human", phi, c, L=520, size=(W, H), ground_y=800, x0=620)
    img.alpha_composite(lay)          # pts["hip"], pts["shoulder"]... to attach props or arrows

Drive `phi` by integrating 1 / cycle_frames per frame (never `i / cycle` with a cycle that
changes), and move a floor or treadmill belt under it at `stance_speed(L, c)` px per cycle.

Angles are from the vertical, positive forward (the walker faces +x). The stance foot is pinned
to the ground by lifting the pelvis to the lower foot, which gives the walk its natural bob and
keeps the feet from sinking into the belt or floating above it.
"""
import math

from PIL import Image, ImageDraw

D2R = math.pi / 180.0
# segment lengths as fractions of standing height
THIGH, SHANK, TORSO, NECK, HEAD_R = 0.245, 0.246, 0.29, 0.045, 0.062
UARM, FARM, HEEL, TOE, ANKLE_H = 0.165, 0.15, 0.035, 0.11, 0.04


def _g(x, mu, s):
    return math.exp(-((x - mu) / s) ** 2)


def joint_angles(phi, c=1.0):
    """One leg at gait phase phi in [0, 1) (0 = heel strike). c in [0, 1] is competence: a
    supported beginner takes short, crouched steps; c = 1 is a full adult stride."""
    phi %= 1.0
    amp = 0.55 + 0.45 * c
    hip = 6.5 * amp + 18.5 * amp * math.cos(2 * math.pi * phi)
    knee = (18 * _g(phi, 0.15, 0.08) + (48 + 14 * c) * (_g(phi, 0.72, 0.11) + _g(phi, -0.28, 0.11))
            + 4 + 10 * (1 - c))
    foot = (10 * (_g(phi, 0.0, 0.06) + _g(phi, 1.0, 0.06)) - 28 * amp * _g(phi, 0.6, 0.07)
            + 6 * _g(phi, 0.8, 0.08))
    return hip, knee, foot


def leg_points(hx, hy, L, phi, c):
    """Hip -> knee -> ankle -> heel/toe in pixels (y down)."""
    hip, knee, foot = joint_angles(phi, c)
    th, ts = hip * D2R, (hip - knee) * D2R
    kx, ky = hx + L * THIGH * math.sin(th), hy + L * THIGH * math.cos(th)
    ax, ay = kx + L * SHANK * math.sin(ts), ky + L * SHANK * math.cos(ts)
    fp = foot * D2R
    ca, sa = math.cos(fp), math.sin(fp)
    # heel and toe from the ankle, the sole ANKLE_H below it, rotated by foot pitch (toe up = +)
    def rot(dx, dy):
        return ax + dx * ca + dy * sa, ay - dx * sa + dy * ca
    heel = rot(-L * HEEL, L * ANKLE_H)
    toe = rot(L * TOE, L * ANKLE_H)
    return (hx, hy), (kx, ky), (ax, ay), heel, toe


def pose(phi, c, L, ground_y, x0, lean=0.0):
    """Both legs, trunk and arms for the near leg at phase phi. Returns a dict of points."""
    near = leg_points(0, 0, L, phi, c)
    far = leg_points(0, 0, L, phi + 0.5, c)
    low = max(near[3][1], near[4][1], far[3][1], far[4][1])
    hy = ground_y - low
    sh = lambda p: (x0 + p[0], hy + p[1])  # noqa: E731
    near, far = [sh(p) for p in near], [sh(p) for p in far]
    hip = (x0, hy)
    tl = (4 + 6 * (1 - c) + lean) * D2R                    # forward trunk lean
    shoulder = (x0 + L * TORSO * math.sin(tl), hy - L * TORSO * math.cos(tl))
    head = (shoulder[0] + L * (NECK + HEAD_R) * math.sin(tl * 1.3),
            shoulder[1] - L * (NECK + HEAD_R) * math.cos(tl * 1.3))
    arms = []
    for ph in (phi + 0.5, phi):                            # near arm swings with the far leg
        sw = (0.35 + 0.65 * c) * math.cos(2 * math.pi * ph)
        a = (2 + 16 * sw) * D2R
        e = a + (20 + 14 * max(0.0, sw)) * D2R
        el = (shoulder[0] + L * UARM * math.sin(a), shoulder[1] + L * UARM * math.cos(a))
        wr = (el[0] + L * FARM * math.sin(e), el[1] + L * FARM * math.cos(e))
        arms.append((shoulder, el, wr))
    return dict(near=near, far=far, hip=hip, shoulder=shoulder, head=head,
                arm_near=arms[0], arm_far=arms[1], lean=tl)


def stance_speed(L, c=1.0, n=400):
    """Mean backward speed of the stance ankle relative to the hip, px per gait cycle — the belt
    speed at which the planted foot does not skate."""
    xs = [leg_points(0, 0, L, k / n, c)[2][0] for k in range(n)]
    lo, hi = int(0.08 * n), int(0.5 * n)
    return (xs[lo] - xs[hi]) / ((hi - lo) / n)


# ---- drawing -----------------------------------------------------------------------------
def _shade(c, k):
    return tuple(int(v * k) for v in c[:3]) + tuple(c[3:])


def limb(d, a, b, w, col):
    taper(d, a, b, w / 2, w / 2, col)


def taper(d, a, b, r0, r1, col):
    """A limb segment: two discs joined by their outer tangents, radius r0 at a and r1 at b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    ln = math.hypot(dx, dy) or 1e-6
    nx, ny = -dy / ln, dx / ln
    d.polygon([(a[0] + nx * r0, a[1] + ny * r0), (b[0] + nx * r1, b[1] + ny * r1),
               (b[0] - nx * r1, b[1] - ny * r1), (a[0] - nx * r0, a[1] - ny * r0)], fill=col)
    for p, r in ((a, r0), (b, r1)):
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=col)


HUMAN = dict(skin=(234, 192, 160), hair=(64, 48, 42), shirt=(58, 146, 168), pants=(46, 62, 98),
             shoe=(70, 76, 92), sole=(236, 236, 240))
ROBOT = dict(shell=(230, 233, 239), dark=(52, 55, 64), joint=(92, 97, 110), led=(40, 200, 230),
             panel=(196, 201, 211))


def _trunk(P, L):
    hx, hy = P["hip"]
    sx, sy = P["shoulder"]
    return (hx, hy), (sx, sy)


def draw_human(d, P, L, alpha=255, hook=None):
    A = (alpha,)
    sk, pa, sh = HUMAN["skin"] + A, HUMAN["pants"] + A, HUMAN["shirt"] + A
    shoe, sole = HUMAN["shoe"] + A, HUMAN["sole"] + A
    s, el, wr = P["arm_far"]
    taper(d, s, el, L * 0.03, L * 0.024, _shade(sh, 0.8)); taper(d, el, wr, L * 0.021, L * 0.017, _shade(sk, 0.84))
    for side, k in (("far", 0.8), ("near", 1.0)):
        hip, kn, an, he, to = P[side]
        taper(d, hip, kn, L * 0.05, L * 0.038, _shade(pa, k)); taper(d, kn, an, L * 0.036, L * 0.026, _shade(pa, k))
        taper(d, he, to, L * 0.026, L * 0.02, _shade(shoe, 0.9 * k + 0.1))
        mid = ((he[0] + to[0]) / 2, (he[1] + to[1]) / 2)
        taper(d, (he[0], he[1] + L * 0.012), (mid[0] + (to[0] - mid[0]) * 0.9, to[1] + L * 0.01), L * 0.011, L * 0.009, _shade(sole, k))
        if side == "far":                                    # trunk and head between the legs
            (hx, hy), (sx, sy) = _trunk(P, L)
            taper(d, (hx, hy - L * 0.03), (sx, sy + L * 0.035), L * 0.062, L * 0.07, sh)
            taper(d, (hx, hy), (hx + L * 0.003, hy - L * 0.02), L * 0.052, L * 0.05, pa)
            hx2, hy2 = P["head"]
            taper(d, (sx, sy), ((sx + hx2) / 2, (sy + hy2) / 2), L * 0.022, L * 0.02, sk)
            r = L * HEAD_R
            d.ellipse([hx2 - r * 0.95, hy2 - r, hx2 + r * 0.95, hy2 + r], fill=sk)
            d.ellipse([hx2 - r * 0.25, hy2 - r * 0.1, hx2 + r * 0.05, hy2 + r * 0.3], fill=_shade(sk, 0.9))  # ear
            d.chord([hx2 - r * 1.02, hy2 - r * 1.1, hx2 + r * 0.98, hy2 + r * 0.55], 165, 352, fill=HUMAN["hair"] + A)
            d.ellipse([hx2 + r * 0.48, hy2 - r * 0.18, hx2 + r * 0.64, hy2 - r * 0.02], fill=(40, 34, 32) + A)
    if hook:                                                 # e.g. a harness: over the trunk, under the near arm
        hook()
    s, el, wr = P["arm_near"]
    taper(d, s, el, L * 0.032, L * 0.025, sh); taper(d, el, wr, L * 0.022, L * 0.018, sk)
    d.ellipse([wr[0] - L * 0.022, wr[1] - L * 0.022, wr[0] + L * 0.022, wr[1] + L * 0.022], fill=sk)


def draw_robot(d, P, L, alpha=255, hook=None):
    A = (alpha,)
    shell, dark, jt, led = ROBOT["shell"] + A, ROBOT["dark"] + A, ROBOT["joint"] + A, ROBOT["led"] + A

    def disc(p, f, col):
        r = L * f
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=col)

    s, el, wr = P["arm_far"]
    taper(d, s, el, L * 0.03, L * 0.026, _shade(shell, 0.76)); taper(d, el, wr, L * 0.024, L * 0.02, _shade(shell, 0.76))
    for side, k in (("far", 0.76), ("near", 1.0)):
        hip, kn, an, he, to = P[side]
        taper(d, hip, kn, L * 0.05, L * 0.042, _shade(shell, k)); taper(d, kn, an, L * 0.04, L * 0.028, _shade(shell, k))
        taper(d, (he[0], he[1] - L * 0.006), (to[0], to[1] - L * 0.006), L * 0.016, L * 0.013, _shade(dark, k))
        disc(kn, 0.019, jt); disc(an, 0.013, jt)
        if side == "far":
            (hx, hy), (sx, sy) = _trunk(P, L)
            taper(d, (hx, hy - L * 0.02), (sx, sy + L * 0.045), L * 0.058, L * 0.074, shell)
            mx, my = hx + (sx - hx) * 0.62, hy + (sy - hy) * 0.62
            taper(d, (mx + L * 0.035, my + L * 0.035), (mx + L * 0.045, my - L * 0.04), L * 0.024, L * 0.024, ROBOT["panel"] + A)  # chest
            disc((hx, hy), 0.05, dark)
            hx2, hy2 = P["head"]
            r = L * HEAD_R
            taper(d, (sx, sy), ((sx + hx2) / 2, (sy + hy2) / 2), L * 0.02, L * 0.02, jt)
            d.rounded_rectangle([hx2 - r * 0.92, hy2 - r * 1.02, hx2 + r * 0.98, hy2 + r * 0.92], radius=r * 0.6, fill=dark)
            d.rounded_rectangle([hx2 + r * 0.18, hy2 - r * 0.34, hx2 + r * 0.92, hy2 + r * 0.04], radius=r * 0.18, fill=led)
    if hook:
        hook()
    s, el, wr = P["arm_near"]
    taper(d, s, el, L * 0.033, L * 0.027, shell); taper(d, el, wr, L * 0.026, L * 0.021, shell)
    disc(s, 0.022, jt); disc(el, 0.015, jt)


def render(style, phi, c, L, size, ground_y, x0, ss=2, lean=0.0, hook=None):
    """The walker alone on a transparent layer of `size`, supersampled `ss`x for clean edges.
    `hook(d, P, ss)` draws a prop worn on the body (a harness, a backpack) in the same space,
    after the trunk and before the near arm, so the arm passes in front of it."""
    w, h = size
    lay = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    P = pose(phi, c, L * ss, ground_y * ss, x0 * ss, lean)
    (draw_human if style == "human" else draw_robot)(d, P, L * ss, hook=hook and (lambda: hook(d, P, ss)))
    return lay.resize((w, h), Image.LANCZOS), {k: _scale(v, 1 / ss) for k, v in P.items()}


def _scale(v, k):
    if isinstance(v, tuple) and len(v) == 2 and all(isinstance(t, (int, float)) for t in v):
        return (v[0] * k, v[1] * k)
    if isinstance(v, (list, tuple)):
        return type(v)(_scale(t, k) for t in v)
    return v


if __name__ == "__main__":
    # self-check: the lower foot touches the ground in every phase, and the belt speed is positive
    for c in (0.0, 1.0):
        for k in range(20):
            P = pose(k / 20, c, 500, 800, 400)
            low = max(P["near"][3][1], P["near"][4][1], P["far"][3][1], P["far"][4][1])
            assert abs(low - 800) < 1e-6, low
        assert stance_speed(500, c) > 0
    seen = []                                  # a worn prop is drawn once, in supersampled space
    lay, _ = render("human", 0.3, 1.0, 300, (400, 400), 380, 200, hook=lambda d, P, ss: seen.append(ss))
    assert seen == [2] and lay.getbbox()
    print("ok", round(stance_speed(500, 0.0), 1), round(stance_speed(500, 1.0), 1))
