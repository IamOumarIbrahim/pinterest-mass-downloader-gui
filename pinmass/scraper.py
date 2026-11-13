"""Finding pins on Pinterest.

Pins are produced as a stream (generators), one results page at a time, so the
rest of the app can start working on the first page while later pages load.
The built-in client talks to Pinterest's web resources directly; pinterest-dl
is kept as a fallback for when that turns up nothing.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass
from itertools import islice
from typing import Callable, Iterable, Iterator, Optional

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
BASE = "https://www.pinterest.com"
API_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/javascript, */*, q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "X-Pinterest-AppState": "active",
    # Pinterest answers "403 Invalid Resource Request" without this one.
    "x-pinterest-pws-handler": "www/pin/[id].js",
    "Referer": BASE + "/",
}
# Direct MP4 variants first; HLS (.m3u8) only as a last resort.
VIDEO_QUALITIES = ("V_1080P", "V_720P", "V_EXP7", "V_480P", "V_EXP6",
                   "V_EXP5", "V_EXP4", "V_EXP3")
PAGE_SIZE = 50  # the most Pinterest hands out per request

Log = Callable[[str, str], None]


class ScrapeError(Exception):
    """Pinterest refused or couldn't be reached. *status* is the HTTP code (0 = network)."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


@dataclass
class Pin:
    """Everything we need to know about one pin."""
    id: str
    src: str                       # full-size image (or GIF / video cover)
    title: str = ""
    video_url: Optional[str] = None
    width: int = 0                 # of the original image; 0 = unknown
    height: int = 0
    sig: str = ""                  # Pinterest's hash of the image: same picture, same sig
    alt: str = ""                  # Pinterest's own description of what the picture shows
    link: str = ""

    @property
    def kind(self) -> str:
        return classify(self.src, self.video_url)

    @property
    def thumb(self) -> str:
        return thumb_url(self.src)

    @property
    def key(self) -> str:
        """Identity of the picture itself: reposts of one image share it."""
        return self.sig or self.id


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
    return resized(src, "236x")


def resized(src: str, size: str) -> str:
    """Pinterest's *size* ('236x', '474x', '736x') rendition of a pinimg URL.
    Resized stills are always JPEGs, whatever the original's format."""
    url = re.sub(r"(i\.pinimg\.com/)(originals|\d+x(\d+)?)/", rf"\g<1>{size}/", src or "")
    return re.sub(r"\.(png|webp|jpeg)(?=$|\?)", ".jpg", url, flags=re.I) if url != src else url


def _best_image(item: dict) -> tuple[Optional[str], int, int]:
    images = item.get("images") or {}
    for key in ("orig", "originals", "736x", "474x"):
        im = images.get(key) or {}
        if im.get("url"):
            return im["url"], int(im.get("width") or 0), int(im.get("height") or 0)
    return item.get("image_large_url"), 0, 0


def _video_lists(item: dict) -> Iterator[dict]:
    v = item.get("videos")
    if isinstance(v, dict) and isinstance(v.get("video_list"), dict):
        yield v["video_list"]
    for page in (item.get("story_pin_data") or {}).get("pages") or []:
        for block in (page or {}).get("blocks") or []:
            v = (block or {}).get("video")
            if isinstance(v, dict) and isinstance(v.get("video_list"), dict):
                yield v["video_list"]


def _best_video(item: dict) -> Optional[str]:
    for v_list in _video_lists(item):
        for qual in VIDEO_QUALITIES:
            url = (v_list.get(qual) or {}).get("url")
            if url:
                return url
        urls = [v.get("url") for v in v_list.values() if isinstance(v, dict) and v.get("url")]
        mp4s = [u for u in urls if u.split("?")[0].endswith(".mp4")]
        if mp4s or urls:
            return (mp4s or urls)[0]
    return None


def parse_item(item: dict) -> Optional[Pin]:
    if not isinstance(item, dict) or not item.get("id") or item.get("is_promoted"):
        return None
    src, width, height = _best_image(item)
    if not src:
        return None
    pin_id = str(item["id"])
    return Pin(
        id=pin_id,
        src=src,
        title=(item.get("grid_title") or item.get("title") or item.get("description") or "").strip(),
        video_url=_best_video(item),
        width=width,
        height=height,
        sig=item.get("image_signature") or "",
        alt=(item.get("auto_alt_text") or item.get("seo_alt_text") or "").strip(),
        link=f"{BASE}/pin/{pin_id}/",
    )


# ── HTTP client ─────────────────────────────────────────────────────────────
def _wait(seconds: float, stop: Optional[threading.Event]) -> bool:
    """Sleep, waking early if stopped. True when stopped."""
    if stop is not None:
        return stop.wait(seconds)
    time.sleep(seconds)
    return False


class Client:
    """One Pinterest web session: cookies, the headers Pinterest insists on,
    and patience with rate limits."""

    RETRIES = 4

    def __init__(self, cookies: Optional[dict] = None):
        self.cookies = cookies
        self._session: Optional[requests.Session] = None
        self._lock = threading.Lock()

    def session(self, fresh: bool = False) -> requests.Session:
        with self._lock:
            if self._session is None or fresh:
                s = requests.Session()
                s.headers.update(API_HEADERS)
                if self.cookies:
                    s.cookies.update(self.cookies)
                    if self.cookies.get("csrftoken"):
                        s.headers["X-CSRFToken"] = self.cookies["csrftoken"]
                else:
                    try:  # anonymous visitors get their session cookies from the home page
                        s.get(BASE + "/", timeout=15, headers={"Accept": "text/html"})
                    except requests.RequestException as exc:
                        raise ScrapeError(f"Couldn't reach Pinterest ({exc.__class__.__name__}). "
                                          "Check your internet connection.") from exc
                self._session = s
            return self._session

    def get(self, resource: str, options: dict, source_url: str = "/",
            stop: Optional[threading.Event] = None) -> tuple[object, Optional[str]]:
        """One resource call. Returns (data, bookmark for the next page)."""
        params = {"source_url": source_url,
                  "data": json.dumps({"options": options, "context": {}}),
                  "_": str(int(time.time() * 1000))}
        url = f"{BASE}/resource/{resource}/get/"
        fresh = False
        last = ScrapeError("Pinterest didn't answer.")
        for attempt in range(self.RETRIES):
            if stop is not None and stop.is_set():
                break
            try:
                resp = self.session(fresh).get(url, params=params, timeout=20)
            except requests.RequestException as exc:
                last = ScrapeError(f"Network problem talking to Pinterest ({exc.__class__.__name__}).")
                if _wait(1.5 * (attempt + 1), stop):
                    break
                continue
            fresh = False
            code = resp.status_code
            if code == 200:
                try:
                    rr = resp.json().get("resource_response") or {}
                except ValueError:
                    last = ScrapeError("Pinterest sent something that isn't data (it may be "
                                       "showing a login or robot check).", code)
                    continue
                return rr.get("data"), rr.get("bookmark")
            if code == 404:
                raise ScrapeError("Pinterest says that doesn't exist (or it's private).", 404)
            if code == 429 or code >= 500:
                try:
                    delay = float(resp.headers.get("Retry-After", ""))
                except ValueError:
                    delay = 2.0 * 2 ** attempt
                last = ScrapeError("Pinterest is rate-limiting this PC. Wait a few minutes "
                                   "and try again." if code == 429
                                   else f"Pinterest is having trouble (HTTP {code}).", code)
                if _wait(min(delay, 30), stop):
                    break
                continue
            if code in (401, 403):
                # usually a stale session: start a new one once, then give up
                last = ScrapeError("Pinterest refused the request (HTTP 403). It may want "
                                   "a login for this, or has changed its site.", code)
                if attempt >= 1:
                    break
                fresh = True
                continue
            last = ScrapeError(f"Pinterest answered HTTP {code}.", code)
            break
        raise last

    def pages(self, resource: str, options: dict, source_url: str = "/",
              stop: Optional[threading.Event] = None) -> Iterator[list]:
        """Every page of a paged resource, as lists of raw items."""
        bookmark: Optional[str] = None
        seen_marks: set[str] = set()
        while not (stop is not None and stop.is_set()):
            opts = dict(options, page_size=PAGE_SIZE, bookmarks=[bookmark] if bookmark else [])
            data, bookmark = self.get(resource, opts, source_url, stop)
            results = data.get("results") if isinstance(data, dict) else data
            if not results:
                return
            yield [r for r in results if isinstance(r, dict)]
            if not bookmark or bookmark.startswith("-end-") or bookmark in seen_marks:
                return
            seen_marks.add(bookmark)


_client: Optional[Client] = None
_client_lock = threading.Lock()


def client() -> Client:
    global _client
    with _client_lock:
        if _client is None:
            _client = Client()
        return _client


def set_client(c: Optional[Client]) -> None:
    """Swap the shared client (None = make a fresh anonymous one on next use)."""
    global _client
    with _client_lock:
        _client = c


def _pins(pages: Iterable[list]) -> Iterator[Pin]:
    seen: set[str] = set()
    barren = 0
    for page in pages:
        new = 0
        for item in page:
            pin = parse_item(item)
            if pin and pin.id not in seen:
                seen.add(pin.id)
                new += 1
                yield pin
        barren = 0 if new else barren + 1
        if barren >= 3:  # Pinterest sometimes loops over the same results forever
            return


# ── sources ─────────────────────────────────────────────────────────────────
def iter_search(query: str, stop: Optional[threading.Event] = None,
                scope: str = "pins") -> Iterator[Pin]:
    """Search results as they load. scope: 'pins' or 'videos'."""
    source = f"/search/{scope}/?q={urllib.parse.quote(query)}&rs=typed"
    options = {"query": query, "scope": scope, "rs": "typed", "redux_normalize_feed": True,
               "appliedProductFilters": "---", "auto_correction_disabled": False}
    return _pins(client().pages("BaseSearchResource", options, source, stop))


def iter_board(username: str, slug: str, stop: Optional[threading.Event] = None) -> Iterator[Pin]:
    url = f"/{username}/{slug}/"
    board, _ = client().get("BoardResource", {"username": username, "slug": slug,
                                              "field_set_key": "detailed"}, url, stop)
    if not isinstance(board, dict) or not board.get("id"):
        raise ScrapeError("Couldn't open that board (is the link right, and the board public?).", 404)
    options = {"board_id": board["id"], "board_url": url, "currentFilter": -1,
               "field_set_key": "react_grid_pin", "filter_section_pins": True,
               "sort": "default", "layout": "default", "redux_normalize_feed": True}
    return _pins(client().pages("BoardFeedResource", options, url, stop))


def _resolve_short(url: str) -> str:
    if "pin.it/" not in url:
        return url
    try:
        return requests.head(url, allow_redirects=True, timeout=10,
                             headers={"User-Agent": USER_AGENT}).url
    except requests.RequestException:
        return url


def get_pin(pin_id: str, stop: Optional[threading.Event] = None) -> Optional[Pin]:
    data, _ = client().get("PinResource", {"id": pin_id, "field_set_key": "detailed"},
                           f"/pin/{pin_id}/", stop)
    return parse_item(data) if isinstance(data, dict) else None


def iter_section(username: str, slug: str, section: str,
                 stop: Optional[threading.Event] = None) -> Iterator[Pin]:
    """One section (sub-folder) of a board."""
    url = f"/{username}/{slug}/{section}/"
    board, _ = client().get("BoardResource", {"username": username, "slug": slug,
                                              "field_set_key": "detailed"}, f"/{username}/{slug}/", stop)
    if not isinstance(board, dict) or not board.get("id"):
        raise ScrapeError("Couldn't open that board (is the link right, and the board public?).", 404)
    sections, _ = client().get("BoardSectionsResource", {"board_id": board["id"]}, url, stop)
    want = section.lower()
    match = next((s for s in sections or [] if isinstance(s, dict) and want in (
        str(s.get("slug", "")).lower(), str(s.get("title", "")).lower().replace(" ", "-"))), None)
    if not match:
        raise ScrapeError(f"That board has no section called “{section}”.", 404)
    options = {"section_id": match["id"], "field_set_key": "react_grid_pin",
               "redux_normalize_feed": True}
    return _pins(client().pages("BoardSectionPinsResource", options, url, stop))


def iter_profile(username: str, stop: Optional[threading.Event] = None) -> Iterator[Pin]:
    """Every pin on a profile, across all of its boards."""
    options = {"username": username, "field_set_key": "grid_item", "is_own_profile_pins": False}
    return _pins(client().pages("UserPinsResource", options, f"/{username}/pins/", stop))


# First path segments that are Pinterest's own pages, not user names.
RESERVED = {"search", "pin", "ideas", "explore", "today", "videos", "business", "settings",
            "about", "topics", "login", "signup", "_", "resource", "discover", "categories"}
PROFILE_TABS = {"pins", "_saved", "_created", "_pins", "boards", "_profile"}
LINK_NAMES = {"pin": "Single pin", "board": "Board", "section": "Board section",
              "profile": "Profile: every pin on it", "search": "Search link"}


def parse_link(url: str) -> tuple[str, dict]:
    """What a Pinterest address points at: ('board', {...}), ('section', …),
    ('profile', …), ('search', …), ('pin', …) or ('unknown', {})."""
    u = urllib.parse.urlparse(url.strip())
    parts = [urllib.parse.unquote(p) for p in u.path.split("/") if p]
    if not parts:
        return "unknown", {}
    head = parts[0].lower()
    if head == "pin" and len(parts) > 1:
        return "pin", {"id": parts[1].rsplit("--", 1)[-1]}   # /pin/some-title--12345/
    if head == "search":
        term = " ".join((urllib.parse.parse_qs(u.query).get("q") or [""])[0].split())
        scope = "videos" if parts[1:2] == ["videos"] else "pins"
        return ("search", {"query": term, "scope": scope}) if term else ("unknown", {})
    if head in ("ideas", "explore") and len(parts) > 1:
        return "search", {"query": parts[1].replace("-", " "), "scope": "pins"}
    if head in RESERVED:
        return "unknown", {}
    if len(parts) == 1 or parts[1].lower() in PROFILE_TABS:
        return "profile", {"username": parts[0]}
    if len(parts) == 2:
        return "board", {"username": parts[0], "slug": parts[1]}
    return "section", {"username": parts[0], "slug": parts[1], "section": parts[2]}


def link_name(url: str) -> str:
    """A short human name for a link, e.g. for a folder: 'someone travel-ideas'."""
    kind, p = parse_link(url)
    if kind == "search":
        return p["query"]
    if kind == "pin":
        return f"pin {p['id']}"
    return " ".join(p.values()) if p else "pinterest"


def iter_url(url: str, stop: Optional[threading.Event] = None) -> Iterator[Pin]:
    url = _resolve_short(url.strip())
    kind, p = parse_link(url)
    if kind == "pin":
        pin = get_pin(p["id"], stop)
        if pin:
            yield pin
    elif kind == "search":
        yield from iter_search(p["query"], stop, p["scope"])
    elif kind == "board":
        yield from iter_board(p["username"], p["slug"], stop)
    elif kind == "section":
        yield from iter_section(p["username"], p["slug"], p["section"], stop)
    elif kind == "profile":
        yield from iter_profile(p["username"], stop)
    else:
        raise ScrapeError("That link isn't a board, profile, search or pin. Open the page "
                          "on Pinterest and copy the address from there.")


# ── signing in with your browser's cookies ──────────────────────────────────
def read_cookies(path: str) -> dict:
    """Pinterest cookies from a browser export: a Netscape cookies.txt, or the
    JSON that cookie-export extensions write. Returns {name: value}."""
    text = open(path, encoding="utf-8-sig", errors="replace").read()
    out: dict[str, str] = {}
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict) and "cookies" in data:
        data = data["cookies"]
    if isinstance(data, dict):
        out = {str(k): str(v) for k, v in data.items() if isinstance(v, (str, int))}
    elif isinstance(data, list):
        for c in data:
            if isinstance(c, dict) and c.get("name") and "pinterest" in str(c.get("domain", "pinterest")):
                out[str(c["name"])] = str(c.get("value", ""))
    else:
        for line in text.splitlines():
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_"):]
            if not line.strip() or line.startswith("#"):
                continue
            f = line.split("\t")
            if len(f) >= 7 and "pinterest" in f[0]:
                out[f[5]] = f[6].strip()
    return out


def signed_in(cookies: Optional[dict]) -> bool:
    """Do these cookies belong to a logged-in Pinterest session?"""
    return bool(cookies) and str(cookies.get("_auth")) == "1" and bool(cookies.get("_pinterest_sess"))


def sign_in(cookies: Optional[dict]) -> None:
    """Use *cookies* for every request from now on (None = browse anonymously)."""
    set_client(Client(cookies) if cookies else None)


def iter_related(pin_id: str, stop: Optional[threading.Event] = None) -> Iterator[Pin]:
    """Pinterest's own "more like this" feed. Pinterest only serves it to
    logged-in sessions, so anonymous use raises ScrapeError (see similar_queries)."""
    options = {"pin_id": pin_id, "context_pin_ids": [], "search_query": "",
               "source": "deep_linking", "top_level_source": "deep_linking",
               "top_level_source_depth": 1, "is_pdp": False}
    return _pins(client().pages("RelatedModulesResource", options, f"/pin/{pin_id}/", stop))


def similar_queries(pin: Pin, original: str = "") -> list[str]:
    """Search phrases that describe *pin*, most specific first: Pinterest's
    description of the picture, its title, then the search it came from."""
    out: list[str] = []
    for text in (pin.alt, pin.title, original):
        text = " ".join((text or "").split())[:120]
        if len(text) >= 3 and not is_url(text) and text.lower() not in (t.lower() for t in out):
            out.append(text)
    return out


# ── pinterest-dl adapter ────────────────────────────────────────────────────
def _from_pdl(media) -> Optional[Pin]:
    src = getattr(media, "src", None)
    if not src:
        return None
    vs = getattr(media, "video_stream", None)
    # pinterest-dl stores a VideoStreamInfo object, not a URL string.
    video_url = getattr(vs, "url", None) if vs is not None and not isinstance(vs, str) else vs
    w, h = (getattr(media, "resolution", None) or (0, 0))[:2]
    return Pin(id=str(getattr(media, "id", "") or abs(hash(src))), src=src,
               title="", alt=getattr(media, "alt", "") or "", video_url=video_url,
               width=int(w or 0), height=int(h or 0),
               link=getattr(media, "origin", "") or "")


def _pdl(query: str, count: int) -> list[Pin]:
    from pinterest_dl import PinterestDL
    api = PinterestDL.with_api(timeout=15, verbose=False)
    raw = (api.scrape(url=query, num=count) if is_url(query)
           else api.search(query=query, num=count, min_resolution=(0, 0)))
    return [p for p in (_from_pdl(m) for m in raw or []) if p]


def iter_pins(query: str, stop: Optional[threading.Event] = None, log: Optional[Log] = None,
              scope: str = "pins", fallback: int = 200) -> Iterator[Pin]:
    """Pins for a keyword or Pinterest URL, streamed. If the built-in client
    finds nothing, pinterest-dl gets a go at up to *fallback* pins."""
    log = log or (lambda m, lvl="info": None)
    found = 0
    problem: Optional[Exception] = None
    try:
        source = iter_url(query, stop) if is_url(query) else iter_search(query, stop, scope)
        for pin in source:
            found += 1
            yield pin
    except ScrapeError as exc:
        problem = exc
    except Exception as exc:  # network weirdness should never kill the run
        problem = exc
    if problem is not None and found:
        log(f"Stopped finding more pins: {problem}", "warning")
    if found or (stop is not None and stop.is_set()) or scope != "pins":
        if problem is not None and not found and scope != "pins":
            log(f"Video search failed: {problem}", "warning")
        return
    try:
        for pin in _pdl(query, fallback):
            found += 1
            yield pin
    except Exception as exc:
        problem = problem or exc
    if not found and problem is not None:
        log(str(problem), "error")


def find_pins(query: str, count: int, stop: Optional[threading.Event] = None,
              log: Optional[Log] = None) -> list[Pin]:
    """Up to *count* unique pins for a keyword or Pinterest URL, as a list."""
    return list(islice(iter_pins(query, stop, log, fallback=count), count))


def merge(existing: Iterable[Pin], more: Iterable[Pin]) -> list[Pin]:
    out = list(existing)
    seen = {p.id for p in out}
    for p in more:
        if p.id not in seen:
            seen.add(p.id)
            out.append(p)
    return out
