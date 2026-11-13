"""The download pipeline, as a stream: find pins → (optionally) match them → download.

All three stages run at the same time. Pins are checked and downloaded while
later result pages are still loading, so the first files land within seconds
and searching stops as soon as enough has been saved.
"""

from __future__ import annotations

import heapq
import itertools
import math
import os
import queue
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterator, Optional

from . import library, media, net, scraper
from .matching import Matcher, MatchSettings, StreamSelector, keep_fraction
from .scraper import Pin

KINDS = ("image", "video", "gif")
LABEL = {"image": "pictures", "video": "videos", "gif": "GIFs"}
MAX_POOL = 1000
SCORERS = 16           # thumbnails are tiny, so many can be checked at once
MAX_UNSCORED = 96      # don't let searching run far ahead of matching
MAX_LOOKED = 4000      # hard stop for one source, however much of it was skipped
CAUGHT_UP = 150        # a follow that meets this many known pins in a row has nothing new


@dataclass
class Job:
    query: str
    out_dir: str
    counts: dict = field(default_factory=lambda: {"image": 50, "video": 0, "gif": 0})
    match: MatchSettings = field(default_factory=MatchSettings)
    threads: int = 8
    seed: Optional[Pin] = None     # "more like this": find pins similar to this one
    origin: str = ""               # the search the seed came from
    preview: bool = False          # show candidates to pick from instead of downloading
    pins: Optional[list] = None    # download exactly these pins (the user's picks)
    scores: dict = field(default_factory=dict)   # pin id → match score, for picks
    exclude: set = field(default_factory=set)    # pin ids already shown: don't offer again
    follow_id: Optional[int] = None  # a check of a followed search/board: new pins only
    min_side: int = 0              # shortest side of the original, in pixels (0 = any)
    shape: str = "any"             # any | tall | wide | square
    library: Optional["library.Library"] = None  # remembers downloads; None = don't track
    skip_owned: bool = True        # leave out pictures the library already has

    @property
    def total(self) -> int:
        return sum(self.counts.get(k, 0) for k in KINDS)


@dataclass
class Event:
    type: str             # log | phase | progress | saved | candidate | done
    level: str = "info"
    text: str = ""
    done: int = 0
    total: int = 0
    kind: str = ""
    path: str = ""
    score: Optional[float] = None
    saved: dict = field(default_factory=dict)
    pin: Optional[Pin] = None
    origin: str = ""      # the search this file came from
    data: bytes = b""     # candidate: its thumbnail
    preview: bool = False  # done: this was a preview, nothing was saved


def pool_size(job: Job) -> int:
    """The most pins worth looking at for this job."""
    mult = {"image": 2, "video": 6, "gif": 6}
    n = sum(job.counts[k] * mult[k] for k in KINDS if job.counts.get(k))
    if job.match.active:
        # Matching throws most candidates away (colour matching at medium
        # tolerance keeps ~5 % of a typical search), so look at many more.
        want = sum(job.counts.get(k, 0) for k in KINDS)
        n = max(n, math.ceil(want / max(keep_fraction(job.match.closeness), 0.05)), want * 20)
    return max(25, min(n, MAX_POOL))


@dataclass
class Source:
    """One stream of pins and the kinds it is there to supply."""
    name: str
    pins: Callable[[], Iterator[Pin]]
    kinds: tuple


class Worker:
    def __init__(self, job: Job, events: "queue.Queue[Event]"):
        self.job = job
        self.events = events
        self.stop_event = threading.Event()   # the user pressed Stop
        self.halt = threading.Event()         # stop searching (stopped, or enough saved)
        self.saved = {k: 0 for k in KINDS}
        self.lock = threading.Lock()
        self.heaps: dict[str, list] = {k: [] for k in KINDS}  # (-score, n, pin), best first
        self.inflight = {k: 0 for k in KINDS}
        self.unscored = 0
        self.scanned = 0
        self.seen: set[str] = set()
        self.selectors: dict[str, StreamSelector] = {}
        self.matcher: Optional[Matcher] = None
        self.scores: dict[str, float] = {}
        self._n = itertools.count()
        self.lib = job.library
        self.seen_sigs: set[str] = set()
        self.skipped = {"owned": 0, "repost": 0, "quality": 0}
        self.embs: dict = {}
        self._dedupe = threading.Lock()

    # ── plumbing ────────────────────────────────────────────────────────
    def stop(self):
        self.stop_event.set()
        self.halt.set()

    @property
    def stopped(self) -> bool:
        return self.stop_event.is_set()

    def log(self, text: str, level: str = "info"):
        self.events.put(Event("log", level=level, text=f"[{datetime.now():%H:%M:%S}] {text}"))

    def phase(self, text: str):
        self.events.put(Event("phase", text=text))

    def progress(self, done: int, total: int):
        self.events.put(Event("progress", done=done, total=total))

    # ── pipeline ────────────────────────────────────────────────────────
    def run(self):
        try:
            self._run()
        except Exception as exc:  # last line of defence: report, don't vanish
            self.log(f"Unexpected error: {exc}", "error")
        finally:
            self.halt.set()
            self.events.put(Event("done", saved=dict(self.saved), preview=self.job.preview,
                                  level="warning" if self.stopped else "success"))

    def _make_matcher(self) -> Optional[Matcher]:
        job = self.job
        if not job.match.active:
            return None
        try:
            matcher = Matcher(job.match, self._smart_model())
        except Exception as exc:
            self.log(f"Couldn't read the reference image ({exc}); matching is off.", "error")
            return None
        modes = matcher.modes()
        if not modes:
            return None
        parts = []
        if job.match.reference and (matcher.looks or (matcher.palette is not None
                                                      and not job.match.palette)):
            parts.append(os.path.basename(job.match.reference))
        elif matcher.looks:
            parts.append(f"your {len(job.match.examples)} picks")
        elif matcher.palette is not None:
            parts.append("your picked colors")
        if matcher.describes:
            parts.append(f"“{job.match.describe.strip()}”")
        self.log(f"Matching against {' and '.join(parts)} ({' + '.join(modes)}).")
        if matcher.palette is not None:
            mix = ", ".join(f"{h} {s:.0%}" for h, s in matcher.palette.entries())
            self.log(f"Reference palette: {mix}")
        return matcher

    def _smart_model(self):
        """The CLIP model if this job wants it, downloading it the first time."""
        m = self.job.match
        if not m.wants_model:
            return None
        from . import smart
        if not smart.available():
            if m.described:
                self.log("Descriptions need the smart model. Install it with: "
                         "pip install onnxruntime tokenizers", "warning")
            return None
        if not smart.installed():
            self.log(f"Getting the smart matching model (about {smart.TOTAL_MB} MB, one time only)…")
            self.phase("Downloading the smart matching model…")
        clip = smart.get(lambda done, total: self.progress(done, total), self.halt)
        if clip is None and not self.stopped:
            self.log("Couldn't load the smart model; using the classic matcher instead.", "warning")
        return clip

    def _sources(self, wanted: list[str]) -> list[Source]:
        q, halt, log = self.job.query, self.halt, self.log
        seed = self.job.seed
        self.seen.update(self.job.exclude)
        if self.job.pins is not None:
            picks = list(self.job.pins)
            return [Source("your picks", lambda: iter(picks), tuple(wanted))]
        if seed is not None:
            # Pinterest's related feed when it's allowed, plus searches for what
            # the picture shows. The matcher then keeps the ones that look like it.
            self.seen.add(seed.id)
            kinds = tuple(wanted)
            out = [Source("related pins", lambda: self._related(seed), kinds)]
            for phrase in scraper.similar_queries(seed, self.job.origin):
                out.append(Source(f"search for '{phrase[:40]}'",
                                  lambda phrase=phrase: scraper.iter_pins(phrase, halt, fallback=0),
                                  kinds))
            return out
        if scraper.is_url(q):
            return [Source("link", lambda: scraper.iter_pins(q, halt, log), tuple(wanted))]
        out = []
        if "image" in wanted:
            out.append(Source("search", lambda: scraper.iter_pins(q, halt, log), tuple(wanted)))
        # Videos and GIFs are rare in plain search results, so look for them specifically.
        if "video" in wanted:
            out.append(Source("video search",
                              lambda: scraper.iter_pins(q, halt, log, scope="videos"), ("video",)))
        if "gif" in wanted:
            gq = q if "gif" in q.lower() else f"{q} gif"
            out.append(Source("GIF search", lambda: scraper.iter_pins(gq, halt, log), ("gif",)))
        return out

    def _related(self, seed: Pin) -> Iterator[Pin]:
        try:
            yield from scraper.iter_related(seed.id, self.halt)
        except scraper.ScrapeError:
            return  # anonymous sessions aren't given this feed; the searches cover for it

    def _seed_reference(self):
        """A "more like this" job matches against the seed picture itself."""
        job = self.job
        ref = job.match.reference
        if ref and os.path.isfile(ref) and media.kind_of(ref) in ("image", "gif"):
            return
        data = media.fetch_bytes(job.seed.src) or media.fetch_bytes(job.seed.thumb)
        if not data:
            self.log("Couldn't load the picture to compare against.", "warning")
            return
        path = os.path.join(job.out_dir, ".seed.img")
        with open(path, "wb") as f:
            f.write(data)
        job.match.reference = path
        self._seed_file = path

    def _run(self):
        job = self.job
        wanted = [k for k in KINDS if job.counts.get(k, 0) > 0]
        if not wanted:
            self.log("Nothing to do: every count is 0.", "warning")
            return
        os.makedirs(job.out_dir, exist_ok=True)
        self.wanted = wanted
        tuned = net.tune()
        self._seed_file = None
        if job.seed is not None:
            self._seed_reference()
            if not (job.match.look or job.match.colors):
                job.match.look = True
        self.matcher = None if job.pins is not None else self._make_matcher()
        self.scores.update(job.scores)
        self.thumbs: dict[str, bytes] = {}
        if self.matcher:
            self.selectors = {k: StreamSelector(self.matcher) for k in wanted}
        self.cap = pool_size(job)
        self.started = time.time()

        self.phase("Searching Pinterest…")
        if tuned:
            self.log("IPv6 to Pinterest isn't working on this network; using IPv4.")
        self.log(f"Looking for pins like '{job.query}'…" if job.seed
                 else f"Looking for '{job.query}'…")
        self.progress(0, job.total)
        scorer = ThreadPoolExecutor(max_workers=SCORERS) if self.matcher else None
        scanners = [threading.Thread(target=self._scan, args=(s, scorer), daemon=True)
                    for s in self._sources(wanted)]
        for t in scanners:
            t.start()
        try:
            self._dispatch(scanners)
        finally:
            self.halt.set()
            if scorer:
                scorer.shutdown(wait=False, cancel_futures=True)
            if self._seed_file:
                try:
                    os.remove(self._seed_file)
                except OSError:
                    pass
        self._report()

    # ── stage 1: find ───────────────────────────────────────────────────
    def _full(self, kind: str) -> bool:
        return self.saved[kind] >= self.job.counts[kind]

    def _buffered(self, kind: str) -> bool:
        """Enough candidates of this kind are already lined up."""
        want = self.job.counts[kind]
        # keep spares: some downloads fail, and with matching the best of the
        # waiting candidates goes first, so a deeper line means better picks
        spare = max(10, want // 2) if self.matcher else max(4, want // 5)
        return self.saved[kind] + self.inflight[kind] + len(self.heaps[kind]) >= want + spare

    def _accepts(self, pin: Pin, kind: str) -> bool:
        """Is this pin worth a look? (call with the lock held)"""
        if self.job.pins is not None:
            return True                   # the user picked it: no second-guessing
        if not fits(pin, self.job.min_side, self.job.shape):
            self.skipped["quality"] += 1  # known from the search results: costs no download
            return False
        if pin.sig:
            if pin.sig in self.seen_sigs:  # the same picture, pinned again by someone else
                self.skipped["repost"] += 1
                return False
            self.seen_sigs.add(pin.sig)
        if self.lib is not None and self.job.skip_owned and self.lib.have(pin, kind):
            self.skipped["owned"] += 1
            return False
        if (self.lib is not None and self.job.follow_id is not None
                and self.lib.follow_saw(self.job.follow_id, pin.key)):
            self.skipped["owned"] += 1    # delivered before (and since deleted): not again
            return False
        return True

    def _scan(self, source: Source, scorer: Optional[ThreadPoolExecutor]):
        kinds = [k for k in source.kinds if k in self.wanted]
        looked = passed = streak = 0
        following = self.job.follow_id is not None
        try:
            for pin in source.pins():
                while not self.halt.is_set():
                    with self.lock:
                        if all(self._full(k) for k in kinds):
                            return
                        busy = (all(self._full(k) or self._buffered(k) for k in kinds)
                                or self.unscored >= MAX_UNSCORED)
                    if not busy:
                        break
                    time.sleep(0.05)
                if self.halt.is_set():
                    return
                kind = pin.kind
                looked += 1
                with self.lock:
                    # a pin of a kind this source isn't here for is left for the one that is
                    if kind not in kinds or pin.id in self.seen:
                        if looked >= self.cap:
                            return
                        continue
                    self.seen.add(pin.id)
                    self.scanned += 1
                    known = self.skipped["owned"]
                    take = not self._full(kind) and self._accepts(pin, kind)
                    streak = streak + 1 if self.skipped["owned"] > known else 0
                    if following and streak >= CAUGHT_UP:
                        return            # deep into pins we already have: caught up
                    if not take and not self._full(kind):
                        # already owned / a re-pin: doesn't use up the budget, so a
                        # repeat search digs deeper instead of coming back short
                        looked -= 1
                        passed += 1
                        if passed >= MAX_LOOKED:
                            return
                    if take and scorer:
                        self.unscored += 1
                    elif take:
                        self._offer(pin, kind, None)
                if take and scorer:
                    scorer.submit(self._score, pin, kind)
                if looked >= self.cap:
                    return
        except Exception as exc:
            self.log(f"The {source.name} stopped early: {exc}", "warning")

    # ── stage 2: match ──────────────────────────────────────────────────
    def _offer(self, pin: Pin, kind: str, score: Optional[float]):
        """Line a candidate up for download (call with the lock held)."""
        if score is not None:
            self.scores[pin.id] = score
        heapq.heappush(self.heaps[kind], (-(score or 0.0), next(self._n), pin))

    def _score(self, pin: Pin, kind: str):
        sc = None
        try:
            if not self.halt.is_set():
                data = (media.fetch_bytes(pin.thumb, timeout=10)
                        or media.fetch_bytes(scraper.resized(pin.src, "474x"), timeout=10)
                        or media.fetch_bytes(pin.src))
                sc = self.matcher.score(data) if data else None
                if sc is not None and self.job.preview:
                    self.thumbs[pin.id] = data
                if sc is not None and sc.emb is not None and self.lib is not None:
                    self.embs[pin.id] = sc.emb
        except Exception:
            sc = None
        finally:
            with self.lock:
                self.unscored -= 1
                if sc is not None:
                    for item, combined in self.selectors[kind].add(pin, sc):
                        self._offer(item, kind, combined)

    # ── stage 3: download (or, when previewing, show) ───────────────────
    def _preview(self, pin: Pin, out_dir: str, kind: str, stop: threading.Event):
        """Preview stand-in for media.download: the thumbnail instead of the file."""
        data = (self.thumbs.pop(pin.id, None) or media.fetch_bytes(pin.thumb, timeout=10)
                or media.fetch_bytes(scraper.resized(pin.src, "474x"), timeout=10))
        return (data, "ok") if data else (None, "network")

    def _download(self, pin: Pin, out_dir: str, kind: str, stop: threading.Event):
        """media.download, plus the library: drop near-duplicates, record the rest."""
        job = self.job
        was_there = media.existing_file(pin, out_dir, kind) if self.lib is not None else None
        path, reason = media.download(pin, out_dir, kind, stop)
        if not path or self.lib is None:
            return path, reason
        dh = library.dhash_of(path) if kind == "image" else None
        with self._dedupe:  # check-then-record must not interleave between two downloads
            if dh is not None and not was_there and job.skip_owned and job.pins is None:
                if self.lib.near_duplicate(dh, ignore=path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    return None, "duplicate"
            self.lib.add(pin, kind, path, job.origin or job.query, self.scores.get(pin.id),
                         dh, self.embs.pop(pin.id, None))
            if job.follow_id is not None:
                self.lib.follow_mark(job.follow_id, pin.key)
        return path, "ok"

    def _dispatch(self, scanners: list[threading.Thread]):
        job = self.job
        fetch = self._preview if job.preview else self._download
        ex = ThreadPoolExecutor(max_workers=job.threads)
        running: dict[Future, tuple[Pin, str]] = {}
        self.failed = {k: {} for k in KINDS}
        total = job.total
        last_note = ""
        try:
            while not self.stopped:
                with self.lock:
                    for k in self.wanted:
                        while (len(running) < job.threads and self.heaps[k]
                               and self.saved[k] + self.inflight[k] < job.counts[k]):
                            _, _, pin = heapq.heappop(self.heaps[k])
                            self.inflight[k] += 1
                            running[ex.submit(fetch, pin, job.out_dir, k,
                                              self.stop_event)] = (pin, k)
                    done_all = all(self._full(k) for k in self.wanted)
                    searching = self.unscored > 0 or any(t.is_alive() for t in scanners)
                    waiting = any(self.heaps[k] and not self._full(k) for k in self.wanted)
                if done_all:
                    break
                if not running and not searching and not waiting:
                    with self.lock:  # nothing left to look at: decide the held-back ones
                        late = [(k, item, c) for k, sel in self.selectors.items()
                                for item, c in sel.flush()]
                        for k, item, c in late:
                            self._offer(item, k, c)
                    if not late:
                        break
                    continue
                if running:
                    finished, _ = wait(list(running), timeout=0.2, return_when=FIRST_COMPLETED)
                else:
                    finished = ()
                    time.sleep(0.05)
                for fut in finished:
                    pin, k = running.pop(fut)
                    try:
                        path, reason = fut.result()
                    except Exception:
                        path, reason = None, "network"
                    with self.lock:
                        self.inflight[k] -= 1
                        ok = bool(path) and self.saved[k] < job.counts[k]
                        if ok:
                            self.saved[k] += 1
                        elif not path:
                            self.failed[k][reason] = self.failed[k].get(reason, 0) + 1
                    if ok and job.preview:
                        self.events.put(Event("candidate", kind=k, data=path, pin=pin,
                                              origin=job.origin or job.query,
                                              score=self.scores.get(pin.id)))
                    elif ok:
                        self.events.put(Event("saved", kind=k, path=path, pin=pin,
                                              origin=job.origin or job.query,
                                              score=self.scores.get(pin.id)))
                    if ok:
                        self.progress(sum(self.saved.values()), total)
                got = sum(self.saved.values())
                if job.preview:
                    note = f"Finding candidates… {got} of {total}, {self.scanned} pins checked"
                else:
                    note = (f"Downloading… {got} of {total} saved, {self.scanned} pins checked"
                            if got or running
                            else f"Searching Pinterest… {self.scanned} pins checked")
                if note != last_note:
                    self.phase(note)
                    last_note = note
        finally:
            self.halt.set()
            ex.shutdown(wait=False, cancel_futures=True)

    def _report(self):
        job = self.job
        if self.stopped:
            return
        if not self.scanned:
            self.log("No pins found. Try a different keyword or check the link.", "warning")
            return
        if self.skipped["owned"]:
            self.log(f"Left out {self.skipped['owned']} pins you already have.")
        if self.skipped["quality"]:
            self.log(f"Left out {self.skipped['quality']} pins that were too small or the "
                     "wrong shape.")
        if self.skipped["repost"]:
            self.log(f"Left out {self.skipped['repost']} re-pins of the same pictures.")
        for k in self.wanted:
            got, want = self.saved[k], job.counts[k]
            sel = self.selectors.get(k)
            if sel and sel.seen:
                self.log(f"{sel.passed} of {sel.seen} {LABEL[k]} checked were a match.",
                         "success" if sel.passed else "warning")
            if job.preview:
                if got < want and not self.matcher:
                    self.log(f"Only {got} {LABEL[k]} found (wanted {want}).", "warning")
                self.log(f"Showing {got} {LABEL[k]} to pick from.", "success" if got else "warning")
                continue
            f = self.failed[k]
            if f.get("no-ffmpeg"):
                self.log(f"{f['no-ffmpeg']} videos need ffmpeg to be saved. Install it with: "
                         "pip install imageio-ffmpeg", "error")
            lost = f.get("network", 0) + f.get("no-url", 0)
            if lost:
                self.log(f"{lost} {LABEL[k]} couldn't be downloaded (Pinterest didn't respond); "
                         "try again in a minute.", "warning")
            if f.get("wrong-type"):
                self.log(f"Skipped {f['wrong-type']} pins that weren't real {LABEL[k]}.")
            if f.get("duplicate"):
                self.log(f"Skipped {f['duplicate']} {LABEL[k]} that look the same as ones "
                         "you already have.")
            if got < want and job.follow_id is not None:
                self.log(f"{got} new {LABEL[k]}." if got else f"No new {LABEL[k]}.",
                         "success" if got else "info")
                continue
            if got < want:
                why = " that match" if self.matcher else ""
                self.log(f"Only {got} {LABEL[k]}{why} available (wanted {want}).", "warning")
                if self.matcher:
                    self.log("Tip: lower “How close?” to get more."
                             if self.matcher.palette is None
                             else "Tip: raise Color tolerance or lower “How close?” to get more.")
            self.log(f"Saved {got} {LABEL[k]}.", "success" if got else "warning")
        if job.preview:
            return
        secs = time.time() - self.started
        self.log(f"All done: {sum(self.saved.values())} files in {job.out_dir} "
                 f"({secs:.0f}s, {self.scanned} pins checked)", "success")


def similar_job(pin: Pin, path: str, base: Job, origin: str = "") -> Job:
    """A job that finds more pins like *pin* (already saved at *path*) and
    puts them next to it, reusing *base*'s counts and matching strictness."""
    m = base.match
    match = MatchSettings(reference=path, look=True, colors=False, closeness=m.closeness,
                          color_tolerance=m.color_tolerance)
    name = (pin.title or pin.alt or origin or "this picture").strip()
    return Job(query=name[:60], out_dir=os.path.dirname(path) or base.out_dir,
               counts=dict(base.counts), match=match, threads=base.threads,
               seed=pin, origin=origin, library=base.library, skip_owned=base.skip_owned,
               min_side=base.min_side, shape=base.shape)


def picks_job(pins: list, base: Job) -> Job:
    """A job that downloads exactly *pins* (what the user picked from a preview)."""
    counts = {k: sum(1 for p in pins if p.kind == k) for k in KINDS}
    return Job(query=base.query, out_dir=base.out_dir, counts=counts, threads=base.threads,
               pins=list(pins), scores=dict(base.scores), origin=base.origin or base.query,
               library=base.library)


def safe_name(text: str) -> str:
    """A folder name for a search or link."""
    if scraper.is_url(text):
        text = scraper.link_name(text)
    name = "".join(c for c in text if c.isalnum() or c in " _-").strip()
    return name[:60] or f"download_{int(time.time())}"


SHAPES = ("any", "tall", "wide", "square")


def fits(pin: Pin, min_side: int = 0, shape: str = "any") -> bool:
    """Does the pin's original meet the size and shape asked for? Pinterest
    reports both in the search results. A pin with no size on record passes."""
    w, h = pin.width, pin.height
    if not (w and h):
        return True
    if min(w, h) < min_side:
        return False
    ratio = w / h
    if shape == "tall":
        return ratio < 0.9
    if shape == "wide":
        return ratio > 1.1
    if shape == "square":
        return 0.9 <= ratio <= 1.1
    return True


def follow_job(f: "library.Follow", lib: "library.Library", threads: int = 8) -> Job:
    """One check of a followed search or board: fetch what's new since last time."""
    return Job(query=f.query, out_dir=f.folder, counts=dict(f.counts), threads=threads,
               library=lib, skip_owned=True, follow_id=f.id, min_side=f.min_side, shape=f.shape)
