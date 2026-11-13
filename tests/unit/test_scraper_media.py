from PIL import Image

from pinmass.media import kind_of, sniff
from pinmass.scraper import classify, is_url, parse_item, thumb_url
from pinmass.worker import Job, pool_size


def test_classify_gif_beats_video():
    assert classify("https://i.pinimg.com/originals/a/b.gif", "https://v.mp4") == "gif"
    assert classify("https://i.pinimg.com/originals/a/b.jpg", "https://v.mp4") == "video"
    assert classify("https://i.pinimg.com/originals/a/b.jpg", None) == "image"


def test_is_url():
    assert is_url("https://www.pinterest.com/user/board/")
    assert is_url("https://pin.it/abc")
    assert is_url("https://de.pinterest.de/pin/123/")
    assert not is_url("fortnite skins")


def test_thumb_url():
    assert thumb_url("https://i.pinimg.com/originals/aa/bb/cc.jpg") == "https://i.pinimg.com/236x/aa/bb/cc.jpg"
    assert thumb_url("https://i.pinimg.com/736x/aa/bb/cc.jpg") == "https://i.pinimg.com/236x/aa/bb/cc.jpg"


def test_parse_item_prefers_mp4_video():
    item = {"id": "1", "images": {"orig": {"url": "https://i.pinimg.com/originals/x.jpg"}},
            "videos": {"video_list": {"V_HLSV4": {"url": "https://v/x.m3u8"},
                                      "V_720P": {"url": "https://v/x.mp4"}}}}
    pin = parse_item(item)
    assert pin.video_url == "https://v/x.mp4"
    assert pin.kind == "video"


def test_sniff_and_kind(tmp_path):
    jpg = tmp_path / "a.download"
    Image.new("RGB", (8, 8)).save(jpg, "JPEG")
    assert kind_of(str(jpg)) == "image"
    still = tmp_path / "b.download"
    Image.new("RGB", (8, 8)).save(still, "GIF")
    assert kind_of(str(still)) == "image"  # a single-frame GIF is not what "GIFs" means
    anim = tmp_path / "c.download"
    frames = [Image.new("RGB", (8, 8), c) for c in ((255, 0, 0), (0, 0, 255))]
    frames[0].save(anim, "GIF", save_all=True, append_images=frames[1:])
    assert kind_of(str(anim)) == "gif"
    assert sniff(b"\x00\x00\x00\x18ftypmp42") == "mp4"
    assert sniff(b"<html>") is None


def test_pool_grows_with_rare_types():
    small = pool_size(Job("x", "o", {"image": 20, "video": 0, "gif": 0}))
    big = pool_size(Job("x", "o", {"image": 20, "video": 20, "gif": 0}))
    assert big > small


def test_download_retries_then_uses_resized_rendition(tmp_path, monkeypatch):
    import threading

    from pinmass import media
    from pinmass.scraper import Pin
    tried = []

    def fake_stream(url, path, stop):
        tried.append(url)
        if "/736x/" not in url:
            return False  # the original keeps failing
        Image.new("RGB", (8, 8)).save(path, "JPEG")
        return True

    monkeypatch.setattr(media, "_stream_to", fake_stream)
    monkeypatch.setattr(media.time, "sleep", lambda s: None)
    pin = Pin(id="42", src="https://i.pinimg.com/originals/aa/bb/cc.jpg")
    path, reason = media.download(pin, str(tmp_path), "image", threading.Event())
    assert reason == "ok" and path.endswith("42.jpg")
    assert tried == [pin.src, pin.src, "https://i.pinimg.com/736x/aa/bb/cc.jpg"]


def test_download_reports_wrong_type_and_removes_it(tmp_path, monkeypatch):
    import os
    import threading

    from pinmass import media
    from pinmass.scraper import Pin

    def fake_stream(url, path, stop):
        Image.new("RGB", (8, 8)).save(path, "JPEG")  # a still picture...
        return True

    monkeypatch.setattr(media, "_stream_to", fake_stream)
    pin = Pin(id="7", src="https://x/y.jpg", video_url="https://x/y.mp4")
    path, reason = media.download(pin, str(tmp_path), "video", threading.Event())  # ...asked as video
    assert path is None and reason == "wrong-type"
    assert os.listdir(tmp_path) == []


def test_parse_link_tells_the_kinds_of_pinterest_address_apart():
    from pinmass.scraper import link_name, parse_link
    P = "https://www.pinterest.com"
    assert parse_link(f"{P}/someone/travel-ideas/") == ("board", {"username": "someone", "slug": "travel-ideas"})
    assert parse_link(f"{P}/someone/travel-ideas/japan/")[0] == "section"
    assert parse_link(f"{P}/someone/") == ("profile", {"username": "someone"})
    assert parse_link(f"{P}/someone/_saved/") == ("profile", {"username": "someone"})
    assert parse_link(f"{P}/pin/12345/") == ("pin", {"id": "12345"})
    assert parse_link(f"{P}/pin/a-nice-title--98765/") == ("pin", {"id": "98765"})
    # a pasted search link used to be read as user "search", board "pins"
    assert parse_link(f"{P}/search/pins/?q=fortnite%20llama&rs=typed") == (
        "search", {"query": "fortnite llama", "scope": "pins"})
    assert parse_link(f"{P}/search/videos/?q=cats")[1]["scope"] == "videos"
    assert parse_link(f"{P}/ideas/cozy-bedroom/9123/") == ("search", {"query": "cozy bedroom", "scope": "pins"})
    assert parse_link(f"{P}/search/pins/")[0] == "unknown"
    assert parse_link(f"{P}/settings/")[0] == "unknown"
    assert link_name(f"{P}/search/pins/?q=fortnite%20llama") == "fortnite llama"
    assert link_name(f"{P}/someone/travel-ideas/") == "someone travel-ideas"


def test_read_cookies_from_both_export_formats(tmp_path):
    import json

    from pinmass.scraper import read_cookies, signed_in
    txt = tmp_path / "cookies.txt"
    txt.write_text("# Netscape HTTP Cookie File\n"
                   ".pinterest.com\tTRUE\t/\tTRUE\t1999999999\t_auth\t1\n"
                   "#HttpOnly_.pinterest.com\tTRUE\t/\tTRUE\t1999999999\t_pinterest_sess\tabc\n"
                   ".example.com\tTRUE\t/\tTRUE\t1999999999\tother\tx\n", encoding="utf-8")
    assert read_cookies(str(txt)) == {"_auth": "1", "_pinterest_sess": "abc"}
    assert signed_in(read_cookies(str(txt)))
    js = tmp_path / "cookies.json"
    js.write_text(json.dumps([{"name": "_auth", "value": "0", "domain": ".pinterest.com"},
                              {"name": "sid", "value": "z", "domain": ".example.com"}]), encoding="utf-8")
    assert read_cookies(str(js)) == {"_auth": "0"}
    assert not signed_in(read_cookies(str(js))) and not signed_in(None)


def test_forbidden_gets_one_fresh_session_then_a_clear_error(monkeypatch):
    import pytest

    from pinmass import scraper
    made = []

    class Resp:
        status_code = 403
        headers = {}

    class Sess:
        def get(self, *a, **k):
            return Resp()

    c = scraper.Client()
    monkeypatch.setattr(c, "session", lambda fresh=False: made.append(fresh) or Sess())
    with pytest.raises(scraper.ScrapeError) as err:
        c.get("BaseSearchResource", {})
    assert made == [False, True] and err.value.status == 403
