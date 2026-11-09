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
