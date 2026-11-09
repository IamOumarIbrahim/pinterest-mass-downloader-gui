"""Downloading files and checking that each one really is the type asked for."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import threading
from typing import Optional

import requests

from .scraper import USER_AGENT, Pin

DL_HEADERS = {"User-Agent": USER_AGENT, "Referer": "https://www.pinterest.com/"}
MAX_THUMB_BYTES = 4 * 1024 * 1024

_local = threading.local()


def _session() -> requests.Session:
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers.update(DL_HEADERS)
    return _local.s


def sniff(head: bytes) -> Optional[str]:
    """Container type from a file's first bytes: jpg/png/webp/gif/mp4/ts or None."""
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[4:8] == b"ftyp":
        return "mp4"
    if head[:1] == b"\x47" and len(head) > 188 and head[188:189] == b"\x47":
        return "ts"
    return None


def kind_of(path: str) -> Optional[str]:
    """'image', 'gif' (animated only) or 'video' for a file on disk."""
    try:
        with open(path, "rb") as f:
            head = f.read(512)
    except OSError:
        return None
    fmt = sniff(head)
    if fmt in ("jpg", "png", "webp"):
        if fmt == "webp" and _is_animated(path):
            return "gif"
        return "image"
    if fmt == "gif":
        return "gif" if _is_animated(path) else "image"
    if fmt in ("mp4", "ts"):
        return "video"
    return None


def _is_animated(path: str) -> bool:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return getattr(im, "n_frames", 1) > 1
    except Exception:
        return False


def fetch_bytes(url: str, limit: int = MAX_THUMB_BYTES, timeout: float = 15) -> Optional[bytes]:
    try:
        with _session().get(url, timeout=timeout, stream=True) as r:
            if r.status_code != 200:
                return None
            buf = io.BytesIO()
            for chunk in r.iter_content(65536):
                buf.write(chunk)
                if buf.tell() > limit:
                    return None
            return buf.getvalue()
    except requests.RequestException:
        return None


def _stream_to(url: str, path: str, stop: threading.Event) -> bool:
    tmp = path + ".part"
    try:
        with _session().get(url, timeout=30, stream=True) as r:
            if r.status_code != 200:
                return False
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(65536):
                    if stop.is_set():
                        raise InterruptedError
                    f.write(chunk)
        os.replace(tmp, path)
        return True
    except (requests.RequestException, OSError, InterruptedError):
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False


def find_ffmpeg() -> Optional[str]:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _hls_to_mp4(url: str, path: str) -> bool:
    ff = find_ffmpeg()
    if not ff:
        return False
    tmp = path + ".part.mp4"
    hdr = "".join(f"{k}: {v}\r\n" for k, v in DL_HEADERS.items())
    try:
        r = subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-headers", hdr, "-i", url,
                            "-c", "copy", "-bsf:a", "aac_adtstoasc", tmp],
                           capture_output=True, timeout=300,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode == 0 and os.path.getsize(tmp) > 0:
            os.replace(tmp, path)
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    if os.path.exists(tmp):
        os.remove(tmp)
    return False


EXT = {"jpg": ".jpg", "png": ".png", "webp": ".webp", "gif": ".gif", "mp4": ".mp4", "ts": ".ts"}


def existing_file(pin: Pin, out_dir: str, want: str) -> Optional[str]:
    exts = {"image": (".jpg", ".png", ".webp"), "gif": (".gif", ".webp"),
            "video": (".mp4",)}[want]
    for ext in exts:
        p = os.path.join(out_dir, pin.id + ext)
        if os.path.exists(p) and os.path.getsize(p) > 0:
            return p
    return None


def download(pin: Pin, out_dir: str, want: str, stop: threading.Event) -> Optional[str]:
    """Save *pin* as *want* ('image' | 'gif' | 'video'). Returns the path, or
    None if it failed or turned out to be a different type (the file is removed:
    asking for videos only must never leave pictures in the folder)."""
    have = existing_file(pin, out_dir, want)
    if have:
        return have
    url = pin.video_url if want == "video" else pin.src
    if not url:
        return None
    base = os.path.join(out_dir, pin.id)
    tmp = base + ".download"
    is_hls = want == "video" and url.split("?")[0].lower().endswith(".m3u8")
    ok = _hls_to_mp4(url, tmp) if is_hls else _stream_to(url, tmp, stop)
    if not ok:
        return None
    if kind_of(tmp) != want:
        os.remove(tmp)
        return None
    with open(tmp, "rb") as f:
        fmt = sniff(f.read(512))
    final = base + EXT.get(fmt, ".bin")
    if want == "video" and fmt == "ts":
        final = base + ".mp4" if _remux_ts(tmp, base + ".mp4") else base + ".ts"
        if final.endswith(".mp4"):
            os.remove(tmp)
            return final
    os.replace(tmp, final)
    return final


def _remux_ts(src: str, dst: str) -> bool:
    ff = find_ffmpeg()
    if not ff:
        return False
    try:
        r = subprocess.run([ff, "-nostdin", "-v", "error", "-y", "-i", src, "-c", "copy", dst],
                           capture_output=True, timeout=300,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
