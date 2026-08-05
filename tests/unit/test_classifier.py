"""Unit tests for classification, deduplication, and selection."""

from pinterest_mass_downloader.domain.enums import MediaType
from pinterest_mass_downloader.services.classifier import (
    classify_media,
    get_media_identifier,
    select_media_items,
)
from tests.fakes import MockPinterestMedia


def test_classification_image():
    img = MockPinterestMedia(id="1", src="https://i.pinimg.com/image.jpg")
    assert classify_media(img) == MediaType.IMAGE


def test_classification_gif():
    gif = MockPinterestMedia(id="2", src="https://i.pinimg.com/anim.GIF?query=1")
    assert classify_media(gif) == MediaType.GIF


def test_classification_video():
    vid = MockPinterestMedia(
        id="3", src="https://i.pinimg.com/poster.jpg", is_video=True, video_url="https://v.mp4"
    )
    assert classify_media(vid) == MediaType.VIDEO


def test_media_identifier():
    item1 = MockPinterestMedia(id="pin123", src="https://i.pinimg.com/1.jpg")
    assert get_media_identifier(item1) == "pin123"

    item2 = MockPinterestMedia(id="", src="https://i.pinimg.com/sub/image.jpg")
    assert get_media_identifier(item2) == "i.pinimg.com/sub/image.jpg"


def test_deduplication_and_selection():
    items = [
        MockPinterestMedia(id="1", src="https://i.pinimg.com/1.jpg"),
        MockPinterestMedia(id="1", src="https://i.pinimg.com/1.jpg"),  # Duplicate
        MockPinterestMedia(id="2", src="https://i.pinimg.com/2.jpg"),
        MockPinterestMedia(id="3", src="https://i.pinimg.com/3.gif"),
    ]

    selected, counts = select_media_items(
        items=items,
        requested_images=1,
        requested_videos=0,
        requested_gifs=1,
    )

    assert len(selected) == 2
    assert counts[MediaType.IMAGE.value].found == 2
    assert counts[MediaType.IMAGE.value].selected == 1
    assert counts[MediaType.IMAGE.value].skipped == 2
    assert counts[MediaType.GIF.value].selected == 1
