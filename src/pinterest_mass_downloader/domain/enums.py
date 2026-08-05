"""Domain enums for Pinterest Mass Downloader."""

from enum import Enum


class StrEnum(str, Enum):
    """Base string enum for clean JSON serialization."""

    def __str__(self) -> str:
        return str(self.value)


class InputMode(StrEnum):
    KEYWORD = "keyword"
    URL = "url"


class BackendType(StrEnum):
    API = "api"
    CHROMIUM = "chromium"
    FIREFOX = "firefox"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"


class MediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    GIF = "gif"
