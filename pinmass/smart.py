"""Smart matching: a small CLIP model that understands what a picture shows.

The classic matcher in matching.py compares edges and colours, so it only
finds pictures that are *laid out* like the reference. CLIP turns a picture
(or a sentence) into a 512-number "meaning" vector; two pictures of the same
thing end up close together even when they are drawn differently. That also
makes text work: "watercolor, no text" can be checked against any picture.

The model (CLIP ViT-B/32, 8-bit, about 150 MB) is downloaded once on first
use and runs on the CPU through onnxruntime. Everything here is optional: if
onnxruntime or tokenizers isn't installed the app falls back to the classic
matcher.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PIL import Image

REPO = "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/"
FILES = {  # local name: (remote path, rough size in MB)
    "vision.onnx": ("onnx/vision_model_quantized.onnx", 89),
    "text.onnx": ("onnx/text_model_quantized.onnx", 65),
    "tokenizer.json": ("tokenizer.json", 1),
}
TOTAL_MB = sum(mb for _, mb in FILES.values())
SIZE = 224
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

Progress = Callable[[int, int], None]   # (bytes done, bytes total)


def model_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "PinterestMassDownloader" / "models" / "clip-vit-b32"


def available() -> bool:
    """Are the libraries smart matching needs installed?"""
    try:
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
        return True
    except Exception:
        return False


def installed() -> bool:
    d = model_dir()
    return all((d / name).exists() and (d / name).stat().st_size > 0 for name in FILES)


def download(progress: Optional[Progress] = None, stop: Optional[threading.Event] = None) -> bool:
    """Fetch any missing model files. True when everything is in place."""
    import requests
    d = model_dir()
    d.mkdir(parents=True, exist_ok=True)
    total = sum(mb for name, (_, mb) in FILES.items() if not (d / name).exists()) * 1_000_000
    done = 0
    for name, (remote, _mb) in FILES.items():
        target = d / name
        if target.exists() and target.stat().st_size > 0:
            continue
        tmp = target.with_suffix(target.suffix + ".part")
        try:
            with requests.get(REPO + remote, stream=True, timeout=(8, 60)) as r:
                if r.status_code != 200:
                    return False
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 18):
                        if stop is not None and stop.is_set():
                            raise InterruptedError
                        f.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, max(total, done))
            os.replace(tmp, target)
        except (requests.RequestException, OSError, InterruptedError):
            try:
                tmp.unlink()
            except OSError:
                pass
            return False
    return True


def _unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-9)


def _prepare(im: Image.Image) -> np.ndarray:
    """PIL image → CLIP's (3, 224, 224) float input."""
    im = im.convert("RGB")
    w, h = im.size
    scale = SIZE / min(w, h)
    im = im.resize((max(SIZE, round(w * scale)), max(SIZE, round(h * scale))),
                   Image.Resampling.BICUBIC)
    w, h = im.size
    left, top = (w - SIZE) // 2, (h - SIZE) // 2
    im = im.crop((left, top, left + SIZE, top + SIZE))
    x = (np.asarray(im, dtype=np.float32) / 255.0 - MEAN) / STD
    return x.transpose(2, 0, 1)


class Clip:
    def __init__(self, folder: Optional[Path] = None):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        folder = folder or model_dir()
        opts = ort.SessionOptions()
        # several pictures are scored at once from different threads, so keep
        # each run small instead of letting every run grab every core
        opts.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 4) // 2))
        opts.log_severity_level = 3
        prov = ["CPUExecutionProvider"]
        self.vision = ort.InferenceSession(str(folder / "vision.onnx"), opts, providers=prov)
        self.text_model = ort.InferenceSession(str(folder / "text.onnx"), opts, providers=prov)
        self.tok = Tokenizer.from_file(str(folder / "tokenizer.json"))
        self.tok.no_padding()
        self.tok.enable_truncation(77)
        self._text_inputs = [i.name for i in self.text_model.get_inputs()]
        self._text_cache: dict[str, np.ndarray] = {}
        self._gate = threading.Semaphore(max(2, (os.cpu_count() or 4) // 4))

    def _pick(self, session, outputs: list, name: str) -> np.ndarray:
        names = [o.name for o in session.get_outputs()]
        return outputs[names.index(name)] if name in names else outputs[0]

    def image(self, im: Image.Image) -> np.ndarray:
        """Unit-length meaning vector for one picture."""
        x = _prepare(im)[None]
        with self._gate:
            out = self.vision.run(None, {self.vision.get_inputs()[0].name: x})
        return _unit(self._pick(self.vision, out, "image_embeds")[0].astype(np.float32))

    def text(self, phrase: str) -> np.ndarray:
        """Unit-length meaning vector for a sentence."""
        phrase = " ".join(phrase.lower().split())
        hit = self._text_cache.get(phrase)
        if hit is not None:
            return hit
        ids = np.array([self.tok.encode(phrase).ids], dtype=np.int64)
        feed = {"input_ids": ids}
        if "attention_mask" in self._text_inputs:
            feed["attention_mask"] = np.ones_like(ids)
        with self._gate:
            out = self.text_model.run(None, feed)
        v = _unit(self._pick(self.text_model, out, "text_embeds")[0].astype(np.float32))
        self._text_cache[phrase] = v
        return v


_clip: Optional[Clip] = None
_lock = threading.Lock()


def get(progress: Optional[Progress] = None, stop: Optional[threading.Event] = None) -> Optional[Clip]:
    """The shared model, downloading it first if needed. None if it can't be had."""
    global _clip
    with _lock:
        if _clip is not None:
            return _clip
        if not available():
            return None
        if not installed() and not download(progress, stop):
            return None
        try:
            _clip = Clip()
        except Exception:
            return None
        return _clip


# ── describing what you want in words ───────────────────────────────────────
NEGATIONS = ("no ", "not ", "without ", "-", "non-", "non ")


def parse_description(text: str) -> tuple[list[str], list[str]]:
    """'watercolor, no text, not blurry' → (['watercolor'], ['text', 'blurry'])."""
    wanted: list[str] = []
    unwanted: list[str] = []
    for part in text.replace(";", ",").replace("\n", ",").split(","):
        part = " ".join(part.split())
        low = part.lower()
        for neg in NEGATIONS:
            if low.startswith(neg) and len(part) > len(neg):
                unwanted.append(part[len(neg):].strip())
                break
        else:
            if part:
                wanted.append(part)
    return wanted, unwanted
