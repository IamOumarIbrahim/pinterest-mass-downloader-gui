import os
import queue
import threading

import numpy as np
import pytest
from PIL import Image, ImageDraw

from pinmass import media, net, scraper
from pinmass.library import Library, dhash_of
from pinmass.scraper import Pin
from pinmass.worker import Job, Worker


def picture(path, seed=0, size=64, quality=90):
    """A picture with enough structure to hash; *seed* picks which picture,
    *size* and *quality* how it was saved."""
    rng = np.random.default_rng(seed)
    im = Image.new("RGB", (256, 256), tuple(int(c) for c in rng.integers(0, 255, 3)))
    d = ImageDraw.Draw(im)
    for _ in range(6):
        x, y = (int(v) for v in rng.integers(0, 190, 2))
        d.rectangle([x, y, x + 64, y + 64], fill=tuple(int(c) for c in rng.integers(0, 255, 3)))
    im.resize((size, size), Image.Resampling.LANCZOS).save(path, "JPEG", quality=quality)
    return str(path)


def pin(i, sig="", **kw):
    return Pin(id=f"p{i}", src=f"https://i.pinimg.com/originals/aa/bb/{i}.jpg", sig=sig, **kw)


@pytest.fixture
def lib(tmp_path):
    lib = Library(str(tmp_path / "library.db"))
    yield lib
    lib.close()


def test_remembers_pins_and_the_same_picture_under_another_pin(lib, tmp_path):
    path = picture(tmp_path / "a.jpg")
    lib.add(pin(1, sig="s1", title="Red car", alt="a red car on a road"), "image", path, "cars", 80.0)
    assert lib.have(pin(1), "image") == os.path.abspath(path)
    assert lib.have(pin(99, sig="s1"), "image") == os.path.abspath(path)   # a re-pin
    assert lib.have(pin(99, sig="other"), "image") is None
    assert lib.have(pin(1), "video") is None
    item = lib.get(path)
    assert (item.pin.title, item.pin.alt, item.query, item.score) == ("Red car", "a red car on a road", "cars", 80.0)


def test_forgets_files_that_were_deleted(lib, tmp_path):
    path = picture(tmp_path / "a.jpg")
    lib.add(pin(1, sig="s1"), "image", path)
    os.remove(path)
    assert lib.have(pin(1, sig="s1"), "image") is None
    assert lib.count() == 0


def test_near_duplicates_are_found_across_sizes_and_quality(lib, tmp_path):
    original = picture(tmp_path / "a.jpg", seed=1, size=256)
    smaller = picture(tmp_path / "b.jpg", seed=1, size=128, quality=40)   # same picture, re-saved
    different = picture(tmp_path / "c.jpg", seed=2)
    lib.add(pin(1), "image", original, dhash=dhash_of(original))
    assert lib.near_duplicate(dhash_of(smaller)) == os.path.abspath(original)
    assert lib.near_duplicate(dhash_of(different)) is None
    assert lib.near_duplicate(dhash_of(original), ignore=original) is None


def test_search_matches_every_word_across_fields(lib, tmp_path):
    a, b = picture(tmp_path / "a.jpg", 1), picture(tmp_path / "b.jpg", 2)
    lib.add(pin(1, title="Sunset"), "image", a, "beach")
    lib.add(pin(2, alt="a red car at the beach"), "image", b, "cars")
    assert [i.pin.id for i in lib.search("beach")] == ["p2", "p1"]       # newest first
    assert [i.pin.id for i in lib.search("red beach")] == ["p2"]
    assert lib.search("mountain") == []
    assert len(lib.search("")) == 2


def test_search_by_meaning_with_the_smart_model(lib, tmp_path):
    class Clip:
        def text(self, phrase):
            return np.array([1, 0, 0] if "dog" in phrase else [0, 0, 1], dtype=np.float32)

    paths = [picture(tmp_path / f"{i}.jpg", i) for i in range(4)]
    for i, p in enumerate(paths):
        emb = np.array([0.9, 0.1, 0] if i == 2 else [0, 1, 0], dtype=np.float32)
        lib.add(pin(i, title="untitled"), "image", p, "pets", emb=emb)
    assert lib.search("dog") == []                       # no word says "dog"…
    assert [i.pin.id for i in lib.search("dog", clip=Clip())] == ["p2"]   # …but one picture shows it


# ── the worker using the library ────────────────────────────────────────────
def run(job):
    events = queue.Queue()
    w = Worker(job, events)
    t = threading.Thread(target=w.run, daemon=True)
    t.start()
    t.join(20)
    assert not t.is_alive()
    out = []
    while not events.empty():
        out.append(events.get())
    return w, out


@pytest.fixture
def pinterest(monkeypatch, tmp_path):
    """Search results p0..p11; pictures repeat every 4 (p4 looks like p0, …)."""
    pins = [pin(i, sig=f"sig{i}") for i in range(12)]
    pins[1] = pin(1, sig="sig0")            # an exact re-pin of p0

    def download(p, out_dir, want, stop):
        os.makedirs(out_dir, exist_ok=True)
        i = int(p.id[1:])
        return picture(os.path.join(out_dir, f"{p.id}.jpg"), seed=i % 4, size=64 + 16 * (i // 4)), "ok"

    monkeypatch.setattr(scraper, "iter_pins", lambda q, stop=None, log=None, scope="pins", fallback=200: iter(pins))
    monkeypatch.setattr(media, "download", download)
    monkeypatch.setattr(net, "tune", lambda: False)
    return pins


def test_worker_drops_repins_and_near_duplicates(pinterest, lib, tmp_path):
    out = tmp_path / "out"
    # one download at a time, so which copy of a look-alike arrives first is fixed
    w, events = run(Job("x", str(out), {"image": 12, "video": 0, "gif": 0}, library=lib, threads=1))
    saved = sorted(e.pin.id for e in events if e.type == "saved")
    # p1 is a re-pin of p0, so picture 1 first turns up as p5; everything else repeats those four
    assert saved == ["p0", "p2", "p3", "p5"]
    assert w.skipped["repost"] == 1 and w.failed["image"]["duplicate"] == 7
    assert sorted(os.listdir(out)) == ["p0.jpg", "p2.jpg", "p3.jpg", "p5.jpg"]
    assert lib.count() == 4 and lib.get(str(out / "p0.jpg")).query == "x"


def test_second_run_skips_what_the_library_has_even_in_another_folder(pinterest, lib, tmp_path):
    run(Job("x", str(tmp_path / "one"), {"image": 2, "video": 0, "gif": 0}, library=lib, threads=1))
    w, events = run(Job("x", str(tmp_path / "two"), {"image": 12, "video": 0, "gif": 0}, library=lib))
    assert w.skipped["owned"] == 2
    assert not any(e.pin.id in ("p0", "p2") for e in events if e.type == "saved")
    w, events = run(Job("x", str(tmp_path / "three"), {"image": 2, "video": 0, "gif": 0},
                        library=lib, skip_owned=False))
    assert w.saved["image"] == 2             # asked for duplicates: gets them


# ── following ───────────────────────────────────────────────────────────────
def test_follow_fetches_only_what_is_new_and_never_brings_back_deleted(monkeypatch, lib, tmp_path):
    from pinmass.worker import follow_job
    board = [pin(i, sig=f"s{i}") for i in range(3)]

    def download(p, out_dir, want, stop):
        os.makedirs(out_dir, exist_ok=True)
        return picture(os.path.join(out_dir, f"{p.id}.jpg"), seed=int(p.id[1:]) + 50), "ok"

    monkeypatch.setattr(scraper, "iter_pins", lambda q, stop=None, log=None, scope="pins", fallback=200: iter(list(board)))
    monkeypatch.setattr(media, "download", download)
    monkeypatch.setattr(net, "tune", lambda: False)
    link = "https://www.pinterest.com/someone/board/"
    f = lib.follow(link, str(tmp_path / "board"), {"image": 50, "video": 0, "gif": 0})
    assert lib.follow(link, str(tmp_path / "board"), {"image": 50}).id == f.id     # no double follow

    w, events = run(follow_job(f, lib, threads=1))
    assert w.saved["image"] == 3 and any("3 new pictures" in e.text for e in events if e.type == "log")
    lib.follow_checked(f.id, 3)

    w, _ = run(follow_job(f, lib, threads=1))            # nothing changed on the board
    assert w.saved["image"] == 0 and w.skipped["owned"] == 3

    os.remove(tmp_path / "board" / "p1.jpg")             # the user threw one away…
    board.insert(0, pin(7, sig="s7"))                    # …and the board got a new pin
    w, events = run(follow_job(f, lib, threads=1))
    assert [e.pin.id for e in events if e.type == "saved"] == ["p7"]    # p1 does not come back
    lib.follow_checked(f.id, 1)
    got = lib.follows()[0]
    assert (got.total, got.last_new) == (4, 1) and got.checked > 0
    lib.unfollow(f.id)
    assert lib.follows() == []
