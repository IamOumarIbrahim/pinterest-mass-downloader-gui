"""Turn a raw recording into the polished README video (+ GIF preview).

usage: python tools/demo/compose_video.py WORKDIR OUT.mp4 [OUT.gif]

Reads WORKDIR/raw.mp4, frames.json and events.json written by record_demo.py
and adds: a backdrop, smooth camera zooms on each step, an animated cursor
with click ripples, the dragged picture, step captions, a fast-forward
through the waiting part, and intro/outro cards.
"""

import json
import math
import os
import subprocess
import sys

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

WORK, OUT = sys.argv[1], sys.argv[2]
GIF = sys.argv[3] if len(sys.argv) > 3 else None
FF = imageio_ffmpeg.get_ffmpeg_exe()
CW, CH, FPS = 1920, 1080, 30
ACCENT = (230, 0, 35)
FONTS = "C:/Windows/Fonts/"


def font(size, weight="sb"):
    name = {"sb": "seguisb.ttf", "b": "segoeuib.ttf", "r": "segoeui.ttf"}[weight]
    try:
        return ImageFont.truetype(FONTS + name, size)
    except OSError:
        return ImageFont.load_default(size)


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def ease_out(x):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


# ── load recording ──────────────────────────────────────────────────────────
meta = json.load(open(os.path.join(WORK, "events.json"), encoding="utf-8"))
W, H = meta["window"]
EV = meta["events"]
frame_t = json.load(open(os.path.join(WORK, "frames.json")))
T0 = frame_t[0]
for e in EV:
    e["s"] = e["t"] - T0  # seconds into the raw recording
SRC_END = frame_t[-1] - T0

# ── output time → source time (fast-forward segments) ───────────────────────
speeds = [(e["s"], e["factor"]) for e in EV if e["type"] == "speed"]


def factor_at(s):
    f = 1.0
    for at, fac in speeds:
        if s >= at:
            f = fac
    return f


src_times = []
s = 0.0
while s < SRC_END:
    src_times.append(s)
    s += factor_at(s) / FPS

# ── camera ──────────────────────────────────────────────────────────────────
MARGIN_X, MARGIN_TOP, MARGIN_BOT = 110, 60, 120
S0 = min((CW - 2 * MARGIN_X) / W, (CH - MARGIN_TOP - MARGIN_BOT) / H)
BASE_C = (W / 2, H / 2)
ANCHOR = (CW / 2, MARGIN_TOP + (CH - MARGIN_TOP - MARGIN_BOT) / 2)
foci = [(0.0, BASE_C, 1.0)]
for e in EV:
    if e["type"] == "focus":
        if e["rect"]:
            x0, y0, x1, y1 = e["rect"]
            fit = min(W * 0.92 / max(x1 - x0, 1), H * 0.85 / max(y1 - y0, 1))
            z = min(e["zoom"], max(1.0, fit))
            foci.append((e["s"], ((x0 + x1) / 2, (y0 + y1) / 2), z))
        else:
            foci.append((e["s"], BASE_C, 1.0))
TRANS = 0.75


def clamp_center(c, z):
    """Keep a zoomed view inside the window so no backdrop shows at the edges."""
    S = S0 * z
    hw, hh = (CW / 2) / S, (CH / 2) / S
    cx = W / 2 if hw * 2 >= W else min(max(c[0], hw), W - hw)
    cy = H / 2 if hh * 2 >= H else min(max(c[1], hh), H - hh)
    return cx, cy


def camera(s):
    prev = cur = foci[0]
    for f in foci:
        if f[0] <= s:
            prev, cur = cur, f
    k = ease((s - cur[0]) / TRANS)
    pc, cc = clamp_center(prev[1], prev[2]), clamp_center(cur[1], cur[2])
    z = prev[2] + (cur[2] - prev[2]) * k
    return (pc[0] + (cc[0] - pc[0]) * k, pc[1] + (cc[1] - pc[1]) * k), z


def to_canvas(p, c, z):
    """Window pixel -> canvas pixel. Unzoomed, the window sits at ANCHOR (leaving
    room for captions); zoomed in, the camera centre goes to the canvas centre."""
    S = S0 * z
    a = min(1.0, max(0.0, (z - 1) / 0.25))
    vx = ANCHOR[0] + (CW / 2 - ANCHOR[0]) * a
    vy = ANCHOR[1] + (CH / 2 - ANCHOR[1]) * a
    return vx + (p[0] - c[0]) * S, vy + (p[1] - c[1]) * S


# ── cursor path ─────────────────────────────────────────────────────────────
moves = [(e["s"], e["dur"], (e["x"], e["y"])) for e in EV if e["type"] == "move"]
START_POS = (W * 0.62, H * 0.55)


def cursor_at(s):
    pos = START_POS
    for at, dur, target in moves:
        if s < at:
            break
        k = ease((s - at) / dur) if dur > 0 else 1
        pos = (pos[0] + (target[0] - pos[0]) * k, pos[1] + (target[1] - pos[1]) * k)
    return pos


clicks = [e["s"] for e in EV if e["type"] in ("click", "drop")]
presses = []
for e in EV:
    if e["type"] == "press":
        presses.append([e["s"], math.inf])
    elif e["type"] == "release" and presses:
        presses[-1][1] = e["s"]
drag = next(((e["s"], e["path"]) for e in EV if e["type"] == "drag_file"), None)
drop_s = next((e["s"] for e in EV if e["type"] == "drop"), None)
captions = [(e["s"], e["text"]) for e in EV if e["type"] == "caption"]


def caption_at(s):
    cur, start, end = None, 0, math.inf
    for i, (at, text) in enumerate(captions):
        if at <= s:
            cur, start = text, at
            end = captions[i + 1][0] if i + 1 < len(captions) else math.inf
    if not cur:
        # keep fading the previous caption out
        return None, 0
    alpha = min(ease((s - start) / 0.3), ease((end - s) / 0.3) if end < math.inf else 1)
    return cur, alpha


def step_number(text):
    texts = [t for _, t in captions if t]
    return texts.index(text) + 1 if text in texts else None


# ── sprites ─────────────────────────────────────────────────────────────────
def make_cursor(size=30):
    k = 4
    im = Image.new("RGBA", (size * k, int(size * 1.5) * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pts = [(0, 0), (0, 21), (5.2, 16.2), (8.6, 24), (12, 22.6), (8.6, 15), (15.4, 15)]
    sc = size * k / 17
    poly = [(2 * k + x * sc, 2 * k + y * sc) for x, y in pts]
    shadow = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon([(x + 2 * k, y + 3 * k) for x, y in poly], fill=(0, 0, 0, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(3 * k))
    im = Image.alpha_composite(im, shadow)
    d = ImageDraw.Draw(im)
    d.polygon(poly, fill=(20, 20, 20, 255))
    inner = [(2 * k + x * sc, 2 * k + y * sc) for x, y in
             [(1.6, 3.8), (1.6, 17.2), (5.6, 13.4), (9.3, 21.6), (10.4, 21.1), (6.9, 13.2), (12, 13.2)]]
    d.polygon(inner, fill=(255, 255, 255, 255))
    return im.resize((im.width // k, im.height // k), Image.Resampling.LANCZOS)


CURSOR = make_cursor(30)


def rounded_mask(size, r):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], r, fill=255)
    return m


WIN_MASK = rounded_mask((W, H), 14)


def backdrop():
    y = np.linspace(0, 1, CH)[:, None]
    x = np.linspace(0, 1, CW)[None, :]
    top, bot = np.array([24, 8, 14]), np.array([10, 6, 12])
    base = top[None, None] * (1 - y[..., None]) + bot[None, None] * y[..., None]
    glow = np.exp(-(((x - 0.5) / 0.45) ** 2 + ((y - 0.15) / 0.35) ** 2))[..., None]
    img = base + glow * np.array([70, 0, 18])[None, None]
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).convert("RGBA")


BG = backdrop()
SHADOW_PAD = 60
_sh = Image.new("RGBA", (W + 2 * SHADOW_PAD, H + 2 * SHADOW_PAD), (0, 0, 0, 0))
ImageDraw.Draw(_sh).rounded_rectangle([SHADOW_PAD, SHADOW_PAD + 18, SHADOW_PAD + W, SHADOW_PAD + H + 18],
                                      18, fill=(0, 0, 0, 170))
SHADOW = _sh.filter(ImageFilter.GaussianBlur(28))

ref_card = None
if drag:
    try:
        r = Image.open(drag[1]).convert("RGB")
        r.thumbnail((130, 130))
        card = Image.new("RGBA", (r.width + 12, r.height + 12), (255, 255, 255, 255))
        card.paste(r, (6, 6))
        card.putalpha(rounded_mask(card.size, 10))
        ref_card = card
    except OSError:
        pass


# ── frame composition ───────────────────────────────────────────────────────
def put(dst: Image.Image, src: Image.Image, xy):
    """alpha_composite that tolerates sprites hanging off the canvas."""
    x, y = int(xy[0]), int(xy[1])
    left, top = max(0, -x), max(0, -y)
    right, bottom = min(src.width, dst.width - x), min(src.height, dst.height - y)
    if right > left and bottom > top:
        dst.alpha_composite(src.crop((left, top, right, bottom)), (x + left, y + top))


def compose(frame: Image.Image, s: float) -> Image.Image:
    c, z = camera(s)
    S = S0 * z
    out = BG.copy()
    x0, y0 = to_canvas((0, 0), c, z)
    # shadow (only noticeable when not zoomed)
    if z < 1.05:
        sw, sh = int(SHADOW.width * S), int(SHADOW.height * S)
        sha = SHADOW.resize((sw, sh), Image.Resampling.BILINEAR)
        put(out, sha, (int(x0 - SHADOW_PAD * S), int(y0 - SHADOW_PAD * S)))
    # visible part of the window
    vx0, vy0 = max(0, (0 - x0) / S), max(0, (0 - y0) / S)
    vx1, vy1 = min(W, (CW - x0) / S), min(H, (CH - y0) / S)
    box = (int(vx0), int(vy0), int(math.ceil(vx1)), int(math.ceil(vy1)))
    crop = frame.crop(box)
    mask = WIN_MASK.crop(box)
    dw, dh = int(round((box[2] - box[0]) * S)), int(round((box[3] - box[1]) * S))
    crop = crop.resize((dw, dh), Image.Resampling.LANCZOS if S < 1.6 else Image.Resampling.BICUBIC)
    mask = mask.resize((dw, dh), Image.Resampling.BILINEAR)
    out.paste(crop, (int(round(x0 + box[0] * S)), int(round(y0 + box[1] * S))), mask)
    draw = ImageDraw.Draw(out)

    # click ripples
    for cs in clicks:
        k = (s - cs) / 0.45
        if 0 <= k <= 1:
            px, py = to_canvas(cursor_at(cs), c, z)
            r = 10 + 34 * ease_out(k)
            a = int(170 * (1 - k))
            ring = Image.new("RGBA", (int(2 * r + 8), int(2 * r + 8)), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse([4, 4, 4 + 2 * r, 4 + 2 * r], outline=(255, 255, 255, a), width=4)
            put(out, ring, (int(px - r - 4), int(py - r - 4)))

    # dragged picture
    px, py = to_canvas(cursor_at(s), c, z)
    if ref_card and drag and drag[0] <= s and (drop_s is None or s < drop_s + 0.25):
        k = 1 - ease((s - drop_s) / 0.25) if drop_s and s >= drop_s else 1
        cardk = ref_card.copy()
        cardk.putalpha(cardk.getchannel("A").point(lambda v: int(v * 0.92 * k)))
        put(out, cardk, (int(px + 18), int(py + 18)))

    # cursor
    pressed = any(a <= s <= b for a, b in presses) or any(0 <= s - cs <= 0.15 for cs in clicks)
    cur = CURSOR if not pressed else CURSOR.resize((int(CURSOR.width * 0.86), int(CURSOR.height * 0.86)))
    scale = min(1.35, max(1.0, z * 0.9))
    if scale != 1:
        cur = cur.resize((int(cur.width * scale), int(cur.height * scale)), Image.Resampling.LANCZOS)
    put(out, cur, (int(px - 2), int(py - 2)))

    # caption
    text, alpha = caption_at(s)
    if text and alpha > 0.01:
        n = step_number(text)
        f = font(34)
        tw = draw.textlength(text, font=f)
        badge = 46 if n else 0
        pw, ph = int(tw + 64 + badge + (14 if n else 0)), 74
        pill = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        pd = ImageDraw.Draw(pill)
        pd.rounded_rectangle([0, 0, pw - 1, ph - 1], ph // 2, fill=(18, 18, 22, 235))
        x = 32
        if n:
            pd.ellipse([22, (ph - badge) // 2, 22 + badge, (ph + badge) // 2], fill=ACCENT + (255,))
            nf = font(26, "b")
            nw = pd.textlength(str(n), font=nf)
            pd.text((22 + (badge - nw) / 2, ph / 2 - 17), str(n), font=nf, fill="white")
            x = 22 + badge + 16
        pd.text((x, ph / 2 - 24), text, font=f, fill=(245, 245, 248))
        pill.putalpha(pill.getchannel("A").point(lambda v: int(v * alpha)))
        put(out, pill, (int(CW / 2 - pw / 2), CH - ph - 28))

    # fast-forward badge
    fac = factor_at(s)
    if fac > 1:
        f = font(28, "b")
        label = f"{fac:g}×  fast-forward"
        tw = draw.textlength(label, font=f)
        draw.rounded_rectangle([CW - tw - 70, 30, CW - 30, 82], 26, fill=(230, 0, 35))
        draw.text((CW - tw - 50, 36), label, font=f, fill="white")
    return out.convert("RGB")


def title_card(t, total, title, sub, extra=None):
    out = BG.copy()
    d = ImageDraw.Draw(out)
    a = min(ease(t / 0.5), ease((total - t) / 0.5))
    layer = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    cy = CH / 2 - 60
    ld.ellipse([CW / 2 - 56, cy - 150, CW / 2 + 56, cy - 38], fill=ACCENT + (255,))
    pf = font(70, "b")
    pw = ld.textlength("P", font=pf)
    ld.text((CW / 2 - pw / 2, cy - 145), "P", font=pf, fill="white")
    tf = font(76, "b")
    tw = ld.textlength(title, font=tf)
    ld.text((CW / 2 - tw / 2, cy - 10), title, font=tf, fill=(246, 246, 248))
    sf = font(36, "r")
    sw = ld.textlength(sub, font=sf)
    ld.text((CW / 2 - sw / 2, cy + 95), sub, font=sf, fill=(190, 190, 200))
    if extra:
        ef = ImageFont.truetype(FONTS + "consola.ttf", 32) if os.path.exists(FONTS + "consola.ttf") else sf
        for i, line in enumerate(extra):
            ew = ld.textlength(line, font=ef)
            y = cy + 180 + i * 56
            ld.rounded_rectangle([CW / 2 - ew / 2 - 24, y - 8, CW / 2 + ew / 2 + 24, y + 44], 12,
                                 fill=(255, 255, 255, 18))
            ld.text((CW / 2 - ew / 2, y), line, font=ef, fill=(235, 235, 240))
    layer.putalpha(layer.getchannel("A").point(lambda v: int(v * a)))
    out.alpha_composite(layer)
    del d
    return out.convert("RGB")


def main():
    reader = imageio_ffmpeg.read_frames(os.path.join(WORK, "raw.mp4"))
    info = next(reader)
    rw, rh = info["size"]
    enc = subprocess.Popen(
        [FF, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{CW}x{CH}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "20",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", OUT], stdin=subprocess.PIPE)

    intro = 2.6
    for i in range(int(intro * FPS)):
        enc.stdin.write(title_card(i / FPS, intro, "Pinterest Mass Downloader",
                                   "Bulk-download pictures, videos & GIFs, keeping only the ones you want").tobytes())

    idx, raw = -1, None
    for n, st in enumerate(src_times):
        want = min(int(st * FPS), len(frame_t) - 1)
        while idx < want:
            try:
                raw = next(reader)
            except StopIteration:
                break
            idx += 1
        frame = Image.frombytes("RGB", (rw, rh), raw)
        if frame.size != (W, H):
            frame = frame.resize((W, H))
        enc.stdin.write(compose(frame, st).tobytes())
        if n % 150 == 0:
            print(f"  {n}/{len(src_times)} frames", flush=True)

    outro = 3.4
    for i in range(int(outro * FPS)):
        enc.stdin.write(title_card(i / FPS, outro, "Get started",
                                   "Windows · Python 3.10+",
                                   ["pip install -r requirements.txt",
                                    "python pinterest_downloader.py"]).tobytes())
    enc.stdin.close()
    enc.wait()
    print("wrote", OUT)

    if GIF:
        pal = os.path.join(WORK, "palette.png")
        vf = "fps=10,scale=880:-1:flags=lanczos"
        subprocess.run([FF, "-y", "-v", "error", "-i", OUT, "-vf", vf + ",palettegen=max_colors=160:stats_mode=diff",
                        pal], check=True)
        subprocess.run([FF, "-y", "-v", "error", "-i", OUT, "-i", pal, "-lavfi",
                        vf + " [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
                        GIF], check=True)
        print("wrote", GIF)


if __name__ == "__main__":
    main()
