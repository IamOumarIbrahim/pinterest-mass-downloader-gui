"""Fake adapter and mock media items for testing."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Tuple

from pinterest_mass_downloader.domain.enums import BackendType, InputMode
from pinterest_mass_downloader.domain.errors import AdapterError


@dataclass
class MockPinterestMedia:
    id: str
    src: str
    is_video: bool = False
    video_url: Optional[str] = None


class FakePinterestAdapter:
    """Fake Pinterest adapter for deterministic offline testing."""

    def __init__(self, media_items: Optional[List[Any]] = None, raise_error: bool = False):
        self.media_items = media_items or []
        self.raise_error = raise_error
        self.last_scrape_kwargs: dict = {}
        self.downloaded_items: List[Any] = []

    def scrape_or_search(
        self,
        mode: InputMode,
        query_or_url: str,
        limit: int,
        cookies_path: Optional[str] = None,
        min_resolution: Tuple[int, int] = (0, 0),
        backend: BackendType = BackendType.API,
    ) -> List[Any]:
        if self.raise_error:
            raise AdapterError("Simulated scraper failure")

        self.last_scrape_kwargs = {
            "mode": mode,
            "query_or_url": query_or_url,
            "limit": limit,
            "cookies_path": cookies_path,
            "min_resolution": min_resolution,
            "backend": backend,
        }

        # Return items up to limit
        return self.media_items[:limit]

    def download_media_items(
        self,
        media_items: List[Any],
        output_dir: Path,
        raw_video: bool = False,
        max_workers: int = 8,
    ) -> List[Path]:
        if self.raise_error:
            raise AdapterError("Simulated download failure")

        output_dir.mkdir(parents=True, exist_ok=True)
        downloaded = []
        for idx, item in enumerate(media_items):
            self.downloaded_items.append(item)
            item_id = getattr(item, "id", f"file_{idx}")
            ext = ".mp4" if getattr(item, "is_video", False) else ".jpg"
            file_path = output_dir / f"{item_id}{ext}"
            file_path.write_bytes(b"dummy_media_bytes")
            downloaded.append(file_path)

        return downloaded
