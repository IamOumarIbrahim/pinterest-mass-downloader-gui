"""PinterestDL adapter wrapping public pinterest-dl API calls."""

import inspect
from pathlib import Path
from typing import Any, List, Optional, Protocol, Tuple

from pinterest_dl import PinterestDL
from pinterest_dl.download.downloader import MediaDownloader

from pinterest_mass_downloader.domain.enums import BackendType, InputMode
from pinterest_mass_downloader.domain.errors import AdapterError


class IPinterestAdapter(Protocol):
    """Protocol for Pinterest scraper/downloader operations."""

    def scrape_or_search(
        self,
        mode: InputMode,
        query_or_url: str,
        limit: int,
        cookies_path: Optional[str] = None,
        min_resolution: Tuple[int, int] = (0, 0),
        backend: BackendType = BackendType.API,
    ) -> List[Any]: ...

    def download_media_items(
        self,
        media_items: List[Any],
        output_dir: Path,
        raw_video: bool = False,
        max_workers: int = 8,
    ) -> List[Path]: ...


class PinterestDLAdapter:
    """Production implementation using public pinterest-dl API."""

    def scrape_or_search(
        self,
        mode: InputMode,
        query_or_url: str,
        limit: int,
        cookies_path: Optional[str] = None,
        min_resolution: Tuple[int, int] = (0, 0),
        backend: BackendType = BackendType.API,
    ) -> List[Any]:
        """Scrape board/pin URL or search keyword using public PinterestDL API."""
        try:
            if backend == BackendType.API:
                scraper = PinterestDL.with_api()
            elif backend in (BackendType.CHROMIUM, BackendType.FIREFOX):
                if hasattr(PinterestDL, "with_browser"):
                    scraper = PinterestDL.with_browser(browser_type=backend.value)
                else:
                    scraper = PinterestDL.with_api()
            else:
                scraper = PinterestDL.with_api()

            if cookies_path:
                cp = Path(cookies_path)
                if cp.exists() and hasattr(scraper, "with_cookies_path"):
                    scraper = scraper.with_cookies_path(cp)

            if mode == InputMode.KEYWORD:
                sig = inspect.signature(scraper.search)
                kwargs: dict = {"query": query_or_url, "num": limit}
                if "min_resolution" in sig.parameters:
                    kwargs["min_resolution"] = min_resolution
                results = scraper.search(**kwargs)
            else:
                sig = inspect.signature(scraper.scrape)
                kwargs = {"url": query_or_url, "num": limit}
                if "min_resolution" in sig.parameters:
                    kwargs["min_resolution"] = min_resolution
                results = scraper.scrape(**kwargs)

            return results or []
        except Exception as e:
            raise AdapterError(f"Pinterest scrape/search failed: {e}") from e

    def download_media_items(
        self,
        media_items: List[Any],
        output_dir: Path,
        raw_video: bool = False,
        max_workers: int = 8,
    ) -> List[Path]:
        """Download media items using public MediaDownloader.download_concurrent."""
        if not media_items:
            return []

        try:
            downloader = MediaDownloader(user_agent="PinterestMassDownloader/2.0.0")
            downloaded_paths = downloader.download_concurrent(
                media_list=media_items,
                output_dir=output_dir,
                download_streams=True,
                skip_remux=raw_video,
                max_workers=max_workers,
            )
            return [Path(p) for p in downloaded_paths if p]
        except Exception as e:
            raise AdapterError(f"Failed to download media items: {e}") from e
