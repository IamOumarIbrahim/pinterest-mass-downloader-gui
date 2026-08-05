"""Unit tests for PinterestDLAdapter with mocks."""

from unittest.mock import MagicMock

import pytest

from pinterest_mass_downloader.domain.enums import InputMode
from pinterest_mass_downloader.domain.errors import AdapterError
from pinterest_mass_downloader.services.pinterest_adapter import PinterestDLAdapter


def test_adapter_search_keyword(monkeypatch):
    mock_scraper = MagicMock()
    mock_scraper.search.return_value = ["item1", "item2"]

    monkeypatch.setattr(
        "pinterest_mass_downloader.services.pinterest_adapter.PinterestDL.with_api",
        lambda: mock_scraper,
    )

    adapter = PinterestDLAdapter()
    res = adapter.scrape_or_search(mode=InputMode.KEYWORD, query_or_url="architecture", limit=5)
    assert res == ["item1", "item2"]
    mock_scraper.search.assert_called_once()


def test_adapter_scrape_url(monkeypatch):
    mock_scraper = MagicMock()
    mock_scraper.scrape.return_value = ["item1"]

    monkeypatch.setattr(
        "pinterest_mass_downloader.services.pinterest_adapter.PinterestDL.with_api",
        lambda: mock_scraper,
    )

    adapter = PinterestDLAdapter()
    res = adapter.scrape_or_search(
        mode=InputMode.URL, query_or_url="https://www.pinterest.com/board/", limit=5
    )
    assert res == ["item1"]
    mock_scraper.scrape.assert_called_once()


def test_adapter_error_handling(monkeypatch):
    def failing_with_api():
        raise RuntimeError("API failure")

    monkeypatch.setattr(
        "pinterest_mass_downloader.services.pinterest_adapter.PinterestDL.with_api",
        failing_with_api,
    )

    adapter = PinterestDLAdapter()
    with pytest.raises(AdapterError, match="Pinterest scrape/search failed"):
        adapter.scrape_or_search(mode=InputMode.KEYWORD, query_or_url="cats", limit=1)


def test_adapter_download_media_items(tmp_path, monkeypatch):
    mock_downloader = MagicMock()
    mock_downloader.download_concurrent.return_value = [str(tmp_path / "out.jpg")]

    monkeypatch.setattr(
        "pinterest_mass_downloader.services.pinterest_adapter.MediaDownloader",
        lambda user_agent: mock_downloader,
    )

    adapter = PinterestDLAdapter()
    out = adapter.download_media_items(["dummy_item"], tmp_path)
    assert out == [tmp_path / "out.jpg"]
