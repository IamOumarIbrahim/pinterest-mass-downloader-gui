"""Finding pins: pinterest-dl first, a built-in unauthenticated scraper as fallback."""

from __future__ import annotations

import json
import re
import threading
import urllib.parse
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
API_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/javascript, */*, q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "X-Pinterest-AppState": "active",
    "Referer": "https://www.pinterest.com/",
}
# Direct MP4 variants first; HLS (.m3u8) only as a last resort.
VIDEO_QUALITIES = ("V_1080P", "V_720P", "V_EXP7", "V_480P", "V_EXP6",
                   "V_EXP5", "V_EXP4", "V_EXP3")

Log = Callable[[str, str], None]


@dataclass
class Pin:
    """Everything we need to know about one pin."""
    id: str
    src: str                       # full-size image (or GIF / video cover)
    title: str = ""
    video_url: Optional[str] = None

    @property
    def kind(self) -> str:
        return classify(self.src, self.video_url)

    @property
    def thumb(self) -> str:
        return thumb_url(self.src)


def is_url(text: str) -> bool:
    return bool(re.match(r"https?://([a-z]+\.)?pinterest\.[a-z.]+/", text.strip(), re.I)
                or re.match(r"https?://pin\.it/", text.strip(), re.I))


def classify(src: str, video_url: Optional[str]) -> str:
    """'gif', 'video' or 'image'. GIF wins over video: Pinterest attaches an MP4
    rendition to most GIF pins, but the user asking for GIFs wants the .gif."""
    path = (src or "").split("?")[0].lower()
    if path.endswith(".gif"):
        return "gif"
    if video_url:
        return "video"
    return "image"


def thumb_url(src: str) -> str:
    """Small (236px) rendition of a pinimg URL, used for fast matching."""
    return re.sub(r"(i\.pinimg\.com/)(originals|\d+x(\d+)?)/", r"\g<1>236x/", src or "")


def _best_image(item: dict) -> Optional[str]:
    images = item.get("images") or {}
    for key in ("orig", "originals", "736x", "474x"):
        url = (images.get(key) or {}).get("url")
        if url:
            return url
    return item.get("image_large_url")


def _best_video(item: dict) -> Optional[str]:
    v_data = item.get("videos")
    if not v_data:
        pages = (item.get("story_pin_data") or {}).get("pages") or []
        if pages and isinstance(pages, list):
            blocks = pages[0].get("blocks") or []
            if blocks and isinstance(blocks, list):
                v_data = blocks[0].get("video")
    if not isinstance(v_data, dict):
        return None
    v_list = v_data.get("video_list") or {}
    for qual in VIDEO_QUALITIES:
        url = (v_list.get(qual) or {}).get("url")
        if url:
            return url
    urls = [v.get("url") for v in v_list.values() if isinstance(v, dict) and v.get("url")]
    mp4s = [u for u in urls if u.split("?")[0].endswith(".mp4")]
    return (mp4s or urls or [None])[0]


def parse_item(item: dict) -> Optional[Pin]:
    if not isinstance(item, dict) or not item.get("id"):
        return None
    src = _best_image(item)
    if not src:
        return None
    return Pin(
        id=str(item["id"]),
        src=src,
        title=item.get("grid_title") or item.get("title") or item.get("description") or "",
        video_url=_best_video(item),
    )


def _paged(endpoint: str, source_url: str, options: dict, count: int,
           stop: Optional[threading.Event]) -> list[Pin]:
    pins: list[Pin] = []
    seen: set[str] = set()
    bookmarks = None
    session = requests.Session()
    misses = 0
    while len(pins) < count and not (stop and stop.is_set()):
        opts = dict(options, page_size=25)
        if bookmarks:
            opts["bookmarks"] = bookmarks
        params = {"source_url": source_url,
                  "data": json.dumps({"options": opts, "context": {}})}
        try:
            resp = session.get(endpoint, params=params, headers=API_HEADERS, timeout=15)
            if resp.status_code != 200:
                break
            payload = resp.json()
        except (requests.RequestException, ValueError):
            break
        rr = payload.get("resource_response") or {}
        data = rr.get("data") or {}
        results = data.get("results") if isinstance(data, dict) else data
        if not results:
            break
        new = 0
        for item in results:
            pin = parse_item(item)
            if pin and pin.id not in seen:
                seen.add(pin.id)
                pins.append(pin)
                new += 1
        misses = misses + 1 if new == 0 else 0
        bookmarks = (data.get("bookmarks") if isinstance(data, dict) else None) or rr.get("bookmark")
        if isinstance(bookmarks, str):
            bookmarks = [bookmarks]
        if not bookmarks or bookmarks == ["-end-"] or misses >= 3:
            break
    return pins[:count]


def search_keyword(query: str, count: int, stop: Optional[threading.Event] = None) -> list[Pin]:
    return _paged("https://www.pinterest.com/resource/BaseSearchResource/get/",
                  f"/search/pins/?q={urllib.parse.quote(query)}",
                  {"query": query, "scope": "pins"}, count, stop)


def _resolve_short(url: str) -> str:
    if "pin.it/" not in url:
        return url
    try:
        return requests.head(url, allow_redirects=True, timeout=10,
                             headers={"User-Agent": USER_AGENT}).url
    except requests.RequestException:
        return url


def scrape_url(url: str, count: int, stop: Optional[threading.Event] = None) -> list[Pin]:
    url = _resolve_short(url.strip())
    pin_match = re.search(r"/pin/(\d+)", url)
    if pin_match:
        pin_id = pin_match.group(1)
        params = {"source_url": f"/pin/{pin_id}/",
                  "data": json.dumps({"options": {"id": pin_id, "field_set_key": "detailed"},
                                      "context": {}})}
        try:
            resp = requests.get("https://www.pinterest.com/resource/PinResource/get/",
                                params=params, headers=API_HEADERS, timeout=15)
            pin = parse_item((resp.json().get("resource_response") or {}).get("data") or {})
            return [pin] if pin else []
        except (requests.RequestException, ValueError):
            return []

    parts = [p for p in urllib.parse.urlparse(url).path.split("/") if p]
    if len(parts) < 2:
        return []
    username, board = parts[0], parts[1]
    return _paged("https://www.pinterest.com/resource/BoardFeedResource/get/",
                  f"/{username}/{board}/",
                  {"board_slug": board, "username": username}, count, stop)


# ── pinterest-dl adapter ────────────────────────────────────────────────────
def _from_pdl(media) -> Optional[Pin]:
    src = getattr(media, "src", None)
    if not src:
        return None
    vs = getattr(media, "video_stream", None)
    # pinterest-dl stores a VideoStreamInfo object, not a URL string.
    video_url = getattr(vs, "url", None) if vs is not None and not isinstance(vs, str) else vs
    return Pin(id=str(getattr(media, "id", "") or abs(hash(src))), src=src,
               title=getattr(media, "alt", "") or "", video_url=video_url)


def find_pins(query: str, count: int, stop: Optional[threading.Event] = None,
              log: Optional[Log] = None) -> list[Pin]:
    """Collect up to *count* unique pins for a keyword or Pinterest URL."""
    log = log or (lambda m, lvl="info": None)
    mode_url = is_url(query)
    pins: list[Pin] = []

    # The built-in scraper keeps direct MP4 links, which download faster and
    # need no ffmpeg, so try it first and top up with pinterest-dl.
    try:
        pins = scrape_url(query, count, stop) if mode_url else search_keyword(query, count, stop)
    except Exception as exc:  # network weirdness should never kill the run
        log(f"Built-in scraper failed: {exc}", "warning")

    if len(pins) < count and not (stop and stop.is_set()):
        try:
            from pinterest_dl import PinterestDL
            client = PinterestDL.with_api(timeout=15, verbose=False)
            raw = (client.scrape(url=query, num=count) if mode_url
                   else client.search(query=query, num=count, min_resolution=(0, 0)))
            pins = merge(pins, filter(None, (_from_pdl(m) for m in raw or [])))
        except Exception as exc:
            if not pins:
                log(f"pinterest-dl couldn't help either ({exc}).", "warning")
    return pins[:count]


def merge(existing: Iterable[Pin], more: Iterable[Pin]) -> list[Pin]:
    out = list(existing)
    seen = {p.id for p in out}
    for p in more:
        if p.id not in seen:
            seen.add(p.id)
            out.append(p)
    return out
