"""Starting downloads from somewhere other than the desktop window.

The phone page talks to a *control*: an object with submit(), status() and
stop(). The desktop app has its own (it feeds the normal queue); Control here
is the one used without a window (`--phone FOLDER`), so a PC left running
with just the phone server can still fetch things.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from typing import Optional

from . import library, settings
from .matching import MatchSettings
from .worker import KINDS, Job, Worker, safe_name

MAX_PER_REQUEST = 300


def clean_counts(raw: dict) -> dict:
    """Counts as sent by the phone → a safe {'image': n, 'video': n, 'gif': n}."""
    out = {}
    for k in KINDS:
        try:
            out[k] = max(0, min(int(raw.get(k) or 0), MAX_PER_REQUEST))
        except (TypeError, ValueError):
            out[k] = 0
    return out


def idle_status() -> dict:
    return {"running": False, "query": "", "phase": "", "done": 0, "total": 0,
            "waiting": 0, "finished": 0, "last": ""}


class Control:
    """Runs submitted searches one after another on a background thread."""

    def __init__(self, folder: str, cfg: Optional[dict] = None):
        self.folder = folder
        self.cfg = cfg or settings.load()
        self.jobs: "queue.Queue[Job]" = queue.Queue()
        self.worker: Optional[Worker] = None
        self._status = idle_status()
        self._lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, query: str, counts: dict) -> Optional[str]:
        """Queue a search. Returns None, or a sentence saying why not."""
        query = " ".join(query.split())
        counts = clean_counts(counts)
        if not query:
            return "Type something to search for."
        if not any(counts.values()):
            return "Ask for at least one picture, video or GIF."
        out = os.path.join(self.folder, safe_name(query)) if self.cfg.get("subfolders", True) \
            else self.folder
        self.jobs.put(Job(query=query, out_dir=out, counts=counts, match=MatchSettings(),
                          threads=int(self.cfg.get("threads", 8)), library=library.shared(),
                          min_side=int(self.cfg.get("min_side", 0)),
                          shape=self.cfg.get("shape", "any"),
                          skip_owned=bool(self.cfg.get("skip_owned", True))))
        with self._lock:
            self._status["waiting"] = self.jobs.qsize()
        return None

    def status(self) -> dict:
        with self._lock:
            return dict(self._status, waiting=self.jobs.qsize())

    def stop(self) -> None:
        if self.worker:
            self.worker.stop()

    def _set(self, **kw):
        with self._lock:
            self._status.update(kw)

    def _loop(self):
        while True:
            job = self.jobs.get()
            events: queue.Queue = queue.Queue()
            self.worker = Worker(job, events)
            self._set(running=True, query=job.query, phase="Starting…", done=0, total=job.total)
            threading.Thread(target=self.worker.run, daemon=True).start()
            while True:
                ev = events.get()
                if ev.type == "phase":
                    self._set(phase=ev.text)
                elif ev.type == "progress":
                    self._set(done=ev.done, total=ev.total)
                elif ev.type == "done":
                    n = sum(ev.saved.values())
                    with self._lock:
                        self._status.update(
                            running=False, phase="", finished=self._status["finished"] + 1,
                            last=f"“{job.query}”: {n} saved" if n
                            else f"“{job.query}”: nothing found")
                    break
            self.worker = None
            time.sleep(0.05)
