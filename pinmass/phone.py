"""Phone gallery: browse and share the download folder from a phone on the same Wi-Fi.

Nothing is copied to the phone. The PC serves a small web app; pictures are
streamed when viewed and handed to the phone's share sheet (Instagram,
WhatsApp, …) only when you tap Share.

* HTTP  (default port 8765): opens with no warnings. Long-press a picture to share it.
* HTTPS (port 8766, self-signed): browsers only allow the one-tap Share/Copy
  buttons on secure pages, so the app offers to switch. Expect one
  "connection not private" warning the first time.

Access needs a secret token (part of the QR code / link), so other devices
on the network can't browse your folder.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import io
import json
import mimetypes
import os
import secrets
import socket
import ssl
import subprocess
import threading
import urllib.parse
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image, ImageOps

from .media import find_ffmpeg

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v"}
MEDIA_EXT = IMAGE_EXT | VIDEO_EXT
THUMB = 360
PAGE = Path(__file__).with_name("phone_page.html")


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    p = Path(base) / "PinterestMassDownloader"
    p.mkdir(parents=True, exist_ok=True)
    return p


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def kind(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXT:
        return "video"
    return "gif" if ext == ".gif" else "image"


# ── certificate ─────────────────────────────────────────────────────────────
def ensure_cert() -> tuple[str, str] | None:
    """Self-signed cert for the LAN IP, created once and reused."""
    d = data_dir()
    crt, key = d / "phone_cert.pem", d / "phone_key.pem"
    ip = lan_ip()
    marker = d / "phone_cert.ip"
    if crt.exists() and key.exists() and marker.exists() and marker.read_text() == ip:
        return str(crt), str(key)
    try:
        import ipaddress

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
    except ImportError:
        return None
    k = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Pinterest Mass Downloader")])
    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(k.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - _dt.timedelta(days=1))
            .not_valid_after(now + _dt.timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address(ip)), x509.DNSName("localhost")]),
                critical=False)
            .sign(k, hashes.SHA256()))
    key.write_bytes(k.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    marker.write_text(ip)
    return str(crt), str(key)


# ── library ─────────────────────────────────────────────────────────────────
class Library:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.thumbs = data_dir() / "thumbs"
        self.thumbs.mkdir(exist_ok=True)

    def resolve(self, rel: str) -> str | None:
        """Absolute path for *rel*, or None if it escapes the root or isn't media."""
        rel = urllib.parse.unquote(rel).replace("\\", "/").lstrip("/")
        path = os.path.abspath(os.path.join(self.root, rel))
        try:
            if os.path.commonpath([path, self.root]) != self.root:
                return None
        except ValueError:
            return None
        return path

    def _entry(self, path: str) -> dict:
        st = os.stat(path)
        rel = os.path.relpath(path, self.root).replace("\\", "/")
        return {"path": rel, "name": os.path.basename(path), "kind": kind(path),
                "size": st.st_size, "mtime": st.st_mtime}

    def _media(self, folder: str, recursive: bool):
        if recursive:
            for dp, dirs, files in os.walk(folder):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for f in files:
                    if os.path.splitext(f)[1].lower() in MEDIA_EXT:
                        yield os.path.join(dp, f)
        else:
            try:
                with os.scandir(folder) as it:
                    for e in it:
                        if e.is_file() and os.path.splitext(e.name)[1].lower() in MEDIA_EXT:
                            yield e.path
            except OSError:
                return

    def albums(self) -> list[dict]:
        out = []
        everything = sorted(self._media(self.root, True), key=os.path.getmtime, reverse=True)
        out.append({"id": "", "name": "Recent", "count": len(everything),
                    "cover": self._entry(everything[0])["path"] if everything else None})
        try:
            subs = [e for e in os.scandir(self.root) if e.is_dir() and not e.name.startswith(".")]
        except OSError:
            subs = []
        for d in sorted(subs, key=lambda e: e.stat().st_mtime, reverse=True):
            files = sorted(self._media(d.path, True), key=os.path.getmtime, reverse=True)
            if files:
                out.append({"id": d.name, "name": d.name, "count": len(files),
                            "cover": self._entry(files[0])["path"]})
        return out

    def items(self, album: str) -> list[dict]:
        folder = self.root if not album else self.resolve(album)
        if not folder or not os.path.isdir(folder):
            return []
        files = sorted(self._media(folder, True), key=os.path.getmtime, reverse=True)[:5000]
        return [self._entry(f) for f in files]

    def thumb(self, path: str) -> bytes | None:
        st = os.stat(path)
        key = hashlib.sha1(f"{path}|{st.st_mtime}|{st.st_size}".encode()).hexdigest()
        cached = self.thumbs / f"{key}.jpg"
        if cached.exists():
            return cached.read_bytes()
        im = None
        try:
            if kind(path) == "video":
                ff = find_ffmpeg()
                if ff:
                    r = subprocess.run([ff, "-nostdin", "-v", "error", "-ss", "0.5", "-i", path,
                                        "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                                       capture_output=True, timeout=20,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    if r.stdout:
                        im = Image.open(io.BytesIO(r.stdout))
            else:
                im = Image.open(path)
                im.draft("RGB", (THUMB * 2, THUMB * 2))
            if im is None:
                return None
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((THUMB, THUMB * 2), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=80, optimize=True)
            data = buf.getvalue()
            cached.write_bytes(data)
            return data
        except Exception:
            return None


# ── HTTP ────────────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    server_version = "PinterestMassDownloader"
    lib: Library
    token: str
    https_url: str | None = None

    def log_message(self, *_):  # keep the console quiet
        pass

    def _authed(self, query: dict) -> bool:
        t = (query.get("t") or [""])[0]
        if t and hmac.compare_digest(t, self.token):
            return True
        c = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return "pmd" in c and hmac.compare_digest(c["pmd"].value, self.token)

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj):
        self._send(200, json.dumps(obj).encode(), "application/json", {"Cache-Control": "no-store"})

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(url.query)
        if not self._authed(q):
            self._send(403, LOCKED.encode(), "text/html; charset=utf-8")
            return
        path = url.path
        if path in ("/", "/index.html"):
            html = PAGE.read_text(encoding="utf-8").replace(
                "__HTTPS_URL__", json.dumps(f"{self.https_url}/?t={self.token}" if self.https_url else ""))
            extra = {"Cache-Control": "no-store"}
            if "t" in q:
                extra["Set-Cookie"] = (f"pmd={self.token}; Path=/; Max-Age=31536000; "
                                       "HttpOnly; SameSite=Strict")
            self._send(200, html.encode(), "text/html; charset=utf-8", extra)
        elif path == "/api/albums":
            self._json({"root": self.lib.root, "albums": self.lib.albums()})
        elif path == "/api/items":
            self._json({"items": self.lib.items((q.get("album") or [""])[0])})
        elif path.startswith("/thumb/"):
            f = self.lib.resolve(path[len("/thumb/"):])
            data = self.lib.thumb(f) if f and os.path.isfile(f) else None
            if data:
                self._send(200, data, "image/jpeg", {"Cache-Control": "private, max-age=86400"})
            else:
                self._send(404, b"", "text/plain")
        elif path.startswith("/file/"):
            f = self.lib.resolve(path[len("/file/"):])
            if f and os.path.isfile(f) and os.path.splitext(f)[1].lower() in MEDIA_EXT:
                self._file(f, "dl" in q)
            else:
                self._send(404, b"", "text/plain")
        else:
            self._send(404, b"", "text/plain")

    def _file(self, path: str, download: bool):
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):  # iOS needs ranges to play video
            a, _, b = rng[6:].split(",")[0].partition("-")
            try:
                if a:
                    start, end = int(a), (int(b) if b else size - 1)
                else:
                    start = max(0, size - int(b))
                end = min(end, size - 1)
            except ValueError:
                start, end = 0, size - 1
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "private, max-age=86400")
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download:
            name = urllib.parse.quote(os.path.basename(path))
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{name}")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = fh.read(min(262144, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (ConnectionError, OSError):
            pass


LOCKED = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>Locked</title><body style="font:16px system-ui;background:#0e0e11;color:#eee;
display:grid;place-items:center;height:90vh;text-align:center">
<div><div style="font-size:48px">🔒</div><p>Scan the QR code shown in<br>
<b>Pinterest Mass Downloader → Phone</b> on your PC.</p></div>"""


class PhoneServer:
    """Runs the gallery on a background thread. Call start()/stop()."""

    def __init__(self, folder: str, token: str, port: int = 8765, https: bool = True):
        self.folder = folder
        self.token = token
        self.port = port
        self.want_https = https
        self._servers: list[ThreadingHTTPServer] = []
        self.ip = lan_ip()

    @property
    def url(self) -> str:
        return f"http://{self.ip}:{self.port}/?t={self.token}"

    @property
    def https_url(self) -> str | None:
        return f"https://{self.ip}:{self.port + 1}/?t={self.token}" if len(self._servers) > 1 else None

    @property
    def running(self) -> bool:
        return bool(self._servers)

    def start(self):
        if self._servers:
            return
        lib = Library(self.folder)
        https_base = f"https://{self.ip}:{self.port + 1}"
        cert = ensure_cert() if self.want_https else None
        attrs = {"lib": lib, "token": self.token, "https_url": https_base if cert else None}
        handler = type("H", (Handler,), attrs)
        http = ThreadingHTTPServer(("0.0.0.0", self.port), handler)
        self._servers.append(http)
        if cert:
            try:
                tls = ThreadingHTTPServer(("0.0.0.0", self.port + 1), handler)
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ctx.load_cert_chain(*cert)
                tls.socket = ctx.wrap_socket(tls.socket, server_side=True)
                self._servers.append(tls)
            except (OSError, ssl.SSLError):
                pass
        for s in self._servers:
            s.daemon_threads = True
            threading.Thread(target=s.serve_forever, daemon=True).start()

    def stop(self):
        for s in self._servers:
            s.shutdown()
            s.server_close()
        self._servers.clear()


def new_token() -> str:
    return secrets.token_urlsafe(12)


def qr_image(text: str, box: int = 8):
    import qrcode
    q = qrcode.QRCode(border=2, box_size=box)
    q.add_data(text)
    q.make(fit=True)
    return q.make_image(fill_color="black", back_color="white").get_image().convert("RGB")


def serve_forever(folder: str, port: int = 8765):
    """CLI entry: python pinterest_downloader.py --phone D:\\Pinterest"""
    from . import settings
    cfg = settings.load()
    if not cfg.get("phone_token"):
        cfg["phone_token"] = new_token()
        settings.save(cfg)
    srv = PhoneServer(folder, cfg["phone_token"], port)
    srv.start()
    print(f"Sharing {os.path.abspath(folder)}")
    print(f"On your phone (same Wi-Fi) open:\n  {srv.url}")
    try:
        q = qr_image(srv.url)
        small = q.resize((q.width // 8, q.height // 8), Image.Resampling.NEAREST)
        px = small.load()
        for y in range(0, small.height, 2):
            row = ""
            for x in range(small.width):
                # print the light modules: terminals are dark, so this reads correctly
                top = px[x, y][0] >= 128
                bot = y + 1 >= small.height or px[x, y + 1][0] >= 128
                row += {(True, True): "█", (True, False): "▀", (False, True): "▄"}.get((top, bot), " ")
            print("  " + row)
    except Exception:
        pass
    print("Press Ctrl+C to stop.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.stop()
