"""The library: a small database of everything the app has downloaded.

Files on disk are named after their pin and nothing else, so on their own they
can't say what they are, where they came from, or whether the same picture is
already sitting in another folder. The library remembers that:

* never download the same picture twice, whichever folder or search it came
  from (Pinterest's image signature identifies a picture across re-pins);
* catch near-duplicates: the same picture re-uploaded at another size or
  quality (a 64-bit perceptual hash, compared by how many bits differ);
* search what you have, by the words of the search, the title and Pinterest's
  description, or by meaning when the smart model is installed;
* remember each file's pin, so "More like this" works on old downloads.

It lives in one SQLite file next to the settings.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

from .scraper import Pin

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id      INTEGER PRIMARY KEY,
    pin_id  TEXT NOT NULL,
    sig     TEXT NOT NULL DEFAULT '',
    kind    TEXT NOT NULL,
    path    TEXT NOT NULL UNIQUE,
    query   TEXT NOT NULL DEFAULT '',
    title   TEXT NOT NULL DEFAULT '',
    alt     TEXT NOT NULL DEFAULT '',
    link    TEXT NOT NULL DEFAULT '',
    src     TEXT NOT NULL DEFAULT '',
    video   TEXT NOT NULL DEFAULT '',
    width   INTEGER NOT NULL DEFAULT 0,
    height  INTEGER NOT NULL DEFAULT 0,
    score   REAL,
    dhash   TEXT,            -- 16 hex digits, images only
    emb     BLOB,            -- 512 float32, when the smart model has seen it
    added   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS items_pin ON items(pin_id);
CREATE INDEX IF NOT EXISTS items_sig ON items(sig);
CREATE TABLE IF NOT EXISTS follows (
    id       INTEGER PRIMARY KEY,
    query    TEXT NOT NULL,          -- keyword or board / profile link
    folder   TEXT NOT NULL,
    image    INTEGER NOT NULL DEFAULT 0,   -- most new files to fetch per check
    video    INTEGER NOT NULL DEFAULT 0,
    gif      INTEGER NOT NULL DEFAULT 0,
    min_side INTEGER NOT NULL DEFAULT 0,
    shape    TEXT NOT NULL DEFAULT 'any',
    added    REAL NOT NULL,
    checked  REAL NOT NULL DEFAULT 0,      -- when it was last checked (0 = never)
    last_new INTEGER NOT NULL DEFAULT 0,   -- how many that check brought
    total    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(query, folder)
);
-- every picture a follow has already delivered, so one you deleted on
-- purpose doesn't come back at the next check
CREATE TABLE IF NOT EXISTS follow_seen (
    follow_id INTEGER NOT NULL,
    key       TEXT NOT NULL,
    PRIMARY KEY (follow_id, key)
) WITHOUT ROWID;
"""
NEAR_BITS = 5   # perceptual hashes this close (of 64 bits) are the same picture


def default_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "PinterestMassDownloader" / "library.db"


@dataclass
class Follow:
    id: int
    query: str
    folder: str
    counts: dict
    min_side: int
    shape: str
    checked: float
    last_new: int
    total: int


@dataclass
class Item:
    id: int
    pin: Pin
    kind: str
    path: str
    query: str
    score: Optional[float]
    added: float


def dhash_of(src) -> Optional[int]:
    """64-bit difference hash of a picture (path, bytes or image); None if unreadable."""
    try:
        from .matching import load
        from PIL import Image
        d = np.asarray(load(src).convert("L").resize((9, 8), Image.Resampling.BOX), dtype=np.int16)
    except Exception:
        return None
    bits = (d[:, 1:] > d[:, :-1]).ravel()
    return int("".join("1" if b else "0" for b in bits), 2)


def _bits(a: np.ndarray) -> np.ndarray:
    """Number of set bits in each uint64."""
    return np.unpackbits(a.view(np.uint8).reshape(-1, 8), axis=1).sum(axis=1)


def _follow(r: sqlite3.Row) -> Follow:
    return Follow(id=r["id"], query=r["query"], folder=r["folder"],
                  counts={"image": r["image"], "video": r["video"], "gif": r["gif"]},
                  min_side=r["min_side"], shape=r["shape"], checked=r["checked"],
                  last_new=r["last_new"], total=r["total"])


class Library:
    def __init__(self, path: Optional[str] = None):
        self.path = str(path or default_path())
        if self.path != ":memory:":
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.executescript(SCHEMA)
        self._hashes: Optional[tuple[np.ndarray, list[str]]] = None

    def close(self):
        with self._lock:
            self._db.close()

    # ── writing ─────────────────────────────────────────────────────────
    def add(self, pin: Pin, kind: str, path: str, query: str = "",
            score: Optional[float] = None, dhash: Optional[int] = None,
            emb: Optional[np.ndarray] = None) -> None:
        path = os.path.abspath(path)
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO items (pin_id, sig, kind, path, query, title, alt, link, src, video,"
                " width, height, score, dhash, emb, added)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(path) DO UPDATE SET pin_id=excluded.pin_id, sig=excluded.sig,"
                " kind=excluded.kind, title=excluded.title, alt=excluded.alt, link=excluded.link,"
                " src=excluded.src, video=excluded.video, width=excluded.width,"
                " height=excluded.height, score=COALESCE(excluded.score, score),"
                " dhash=COALESCE(excluded.dhash, dhash), emb=COALESCE(excluded.emb, emb),"
                " query=CASE WHEN excluded.query != '' THEN excluded.query ELSE query END",
                (pin.id, pin.sig, kind, path, query, pin.title, pin.alt, pin.link, pin.src,
                 pin.video_url or "", pin.width, pin.height, score,
                 f"{dhash:016x}" if dhash is not None else None,
                 emb.astype(np.float32).tobytes() if emb is not None else None, time.time()))
            if dhash is not None and self._hashes is not None:
                arr, paths = self._hashes
                self._hashes = (np.append(arr, np.uint64(dhash)), paths + [path])

    def forget(self, path: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM items WHERE path = ?", (os.path.abspath(path),))
            self._hashes = None

    # ── "do I already have this?" ───────────────────────────────────────
    def _live(self, rows: Iterable[sqlite3.Row]) -> Optional[str]:
        """First of *rows* whose file still exists; rows for deleted files are dropped."""
        for r in rows:
            if os.path.exists(r["path"]):
                return r["path"]
            self.forget(r["path"])
        return None

    def have(self, pin: Pin, kind: str) -> Optional[str]:
        """Path of a file already holding this pin (or this exact picture), if any."""
        with self._lock:
            rows = self._db.execute(
                "SELECT path FROM items WHERE kind = ? AND (pin_id = ?"
                + (" OR sig = ?)" if pin.sig else ")"),
                (kind, pin.id, pin.sig) if pin.sig else (kind, pin.id)).fetchall()
            return self._live(rows)

    def near_duplicate(self, dhash: int, ignore: str = "") -> Optional[str]:
        """Path of a picture that looks the same as the one with *dhash*, if any."""
        with self._lock:
            if self._hashes is None:
                rows = self._db.execute(
                    "SELECT path, dhash FROM items WHERE dhash IS NOT NULL").fetchall()
                self._hashes = (np.array([int(r["dhash"], 16) for r in rows], dtype=np.uint64),
                                [r["path"] for r in rows])
            arr, paths = self._hashes
            if not len(arr):
                return None
            close = np.nonzero(_bits(arr ^ np.uint64(dhash)) <= NEAR_BITS)[0]
            ignore = os.path.abspath(ignore) if ignore else ""
            for i in close:
                if paths[i] != ignore and os.path.exists(paths[i]):
                    return paths[i]
            return None

    # ── reading ─────────────────────────────────────────────────────────
    @staticmethod
    def _item(r: sqlite3.Row) -> Item:
        pin = Pin(id=r["pin_id"], src=r["src"], title=r["title"], video_url=r["video"] or None,
                  width=r["width"], height=r["height"], sig=r["sig"], alt=r["alt"], link=r["link"])
        return Item(id=r["id"], pin=pin, kind=r["kind"], path=r["path"], query=r["query"],
                    score=r["score"], added=r["added"])

    def get(self, path: str) -> Optional[Item]:
        with self._lock:
            r = self._db.execute("SELECT * FROM items WHERE path = ?",
                                 (os.path.abspath(path),)).fetchone()
        return self._item(r) if r else None

    def count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM items").fetchone()[0]

    def recent(self, limit: int = 60) -> list[Item]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM items ORDER BY added DESC LIMIT ?",
                                    (limit * 2,)).fetchall()
        return [self._item(r) for r in rows if os.path.exists(r["path"])][:limit]

    def search(self, text: str, limit: int = 60, clip=None) -> list[Item]:
        """Downloads matching *text*: every word must appear in the search, title
        or description. With the smart model (*clip*), pictures that merely
        *show* what the text says are found too, best fit first."""
        words = [w for w in text.lower().split() if w]
        if not words:
            return self.recent(limit)
        where = " AND ".join("(lower(query) LIKE ? OR lower(title) LIKE ? OR lower(alt) LIKE ?)"
                             for _ in words)
        args = [f"%{w}%" for w in words for _ in range(3)]
        with self._lock:
            rows = self._db.execute(f"SELECT * FROM items WHERE {where} ORDER BY added DESC"
                                    " LIMIT ?", (*args, limit * 2)).fetchall()
            out = [self._item(r) for r in rows if os.path.exists(r["path"])][:limit]
            if clip is None or len(out) >= limit:
                return out
            embs = self._db.execute("SELECT * FROM items WHERE emb IS NOT NULL").fetchall()
        if not embs:
            return out
        try:
            q = clip.text(f"a picture of {text}") - 0.5 * clip.text("a picture")
        except Exception:
            return out
        mat = np.frombuffer(b"".join(r["emb"] for r in embs), dtype=np.float32).reshape(len(embs), -1)
        sims = mat @ q
        have = {i.path for i in out}
        # only clear fits: well above what an unrelated picture scores
        bar = max(float(np.median(sims)) + 0.035, float(sims.max()) - 0.05)
        for i in np.argsort(-sims):
            if len(out) >= limit or sims[i] < bar:
                break
            r = embs[i]
            if r["path"] not in have and os.path.exists(r["path"]):
                out.append(self._item(r))
        return out

    def missing_embeddings(self, limit: int = 200) -> list[tuple[str, str]]:
        """(path, kind) of pictures the smart model hasn't looked at yet."""
        with self._lock:
            rows = self._db.execute(
                "SELECT path, kind FROM items WHERE emb IS NULL AND kind != 'video'"
                " ORDER BY added DESC LIMIT ?", (limit,)).fetchall()
        return [(r["path"], r["kind"]) for r in rows]

    def set_embedding(self, path: str, emb: np.ndarray) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE items SET emb = ? WHERE path = ?",
                             (emb.astype(np.float32).tobytes(), os.path.abspath(path)))


    # ── follows ─────────────────────────────────────────────────────────
    def follow(self, query: str, folder: str, counts: dict, min_side: int = 0,
               shape: str = "any") -> Follow:
        """Start following a search or board (or update one already followed)."""
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO follows (query, folder, image, video, gif, min_side, shape, added)"
                " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(query, folder) DO UPDATE SET"
                " image=excluded.image, video=excluded.video, gif=excluded.gif,"
                " min_side=excluded.min_side, shape=excluded.shape",
                (query, folder, counts.get("image", 0), counts.get("video", 0),
                 counts.get("gif", 0), min_side, shape, time.time()))
            r = self._db.execute("SELECT * FROM follows WHERE query = ? AND folder = ?",
                                 (query, folder)).fetchone()
        return _follow(r)

    def follows(self) -> list:
        with self._lock:
            return [_follow(r) for r in self._db.execute("SELECT * FROM follows ORDER BY added")]

    def unfollow(self, follow_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM follows WHERE id = ?", (follow_id,))
            self._db.execute("DELETE FROM follow_seen WHERE follow_id = ?", (follow_id,))

    def follow_checked(self, follow_id: int, new: int) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE follows SET checked = ?, last_new = ?, total = total + ?"
                             " WHERE id = ?", (time.time(), new, new, follow_id))

    def follow_saw(self, follow_id: int, key: str) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM follow_seen WHERE follow_id = ? AND key = ?",
                                    (follow_id, key)).fetchone() is not None

    def follow_mark(self, follow_id: int, key: str) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR IGNORE INTO follow_seen (follow_id, key) VALUES (?, ?)",
                             (follow_id, key))


_shared: Optional[Library] = None
_shared_lock = threading.Lock()


def shared() -> Library:
    """The app-wide library (opened on first use)."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = Library()
        return _shared
