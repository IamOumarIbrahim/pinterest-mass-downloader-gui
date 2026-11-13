"""The phone server: who gets in, and starting downloads from the phone."""

import json
import urllib.error
import urllib.request

import pytest
from PIL import Image

from pinmass import library, phone, remote
from pinmass.scraper import Pin


class FakeControl:
    def __init__(self):
        self.asked = []
        self.stopped = 0

    def submit(self, query, counts):
        if not query.strip():
            return "Type something to search for."
        self.asked.append((query, remote.clean_counts(counts)))
        return None

    def status(self):
        return dict(remote.idle_status(), running=bool(self.asked), query="cats", done=3, total=10)

    def stop(self):
        self.stopped += 1


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    lib = library.Library(str(tmp_path / "library.db"))
    monkeypatch.setattr(library, "_shared", lib)
    root = tmp_path / "pics"
    (root / "cats").mkdir(parents=True)
    Image.new("RGB", (40, 40), (200, 10, 10)).save(root / "cats" / "a.jpg")
    Image.new("RGB", (40, 40), (10, 10, 200)).save(root / "cats" / "b.jpg")
    lib.add(Pin(id="a", src="", title="Ginger cat"), "image", str(root / "cats" / "a.jpg"), "cats")
    lib.add(Pin(id="b", src="", title="Blue sky"), "image", str(root / "cats" / "b.jpg"), "sky")
    control = FakeControl()
    srv = phone.PhoneServer(str(root), "secret", port=18765, https=False, control=control)
    srv.start()
    yield srv, control
    srv.stop()
    lib.close()


def call(path, body=None, token="secret"):
    url = f"http://127.0.0.1:18765{path}{'&' if '?' in path else '?'}t={token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def test_needs_the_token_for_everything(server):
    for path, body in (("/api/albums", None), ("/api/status", None), ("/api/download", {"query": "x"})):
        with pytest.raises(urllib.error.HTTPError) as err:
            call(path, body, token="wrong")
        assert err.value.code == 403
    assert server[1].asked == []


def test_download_request_reaches_the_control_with_safe_counts(server):
    srv, control = server
    assert call("/api/download", {"query": "fortnite llama", "image": "30", "video": 9999, "gif": -4}) == {
        "ok": True, "error": ""}
    assert control.asked == [("fortnite llama", {"image": 30, "video": remote.MAX_PER_REQUEST, "gif": 0})]
    assert call("/api/download", {"query": "  "})["error"] == "Type something to search for."
    call("/api/stop", {})
    assert control.stopped == 1


def test_status_says_whether_downloads_can_be_started(server):
    st = call("/api/status")
    assert st["can_download"] and st["total"] == 10 and st["done"] == 3


def test_search_finds_downloads_under_the_shared_folder(server):
    assert [i["name"] for i in call("/api/search?q=ginger")["items"]] == ["a.jpg"]
    assert call("/api/search?q=sky")["items"][0]["path"] == "cats/b.jpg"
    assert call("/api/search?q=dinosaur")["items"] == []


def test_headless_control_refuses_empty_requests(tmp_path):
    c = remote.Control(str(tmp_path), {"threads": 2})
    assert c.submit("", {"image": 5})
    assert c.submit("cats", {"image": 0})
    assert c.status()["running"] is False
