"""Integration test verifying installed pinterest-dl public API compatibility."""

import inspect

import pinterest_dl
from pinterest_dl import PinterestDL
from pinterest_dl.download.downloader import MediaDownloader

from pinterest_mass_downloader.services.pinterest_adapter import PinterestDLAdapter


def test_pinterest_dl_version():
    assert hasattr(pinterest_dl, "__version__")


def test_pinterest_dl_public_methods():
    assert hasattr(PinterestDL, "with_api")
    scraper = PinterestDL.with_api()

    assert hasattr(scraper, "search")
    assert hasattr(scraper, "scrape")
    assert hasattr(scraper, "with_cookies_path")

    search_sig = inspect.signature(scraper.search)
    assert "query" in search_sig.parameters
    assert "num" in search_sig.parameters

    scrape_sig = inspect.signature(scraper.scrape)
    assert "url" in scrape_sig.parameters
    assert "num" in scrape_sig.parameters


def test_media_downloader_public_methods():
    assert hasattr(MediaDownloader, "download_concurrent")
    sig = inspect.signature(MediaDownloader.download_concurrent)
    assert "media_list" in sig.parameters
    assert "output_dir" in sig.parameters
    assert "max_workers" in sig.parameters


def test_adapter_instantiation():
    adapter = PinterestDLAdapter()
    assert hasattr(adapter, "scrape_or_search")
    assert hasattr(adapter, "download_media_items")
