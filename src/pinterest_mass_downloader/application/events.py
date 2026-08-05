"""Typed event definitions for execution progress, status changes, and logging."""

import datetime
from dataclasses import dataclass, field
from typing import Dict

from pinterest_mass_downloader.domain.models import MediaCountSummary, ResultSummary


@dataclass
class AppEvent:
    timestamp: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


@dataclass
class LogEvent(AppEvent):
    level: str = "INFO"  # INFO, WARNING, ERROR, DEBUG
    message: str = ""


@dataclass
class StageChangeEvent(AppEvent):
    job_id: str = ""
    stage: str = ""  # e.g., "validating", "scraping", "classifying", "downloading", "finalizing"
    message: str = ""


@dataclass
class ProgressEvent(AppEvent):
    job_id: str = ""
    current: int = 0
    total: int = 0

    @property
    def percentage(self) -> float:
        return (self.current / self.total * 100.0) if self.total > 0 else 0.0


@dataclass
class MediaCountsEvent(AppEvent):
    job_id: str = ""
    counts: Dict[str, MediaCountSummary] = field(default_factory=dict)


@dataclass
class ItemFailureEvent(AppEvent):
    job_id: str = ""
    item_id: str = ""
    error: str = ""


@dataclass
class TerminalResultEvent(AppEvent):
    job_id: str = ""
    result: ResultSummary = field(default_factory=ResultSummary)
