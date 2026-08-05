"""Domain models for Pinterest Mass Downloader."""

import datetime
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from pinterest_mass_downloader.domain.enums import BackendType, InputMode, JobStatus, MediaType
from pinterest_mass_downloader.domain.errors import StateTransitionError, ValidationError

# Valid state transitions lookup table
VALID_TRANSITIONS: Dict[JobStatus, List[JobStatus]] = {
    JobStatus.PENDING: [JobStatus.RUNNING],
    JobStatus.RUNNING: [
        JobStatus.COMPLETED,
        JobStatus.PARTIAL,
        JobStatus.FAILED,
        JobStatus.CANCELLING,
    ],
    JobStatus.CANCELLING: [JobStatus.CANCELLED, JobStatus.FAILED],
    JobStatus.COMPLETED: [],
    JobStatus.PARTIAL: [JobStatus.PENDING],
    JobStatus.FAILED: [JobStatus.PENDING],
    JobStatus.CANCELLED: [JobStatus.PENDING],
}


@dataclass
class MediaCountSummary:
    requested: int = 0
    found: int = 0
    selected: int = 0
    skipped: int = 0
    downloaded: int = 0
    failed: int = 0
    existing: int = 0

    def to_dict(self) -> dict:
        return {
            "requested": self.requested,
            "found": self.found,
            "selected": self.selected,
            "skipped": self.skipped,
            "downloaded": self.downloaded,
            "failed": self.failed,
            "existing": self.existing,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MediaCountSummary":
        return cls(
            requested=data.get("requested", 0),
            found=data.get("found", 0),
            selected=data.get("selected", 0),
            skipped=data.get("skipped", 0),
            downloaded=data.get("downloaded", 0),
            failed=data.get("failed", 0),
            existing=data.get("existing", 0),
        )


@dataclass
class ResultSummary:
    status: JobStatus = JobStatus.PENDING
    counts: Dict[str, MediaCountSummary] = field(
        default_factory=lambda: {
            MediaType.IMAGE.value: MediaCountSummary(),
            MediaType.VIDEO.value: MediaCountSummary(),
            MediaType.GIF.value: MediaCountSummary(),
        }
    )
    errors: List[str] = field(default_factory=list)
    downloaded_files: List[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "counts": {k: v.to_dict() for k, v in self.counts.items()},
            "errors": self.errors,
            "downloaded_files": self.downloaded_files,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResultSummary":
        raw_status = data.get("status", JobStatus.PENDING.value)
        status = JobStatus(raw_status) if isinstance(raw_status, str) else raw_status
        counts_data = data.get("counts", {})
        counts = {}
        for mtype in (MediaType.IMAGE.value, MediaType.VIDEO.value, MediaType.GIF.value):
            if mtype in counts_data:
                counts[mtype] = MediaCountSummary.from_dict(counts_data[mtype])
            else:
                counts[mtype] = MediaCountSummary()
        return cls(
            status=status,
            counts=counts,
            errors=data.get("errors", []),
            downloaded_files=data.get("downloaded_files", []),
            message=data.get("message", ""),
        )


@dataclass
class DownloadRequest:
    mode: InputMode
    query: str
    output_dir: str
    images: int = 50
    videos: int = 0
    gifs: int = 0
    min_width: int = 0
    min_height: int = 0
    backend: BackendType = BackendType.API
    cookies_path: Optional[str] = None
    raw_video: bool = False
    overwrite: bool = False
    dry_run: bool = False
    verbose: bool = False

    def validate(self) -> None:
        """Validate input parameters."""
        if not self.query or not self.query.strip():
            raise ValidationError("Query or URL cannot be empty.")

        if self.mode == InputMode.URL:
            q = self.query.strip().lower()
            if not (q.startswith("http://") or q.startswith("https://")):
                raise ValidationError("URL must start with http:// or https://")
            if "pinterest." not in q and "pin.it" not in q:
                raise ValidationError("URL must be a valid Pinterest URL.")

        if self.images < 0 or self.videos < 0 or self.gifs < 0:
            raise ValidationError("Media counts cannot be negative.")

        if self.images == 0 and self.videos == 0 and self.gifs == 0:
            raise ValidationError("At least one media limit must be greater than zero.")

        if self.min_width < 0 or self.min_height < 0:
            raise ValidationError("Minimum resolution dimensions cannot be negative.")

        if self.cookies_path:
            cookie_p = Path(self.cookies_path)
            if not cookie_p.exists() or not cookie_p.is_file():
                raise ValidationError(f"Cookie file not found: {self.cookies_path}")

        if self.output_dir:
            out_p = Path(self.output_dir)
            if out_p.exists() and out_p.is_file():
                raise ValidationError(f"Output directory path points to a file: {self.output_dir}")

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "query": self.query,
            "output_dir": self.output_dir,
            "images": self.images,
            "videos": self.videos,
            "gifs": self.gifs,
            "min_width": self.min_width,
            "min_height": self.min_height,
            "backend": self.backend.value,
            "cookies_path": self.cookies_path,
            "raw_video": self.raw_video,
            "overwrite": self.overwrite,
            "dry_run": self.dry_run,
            "verbose": self.verbose,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DownloadRequest":
        return cls(
            mode=InputMode(data["mode"]),
            query=data["query"],
            output_dir=data["output_dir"],
            images=data.get("images", 50),
            videos=data.get("videos", 0),
            gifs=data.get("gifs", 0),
            min_width=data.get("min_width", 0),
            min_height=data.get("min_height", 0),
            backend=BackendType(data.get("backend", BackendType.API.value)),
            cookies_path=data.get("cookies_path"),
            raw_video=data.get("raw_video", False),
            overwrite=data.get("overwrite", False),
            dry_run=data.get("dry_run", False),
            verbose=data.get("verbose", False),
        )


@dataclass
class Job:
    request: DownloadRequest
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: JobStatus = JobStatus.PENDING
    created_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    attempts: int = 0
    result: ResultSummary = field(default_factory=ResultSummary)

    def transition_to(self, target_status: JobStatus) -> None:
        """Enforce strict status transitions."""
        if target_status not in VALID_TRANSITIONS.get(self.status, []):
            raise StateTransitionError(
                f"Invalid status transition from {self.status.value} to {target_status.value}"
            )
        self.status = target_status
        self.result.status = target_status

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "request": self.request.to_dict(),
            "status": self.status.value,
            "created_at": self.created_at,
            "attempts": self.attempts,
            "result": self.result.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        job = cls(
            id=data.get("id", str(uuid.uuid4())),
            request=DownloadRequest.from_dict(data["request"]),
            status=JobStatus(data.get("status", JobStatus.PENDING.value)),
            created_at=data.get(
                "created_at", datetime.datetime.now(datetime.timezone.utc).isoformat()
            ),
            attempts=data.get("attempts", 0),
            result=ResultSummary.from_dict(data.get("result", {})),
        )
        return job
