"""Comparing pins against a reference ("master") image.

Two independent checks, both pure numpy so there is no model to download:

* look   – does the picture *resemble* the reference? Combines edge structure
           (orientation histograms), grey-level layout, a coarse colour
           histogram and a perceptual hash (which catches near-duplicates).
* colors – is the picture made of the same main colours, in roughly the same
           amounts? The reference is reduced to a palette (k-means in CIELAB);
           every candidate pixel is assigned to its nearest palette colour.
           Tolerance decides how far each colour's share may drift.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from PIL import Image, ImageOps

ANALYSIS_SIZE = 96


# ── colour space ────────────────────────────────────────────────────────────
def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB uint8 (..., 3) to CIELAB (D65)."""
    c = rgb.astype(np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200
    f = np.stack([fx, fy, fz], axis=-1)
    xyz = np.where(f ** 3 > 216 / 24389, f ** 3, (116 * f - 16) / (24389 / 27))
    xyz = xyz * np.array([0.95047, 1.0, 1.08883])
    m = np.array([[3.2404542, -1.5371385, -0.4985314],
                  [-0.9692660, 1.8760108, 0.0415560],
                  [0.0556434, -0.2040259, 1.0572252]])
    c = np.clip(xyz @ m.T, 0, 1)
    c = np.where(c > 0.0031308, 1.055 * c ** (1 / 2.4) - 0.055, 12.92 * c)
    return np.clip(np.round(c * 255), 0, 255).astype(np.uint8)


# ── loading ─────────────────────────────────────────────────────────────────
def load(src) -> Image.Image:
    """Open a path, bytes or PIL image as a flattened RGB image (first frame)."""
    if isinstance(src, Image.Image):
        im = src
    elif isinstance(src, (bytes, bytearray)):
        im = Image.open(io.BytesIO(src))
    else:
        im = Image.open(src)
    im.seek(0) if getattr(im, "is_animated", False) else None
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    return im.convert("RGB")


def _pixels(im: Image.Image, size: int = ANALYSIS_SIZE) -> np.ndarray:
    small = im.copy()
    small.thumbnail((size, size), Image.Resampling.BILINEAR)
    return np.asarray(small, dtype=np.uint8).reshape(-1, 3)


# ── palette ─────────────────────────────────────────────────────────────────
@dataclass
class Palette:
    lab: np.ndarray            # (k, 3)
    shares: np.ndarray         # (k,) sums to 1

    @property
    def rgb(self) -> np.ndarray:
        return lab_to_rgb(self.lab)

    def hex(self) -> list[str]:
        return ["#{:02x}{:02x}{:02x}".format(*c) for c in self.rgb]

    def entries(self) -> list[tuple[str, float]]:
        return [(h, float(s)) for h, s in zip(self.hex(), self.shares, strict=True)]

    @classmethod
    def from_entries(cls, entries) -> Palette:
        """Build from [(hex, share), ...]; shares are renormalised."""
        rgb = np.array([[int(h[i:i + 2], 16) for i in (1, 3, 5)] for h, _ in entries], dtype=np.uint8)
        shares = np.array([max(float(s), 1e-6) for _, s in entries])
        return cls(lab=rgb_to_lab(rgb), shares=shares / shares.sum())

    def without(self, index: int) -> Palette:
        e = self.entries()
        del e[index]
        return Palette.from_entries(e)

    def plus(self, hex_color: str) -> Palette:
        """Add a colour with an equal slice; the others shrink proportionally."""
        e = self.entries()
        n = len(e)
        e = [(h, s * n / (n + 1)) for h, s in e] + [(hex_color.lower(), 1 / (n + 1))]
        return Palette.from_entries(e)


def _kmeans(x: np.ndarray, k: int, iters: int = 15, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    centers = [x[rng.integers(len(x))]]
    for _ in range(1, k):  # k-means++
        d = np.min(((x[:, None] - np.array(centers)[None]) ** 2).sum(-1), axis=1)
        if d.sum() == 0:
            break
        centers.append(x[rng.choice(len(x), p=d / d.sum())])
    c = np.array(centers)
    for _ in range(iters):
        lbl = ((x[:, None] - c[None]) ** 2).sum(-1).argmin(1)
        new = np.array([x[lbl == i].mean(0) if np.any(lbl == i) else c[i] for i in range(len(c))])
        if np.allclose(new, c, atol=0.1):
            break
        c = new
    return c


def color_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Lab distance with lightness at half weight (CMC-style l:c = 2:1), so
    "same colour" is mostly about hue and saturation, not shading."""
    d = a - b
    return np.sqrt((d[..., 0] / 2) ** 2 + d[..., 1] ** 2 + d[..., 2] ** 2)


def extract_palette(src, k: int = 5, merge_de: float = 10.0, min_share: float = 0.06) -> Palette:
    lab = rgb_to_lab(_pixels(load(src)))
    centers = _kmeans(lab, k)
    # merge near-identical clusters
    merged: list[np.ndarray] = []
    for c in centers:
        if all(color_distance(c, m) >= merge_de for m in merged):
            merged.append(c)
    centers = np.array(merged)
    def assign(cs):
        lbl = color_distance(lab[:, None], cs[None]).argmin(1)
        return lbl, np.bincount(lbl, minlength=len(cs)) / len(lbl)

    for _ in range(3):  # drop slivers and hand their pixels to the neighbours
        lbl, shares = assign(centers)
        keep = shares >= min_share
        keep[shares.argmax()] = True
        if keep.all():
            break
        centers = centers[keep]
    lbl, shares = assign(centers)
    centers = np.array([lab[lbl == i].mean(0) if np.any(lbl == i) else centers[i]
                        for i in range(len(centers))])
    order = np.argsort(-shares)
    return Palette(lab=centers[order], shares=shares[order])


# ── colour matching ─────────────────────────────────────────────────────────
@dataclass
class ColorRule:
    """What a tolerance (0 strict … 100 loose) means in numbers."""
    same_color_de: float      # how far a pixel may be from a palette colour
    max_deviation: float      # allowed absolute change in each colour's share
    max_foreign: float        # share of pixels allowed to be none of the colours
    min_presence: float = 0.02  # main colours must at least appear (sensible floor)


def color_rule(tolerance: float) -> ColorRule:
    t = min(max(tolerance, 0.0), 100.0) / 100.0
    return ColorRule(same_color_de=14 + 14 * t,
                     max_deviation=0.08 + 0.92 * t ** 1.5,
                     max_foreign=0.15 + 0.60 * t)  # loose: backgrounds may differ


def allowed_ranges(pal: Palette, tolerance: float) -> list[tuple[float, float]]:
    r = color_rule(tolerance)
    out = []
    for s in pal.shares:
        lo = max(s - r.max_deviation, r.min_presence if s >= 0.10 else 0.0)
        out.append((lo, min(1.0, s + r.max_deviation)))
    return out


@dataclass
class ColorResult:
    ok: bool
    score: float               # 0..100, how close the colour mix is
    shares: np.ndarray
    foreign: float


def color_match(pal: Palette, src, tolerance: float) -> ColorResult:
    r = color_rule(tolerance)
    lab = rgb_to_lab(_pixels(load(src)))
    d = color_distance(lab[:, None], pal.lab[None])
    nearest = d.argmin(1)
    hit = d[np.arange(len(lab)), nearest] <= r.same_color_de
    shares = np.bincount(nearest[hit], minlength=len(pal.lab)) / len(lab)
    foreign = 1.0 - hit.mean()
    ranges = allowed_ranges(pal, tolerance)
    ok = foreign <= r.max_foreign and all(lo <= s <= hi for s, (lo, hi) in zip(shares, ranges))
    tv = 0.5 * (np.abs(shares - pal.shares).sum() + foreign)
    return ColorResult(ok=bool(ok), score=float(100 * (1 - tv)), shares=shares, foreign=float(foreign))


# ── look-alike matching ─────────────────────────────────────────────────────
@dataclass
class Signature:
    hog: np.ndarray
    layout: np.ndarray
    hist: np.ndarray
    dhash: np.ndarray = field(repr=False)


def signature(src) -> Signature:
    im = load(src)
    sq = ImageOps.fit(im, (ANALYSIS_SIZE, ANALYSIS_SIZE), Image.Resampling.BILINEAR)
    rgb = np.asarray(sq, dtype=np.uint8)
    gray = np.asarray(sq.convert("L"), dtype=np.float64)

    # edge-orientation histogram on a 3x3 grid (HOG-like)
    gy, gx = np.gradient(gray)
    mag = np.hypot(gx, gy)
    ang = (np.arctan2(gy, gx) % np.pi) / np.pi * 9
    bins = np.minimum(ang.astype(int), 8)
    cell = ANALYSIS_SIZE // 3
    hog = np.zeros((3, 3, 9))
    for i in range(3):
        for j in range(3):
            sl = (slice(i * cell, (i + 1) * cell), slice(j * cell, (j + 1) * cell))
            hog[i, j] = np.bincount(bins[sl].ravel(), weights=mag[sl].ravel(), minlength=9)
    hog = np.sqrt(hog.ravel())
    hog /= np.linalg.norm(hog) + 1e-9

    # grey-level layout (composition), contrast-normalised
    lay = np.asarray(sq.convert("L").resize((12, 12), Image.Resampling.BOX), dtype=np.float64).ravel()
    lay -= lay.mean()
    lay /= np.linalg.norm(lay) + 1e-9

    # coarse colour histogram
    lab = rgb_to_lab(rgb.reshape(-1, 3))
    hist, _ = np.histogramdd(lab, bins=(4, 6, 6), range=((0, 100), (-80, 80), (-80, 80)))
    hist = hist.ravel() / hist.sum()

    # difference hash (64 bit) for near-duplicates
    d = np.asarray(im.convert("L").resize((9, 8), Image.Resampling.BOX), dtype=np.int16)
    dh = (d[:, 1:] > d[:, :-1]).ravel()
    return Signature(hog=hog, layout=lay, hist=hist, dhash=dh)


def look_similarity(a: Signature, b: Signature) -> float:
    """0..100. Same-topic photos mostly land around 55-68; near-duplicates 90+."""
    hog = float(a.hog @ b.hog)                       # 0..1
    lay = (float(a.layout @ b.layout) + 1) / 2       # 0..1
    hist = float(np.minimum(a.hist, b.hist).sum())   # 0..1
    ham = float((a.dhash != b.dhash).mean())         # 0..1
    s = 0.40 * hog + 0.25 * lay + 0.20 * hist + 0.15 * (1 - ham)
    if ham <= 0.12:                                  # practically the same picture
        s = max(s, 0.95)
    return 100 * s


def keep_fraction(closeness: float) -> float:
    """How much of the candidate pool 'Looks similar' keeps: closeness 0 keeps
    the best 60 %, 100 keeps only the best 8 %."""
    c = min(max(closeness, 0.0), 100.0) / 100.0
    return 0.60 - 0.52 * c


LOOK_FLOOR = 50.0      # below this nothing counts as "looks similar", however few pass
NEAR_DUPLICATE = 90.0  # always a match


@dataclass
class Score:
    look: Optional[float] = None
    color: Optional[ColorResult] = None

    @property
    def combined(self) -> float:
        parts = [x for x in (self.look, self.color.score if self.color else None) if x is not None]
        return float(np.mean(parts)) if parts else 0.0


# ── putting it together ─────────────────────────────────────────────────────
@dataclass
class MatchSettings:
    reference: Optional[str] = None
    palette: Optional[list] = None   # [(hex, share)]: picked/edited colours win over the picture's
    look: bool = False
    colors: bool = False
    color_tolerance: float = 50.0
    closeness: float = 50.0

    @property
    def active(self) -> bool:
        look = self.look and bool(self.reference)
        colors = self.colors and bool(self.reference or self.palette)
        return look or colors


class Matcher:
    def __init__(self, settings: MatchSettings):
        self.s = settings
        ref = load(settings.reference) if settings.reference else None
        self.palette = None
        if settings.colors:
            self.palette = (Palette.from_entries(settings.palette) if settings.palette
                            else extract_palette(ref) if ref is not None else None)
        self.sig = signature(ref) if settings.look and ref is not None else None

    def score(self, data: bytes) -> Optional[Score]:
        """Raw scores for one candidate, or None if it can't be read."""
        try:
            im = load(data)
        except Exception:
            return None
        sc = Score()
        if self.sig is not None:
            sc.look = look_similarity(self.sig, signature(im))
        if self.palette is not None:
            sc.color = color_match(self.palette, im, self.s.color_tolerance)
        return sc

    def look_cutoff(self, looks: list[float]) -> float:
        """Look scores drift with the search (a 'fortnite' pool scores lower
        than a 'fortnite llama' pool), so "How close" keeps the best share of
        *this* pool rather than using a fixed number."""
        if not looks:
            return LOOK_FLOOR
        q = 1 - keep_fraction(self.s.closeness)
        return max(LOOK_FLOOR, float(np.quantile(looks, q)))

    def select(self, scored: list) -> list:
        """[(item, Score)] -> [(item, combined score)] that pass, best first."""
        cut = self.look_cutoff([sc.look for _, sc in scored if sc.look is not None])
        out = []
        for item, sc in scored:
            if sc.look is not None and not (sc.look >= cut or sc.look >= NEAR_DUPLICATE):
                continue
            if sc.color is not None and not sc.color.ok:
                continue
            out.append((item, sc.combined))
        out.sort(key=lambda t: -t[1])
        return out
