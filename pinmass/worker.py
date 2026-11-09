"""The download pipeline: find pins → (optionally) match them → download."""

from __future__ import annotations

import math
import os
import queue
import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from . import media, scraper
from .matching import Matcher, MatchSettings, keep_fraction
from .scraper import Pin

KINDS = ("image", "video", "gif")
LABEL = {"image": "pictures", "video": "videos", "gif": "GIFs"}
MAX_POOL = 1000


@dataclass
class Job:
    query: str
    out_dir: str
    counts: dict = field(default_factory=lambda: {"image": 50, "video": 0, "gif": 0})
    match: MatchSettings = field(default_factory=MatchSettings)
    threads: int = 8

    @property
    def total(self) -> int:
        return sum(self.counts.get(k, 0) for k in KINDS)


@dataclass
class Event:
    type: str             # log | phase | progress | saved | done
    level: str = "info"
    text: str = ""
    done: int = 0
    total: int = 0
    kind: str = ""
    path: str = ""
    score: Optional[float] = None
    saved: dict = field(default_factory=dict)


def pool_size(job: Job) -> int:
    mult = {"image": 2, "video": 6, "gif": 6}
    n = sum(job.counts[k] * mult[k] for k in KINDS if job.counts.get(k))
    if job.match.active:
        # Matching throws most candidates away (colour matching at medium
        # tolerance keeps ~5 % of a typical search), so look at many more.
        want = sum(job.counts.get(k, 0) for k in KINDS)
        n = max(n, math.ceil(want / max(keep_fraction(job.match.closeness), 0.05)), want * 20)
    return max(25, min(n, MAX_POOL))


class Worker:
    def __init__(self, job: Job, events: "queue.Queue[Event]"):
        self.job = job
        self.events = events
        self.stop_event = threading.Event()
        self.saved = {k: 0 for k in KINDS}

    # ── plumbing ────────────────────────────────────────────────────────
    def stop(self):
        self.stop_event.set()

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
            self.events.put(Event("done", saved=dict(self.saved),
                                  level="warning" if self.stopped else "success"))

    def _run(self):
        job = self.job
        wanted = [k for k in KINDS if job.counts.get(k, 0) > 0]
        if not wanted:
            self.log("Nothing to do: every count is 0.", "warning")
            return
        os.makedirs(job.out_dir, exist_ok=True)

        matcher = None
        if job.match.active:
            try:
                matcher = Matcher(job.match)
            except Exception as exc:
                self.log(f"Couldn't read the reference image ({exc}); matching is off.", "error")
            else:
                modes = [m for m, on in (("look-alike", matcher.sig is not None),
                                         ("color", matcher.palette is not None)) if on]
                src = (os.path.basename(job.match.reference) if job.match.reference
                       else "your picked colors")
                self.log(f"Matching against {src} ({' + '.join(modes)}).")
                if matcher.palette is not None:
                    mix = ", ".join(f"{h} {s:.0%}" for h, s in
                                    matcher.palette.entries())
                    self.log(f"Reference palette: {mix}")

        # 1. find
        n = pool_size(job)
        self.phase("Searching Pinterest…")
        self.log(f"Looking for up to {n} pins for '{job.query}'…")
        pins = scraper.find_pins(job.query, n, self.stop_event, self.log)
        pins = self._top_up(pins, wanted, n)
        if self.stopped:
            return
        if not pins:
            self.log("No pins found. Try a different keyword or check the URL.", "warning")
            return

        pools = {k: [p for p in pins if p.kind == k] for k in KINDS}
        self.log("Found " + ", ".join(f"{len(pools[k])} {LABEL[k]}" for k in KINDS) + ".")

        # 2. match
        scores: dict[str, float] = {}
        if matcher:
            for k in wanted:
                pools[k] = self._rank(pools[k], matcher, scores, k)
                if self.stopped:
                    return

        # 3. download, strictly per type
        total = sum(min(job.counts[k], len(pools[k])) for k in wanted)
        done = 0
        self.progress(0, total)
        for k in wanted:
            if self.stopped:
                return
            want_n = job.counts[k]
            if len(pools[k]) < want_n:
                why = " that match the reference" if matcher else ""
                self.log(f"Only {len(pools[k])} {LABEL[k]}{why} available (wanted {want_n}).",
                         "warning")
                if matcher:
                    self.log("Tip: raise Color tolerance or lower How close to get more.")
            if not pools[k]:
                continue
            self.phase(f"Downloading {LABEL[k]}…")
            got = self._download(pools[k], k, want_n, scores, done, total)
            done += got
            self.saved[k] = got
            self.log(f"Saved {got} {LABEL[k]}.", "success" if got else "warning")

        if not self.stopped:
            self.log(f"All done: {sum(self.saved.values())} files in {job.out_dir}", "success")

    def _top_up(self, pins: list[Pin], wanted: list[str], n: int) -> list[Pin]:
        """Videos and GIFs are rare in plain search results; search for them
        specifically when the first pass didn't turn up enough."""
        if scraper.is_url(self.job.query):
            return pins
        for k, word in (("gif", "gif"), ("video", "video")):
            if k not in wanted or self.stopped:
                continue
            have = sum(1 for p in pins if p.kind == k)
            need = self.job.counts[k] * (3 if self.job.match.active else 1)
            if have >= need:
                continue
            q = self.job.query if word in self.job.query.lower() else f"{self.job.query} {word}"
            self.log(f"Not many {LABEL[k]} yet ({have}); also searching '{q}'…")
            more = scraper.find_pins(q, min(n, MAX_POOL), self.stop_event, self.log)
            pins = scraper.merge(pins, more)
        return pins

    def _rank(self, pool: list[Pin], matcher: Matcher, scores: dict, kind: str) -> list[Pin]:
        if not pool:
            return pool
        self.phase(f"Comparing {LABEL[kind]} with your reference…")
        scored = []
        done = 0

        def check(pin: Pin):
            data = (media.fetch_bytes(pin.thumb, timeout=10)
                    or media.fetch_bytes(scraper.thumb_url(pin.src).replace("/236x/", "/474x/"),
                                         timeout=10)
                    or media.fetch_bytes(pin.src))
            return pin, (matcher.score(data) if data else None)

        # thumbnails are tiny, so check many at once regardless of the download setting
        with ThreadPoolExecutor(max_workers=max(16, self.job.threads)) as ex:
            futures = [ex.submit(check, p) for p in pool]
            for fut in futures:
                if self.stopped:
                    ex.shutdown(wait=False, cancel_futures=True)
                    return []
                pin, sc = fut.result()
                done += 1
                if sc is not None:
                    scored.append((pin, sc))
                if done % 5 == 0 or done == len(pool):
                    self.progress(done, len(pool))
        results = matcher.select(scored)
        for pin, combined in results:
            scores[pin.id] = combined
        self.log(f"{len(results)} of {len(pool)} {LABEL[kind]} match the reference.",
                 "success" if results else "warning")
        return [p for p, _ in results]

    def _download(self, pool: list[Pin], kind: str, want_n: int, scores: dict,
                  base_done: int, total: int) -> int:
        """Download from *pool* in order until *want_n* files of the right type
        are saved. Rejected or failed pins are replaced by the next candidate."""
        saved = 0
        it = iter(pool)
        rejected = 0
        ex = ThreadPoolExecutor(max_workers=self.job.threads)
        running: dict[Future, Pin] = {}

        def fill():
            while len(running) < self.job.threads and saved + len(running) < want_n:
                pin = next(it, None)
                if pin is None:
                    return
                running[ex.submit(media.download, pin, self.job.out_dir, kind,
                                  self.stop_event)] = pin

        try:
            fill()
            while running and not self.stopped:
                finished, _ = wait(list(running), timeout=0.5, return_when=FIRST_COMPLETED)
                for fut in finished:
                    pin = running.pop(fut)
                    path = fut.result()
                    if path and saved < want_n:
                        saved += 1
                        self.events.put(Event("saved", kind=kind, path=path,
                                              score=scores.get(pin.id)))
                        self.progress(base_done + saved, total)
                    elif not path:
                        rejected += 1
                fill()
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        if rejected:
            self.log(f"Skipped {rejected} pins that failed or weren't real {LABEL[kind]}.")
        return saved
