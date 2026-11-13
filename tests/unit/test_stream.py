"""The streaming pipeline, with Pinterest and the network faked."""

import queue
import threading

import pytest
from PIL import Image

from pinmass import media, net, scraper, worker
from pinmass.matching import Matcher, MatchSettings, Score, StreamSelector
from pinmass.scraper import Pin
from pinmass.worker import Job, Worker


def pin(i, kind="image", **kw):
    ext = "gif" if kind == "gif" else "jpg"
    return Pin(id=f"p{i}", src=f"https://i.pinimg.com/originals/aa/bb/{i}.{ext}",
               video_url="https://v/x.mp4" if kind == "video" else None, **kw)


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """Endless fake search; downloads just create an empty file."""
    state = {"pulled": 0, "fail": set()}

    def iter_pins(query, stop=None, log=None, scope="pins", fallback=200):
        i = 0
        while not (stop and stop.is_set()) and i < 5000:
            i += 1
            state["pulled"] += 1
            kind = "video" if scope == "videos" else "gif" if query.endswith(" gif") else "image"
            yield pin(f"{scope}{kind}{i}", kind)

    def download(p, out_dir, want, stop):
        if p.id in state["fail"]:
            return None, "network"
        path = tmp_path / f"{p.id}.bin"
        path.write_bytes(b"x")
        return str(path), "ok"

    monkeypatch.setattr(scraper, "iter_pins", iter_pins)
    monkeypatch.setattr(media, "download", download)
    monkeypatch.setattr(net, "tune", lambda: False)
    return state


def run(job):
    events = queue.Queue()
    w = Worker(job, events)
    t = threading.Thread(target=w.run, daemon=True)
    t.start()
    t.join(20)
    assert not t.is_alive(), "worker hung"
    out = []
    while not events.empty():
        out.append(events.get())
    return w, out


def test_stops_searching_once_enough_is_saved(fake, tmp_path):
    w, events = run(Job("cats", str(tmp_path), {"image": 20, "video": 0, "gif": 0}))
    assert w.saved["image"] == 20
    assert sum(e.type == "saved" for e in events) == 20
    assert fake["pulled"] < 100      # the old pipeline would have pulled the whole pool first
    assert events[-1].type == "done"


def test_each_kind_gets_its_own_source_and_exact_count(fake, tmp_path):
    w, events = run(Job("cats", str(tmp_path), {"image": 5, "video": 3, "gif": 2}))
    assert w.saved == {"image": 5, "video": 3, "gif": 2}
    kinds = [e.kind for e in events if e.type == "saved"]
    assert sorted(kinds) == ["gif"] * 2 + ["image"] * 5 + ["video"] * 3


def test_failed_downloads_are_replaced(fake, tmp_path):
    fake["fail"] = {f"ppinsimage{i}" for i in range(1, 8)}
    w, events = run(Job("cats", str(tmp_path), {"image": 10, "video": 0, "gif": 0}))
    assert w.saved["image"] == 10
    assert w.failed["image"]["network"] >= 1


def test_runs_dry_gracefully(monkeypatch, fake, tmp_path):
    monkeypatch.setattr(scraper, "iter_pins",
                        lambda q, stop=None, log=None, scope="pins", fallback=200:
                        iter([pin(1), pin(2), pin(3)]))
    w, events = run(Job("cats", str(tmp_path), {"image": 10, "video": 0, "gif": 0}))
    assert w.saved["image"] == 3
    assert any("Only 3 pictures" in e.text for e in events if e.type == "log")


def test_stop_ends_the_run(fake, tmp_path):
    events = queue.Queue()
    w = Worker(Job("cats", str(tmp_path), {"image": 4000, "video": 0, "gif": 0}), events)
    t = threading.Thread(target=w.run, daemon=True)
    t.start()
    w.stop()
    t.join(10)
    assert not t.is_alive()


def test_stream_selector_holds_back_until_it_knows_the_pool(tmp_path):
    ref = tmp_path / "ref.png"
    Image.new("RGB", (32, 32), (200, 30, 30)).save(ref)
    sel = StreamSelector(Matcher(MatchSettings(reference=str(ref), look=True, closeness=50,
                                                smart=False)))
    out = []
    for i in range(StreamSelector.WARMUP - 1):
        out += sel.add(i, Score(look=50 + i))          # 50..78
    assert out == []                                    # still warming up
    out += sel.add(99, Score(look=95))
    kept = {item for item, _ in out}
    assert 99 in kept and 0 not in kept                 # best in, worst out
    assert 0.2 < len(kept) / StreamSelector.WARMUP < 0.5   # closeness 50 keeps about a third
    assert sel.add(100, Score(look=10)) == []


def test_stream_selector_flush_decides_a_small_pool(tmp_path):
    ref = tmp_path / "ref.png"
    Image.new("RGB", (32, 32), (200, 30, 30)).save(ref)
    sel = StreamSelector(Matcher(MatchSettings(reference=str(ref), look=True, closeness=0,
                                                smart=False)))
    for i in range(5):
        assert sel.add(i, Score(look=60 + i)) == []
    assert len(sel.flush()) >= 2 and sel.flush() == []


def test_client_reports_rate_limits(monkeypatch):
    class Resp:
        status_code = 429
        headers = {"Retry-After": "0"}

    class Sess:
        def get(self, *a, **k):
            return Resp()

    c = scraper.Client()
    monkeypatch.setattr(c, "session", lambda fresh=False: Sess())
    with pytest.raises(scraper.ScrapeError) as err:
        c.get("BaseSearchResource", {})
    assert err.value.status == 429 and "rate-limiting" in str(err.value)


def test_parse_item_reads_size_signature_and_skips_ads():
    item = {"id": "9", "image_signature": "abc", "auto_alt_text": "a cat",
            "images": {"orig": {"url": "https://i.pinimg.com/originals/x.jpg", "width": 600, "height": 900}}}
    p = scraper.parse_item(item)
    assert (p.width, p.height, p.sig, p.alt, p.key) == (600, 900, "abc", "a cat", "abc")
    assert scraper.parse_item(dict(item, is_promoted=True)) is None


def test_more_like_this_searches_for_what_the_picture_shows(monkeypatch, fake, tmp_path):
    from pinmass.worker import similar_job
    asked = []

    def iter_pins(query, stop=None, log=None, scope="pins", fallback=200):
        asked.append(query)
        return iter([pin(f"{len(asked)}-{i}") for i in range(3)])

    def no_related(pin_id, stop=None):
        raise scraper.ScrapeError("login needed", 404)

    monkeypatch.setattr(scraper, "iter_pins", iter_pins)
    monkeypatch.setattr(scraper, "iter_related", no_related)
    monkeypatch.setattr(media, "fetch_bytes", lambda url, **kw: None)   # nothing can be scored
    ref = tmp_path / "seed.jpg"
    Image.new("RGB", (16, 16), (10, 200, 10)).save(ref, "JPEG")
    seed = pin("seed", alt="a green square", title="Green")
    job = similar_job(seed, str(ref), Job("squares", str(tmp_path), {"image": 5, "video": 0, "gif": 0}),
                      "squares")
    assert job.seed is seed and job.match.look and job.match.reference == str(ref)
    assert job.out_dir == str(tmp_path)
    run(job)
    assert sorted(asked) == ["Green", "a green square", "squares"]


def test_similar_queries_drops_blanks_links_and_repeats():
    p = pin(1, alt="  a   red  car ", title="A red car")
    assert scraper.similar_queries(p, "https://www.pinterest.com/a/b/") == ["a red car"]


def test_preview_shows_candidates_without_saving_anything(monkeypatch, fake, tmp_path):
    monkeypatch.setattr(media, "fetch_bytes", lambda url, **kw: b"thumb")
    job = Job("cats", str(tmp_path / "out"), {"image": 6, "video": 0, "gif": 0}, preview=True)
    w, events = run(job)
    cands = [e for e in events if e.type == "candidate"]
    assert len(cands) == 6 and all(e.data == b"thumb" and e.pin for e in cands)
    assert not any(e.type == "saved" for e in events)
    assert events[-1].type == "done" and events[-1].preview
    assert not any((tmp_path / "out").glob("*"))


def test_picks_job_downloads_exactly_the_picks(fake, tmp_path):
    from pinmass.worker import picks_job
    picks = [pin("a"), pin("b", "video"), pin("c")]
    base = Job("cats", str(tmp_path), {"image": 50, "video": 0, "gif": 0}, scores={"pa": 88.0})
    job = picks_job(picks, base)
    assert job.counts == {"image": 2, "video": 1, "gif": 0}
    w, events = run(job)
    saved = {e.pin.id: e.score for e in events if e.type == "saved"}
    assert saved == {"pa": 88.0, "pb": None, "pc": None}
    assert fake["pulled"] == 0          # nothing was searched for


def test_excluded_pins_are_not_offered_again(monkeypatch, fake, tmp_path):
    monkeypatch.setattr(scraper, "iter_pins",
                        lambda q, stop=None, log=None, scope="pins", fallback=200:
                        iter([pin(i) for i in range(6)]))
    job = Job("cats", str(tmp_path), {"image": 6, "video": 0, "gif": 0}, exclude={"p0", "p1"})
    w, events = run(job)
    assert sorted(e.pin.id for e in events if e.type == "saved") == ["p2", "p3", "p4", "p5"]


def test_fits_checks_size_and_shape_from_search_data():
    from pinmass.worker import fits
    tall, wide, square, unknown = (pin(1, width=1080, height=1920), pin(2, width=1920, height=1080),
                                   pin(3, width=800, height=820), pin(4))
    assert fits(tall, 1000, "tall") and not fits(tall, 1200, "tall") and not fits(tall, 0, "wide")
    assert fits(wide, 0, "wide") and not fits(wide, 0, "square")
    assert fits(square, 0, "square") and not fits(square, 0, "tall")
    assert fits(unknown, 2000, "wide")           # no size on record: give it the benefit of the doubt


def test_quality_filter_skips_before_downloading(monkeypatch, fake, tmp_path):
    pins = [pin(i, width=400 if i % 2 else 1200, height=1600) for i in range(20)]
    monkeypatch.setattr(scraper, "iter_pins",
                        lambda q, stop=None, log=None, scope="pins", fallback=200: iter(pins))
    w, events = run(Job("x", str(tmp_path), {"image": 20, "video": 0, "gif": 0}, min_side=1000,
                        shape="tall"))
    saved = [e.pin for e in events if e.type == "saved"]
    assert len(saved) == 10 and all(p.width == 1200 for p in saved)
    assert w.skipped["quality"] == 10
