"""Media classification, deduplication, and selection logic."""

from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

from pinterest_mass_downloader.domain.enums import MediaType
from pinterest_mass_downloader.domain.models import MediaCountSummary


def classify_media(item: Any) -> MediaType:
    """Classify a media item as IMAGE, VIDEO, or GIF based on metadata and URL attributes."""
    # Check if item is video
    is_video = False
    if hasattr(item, "is_video") and getattr(item, "is_video"):
        is_video = True
    elif hasattr(item, "type") and getattr(item, "type") == "video":
        is_video = True
    elif hasattr(item, "video_url") and getattr(item, "video_url"):
        is_video = True
    elif hasattr(item, "streams") and getattr(item, "streams"):
        is_video = True

    if is_video:
        return MediaType.VIDEO

    # Extract URL string
    url_str = ""
    if hasattr(item, "src") and getattr(item, "src"):
        url_str = str(getattr(item, "src"))
    elif hasattr(item, "url") and getattr(item, "url"):
        url_str = str(getattr(item, "url"))

    # Check for GIF extension (case-insensitive)
    parsed_path = urlparse(url_str).path.lower()
    if parsed_path.endswith(".gif"):
        return MediaType.GIF

    return MediaType.IMAGE


def get_media_identifier(item: Any) -> str:
    """Extract stable identifier (pin ID or normalized source URL) for deduplication."""
    if hasattr(item, "id") and getattr(item, "id"):
        return str(getattr(item, "id"))
    if hasattr(item, "pin_id") and getattr(item, "pin_id"):
        return str(getattr(item, "pin_id"))

    # Fallback to normalized source URL
    url_str = ""
    if hasattr(item, "src") and getattr(item, "src"):
        url_str = str(getattr(item, "src"))
    elif hasattr(item, "url") and getattr(item, "url"):
        url_str = str(getattr(item, "url"))

    parsed = urlparse(url_str)
    return f"{parsed.netloc}{parsed.path}"


def select_media_items(
    items: List[Any],
    requested_images: int,
    requested_videos: int,
    requested_gifs: int,
) -> Tuple[List[Any], Dict[str, MediaCountSummary]]:
    """Deduplicate, classify, and select media items up to per-type requested limits."""
    selected_items: List[Any] = []

    counts = {
        MediaType.IMAGE.value: MediaCountSummary(requested=requested_images),
        MediaType.VIDEO.value: MediaCountSummary(requested=requested_videos),
        MediaType.GIF.value: MediaCountSummary(requested=requested_gifs),
    }

    seen_ids = set()

    for item in items:
        media_id = get_media_identifier(item)
        mtype = classify_media(item).value
        count_summary = counts[mtype]

        if media_id in seen_ids:
            count_summary.skipped += 1
            continue

        seen_ids.add(media_id)
        count_summary.found += 1

        if count_summary.selected < count_summary.requested:
            count_summary.selected += 1
            selected_items.append(item)
        else:
            count_summary.skipped += 1

    return selected_items, counts
