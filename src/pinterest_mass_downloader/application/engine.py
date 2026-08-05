"""Cancellable execution engine for Pinterest download jobs."""

import threading
from typing import Any, Callable, Dict, List, Optional

from pinterest_mass_downloader.application.events import (
    AppEvent,
    LogEvent,
    MediaCountsEvent,
    ProgressEvent,
    StageChangeEvent,
    TerminalResultEvent,
)
from pinterest_mass_downloader.domain.enums import JobStatus, MediaType
from pinterest_mass_downloader.domain.errors import ValidationError
from pinterest_mass_downloader.domain.models import Job, ResultSummary
from pinterest_mass_downloader.infrastructure.paths import ensure_safe_directory, get_job_output_dir
from pinterest_mass_downloader.services.classifier import get_media_identifier, select_media_items
from pinterest_mass_downloader.services.manifests import ManifestManager
from pinterest_mass_downloader.services.pinterest_adapter import IPinterestAdapter

DEFAULT_BATCH_SIZE = 8


class CancellationToken:
    """Thread-safe cancellation token."""

    def __init__(self):
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()


class DownloadEngine:
    """Engine executing download jobs with cooperative batch cancellation and manifest resume."""

    def __init__(self, adapter: IPinterestAdapter, batch_size: int = DEFAULT_BATCH_SIZE):
        self.adapter = adapter
        self.batch_size = min(max(batch_size, 1), 16)

    def run_job(
        self,
        job: Job,
        cancel_token: Optional[CancellationToken] = None,
        event_cb: Optional[Callable[[AppEvent], None]] = None,
    ) -> ResultSummary:
        """Run a single job sequentially, emitting progress events."""

        def notify(evt: AppEvent) -> None:
            if event_cb:
                event_cb(evt)

        token = cancel_token or CancellationToken()

        # 1. State transition to RUNNING
        job.transition_to(JobStatus.RUNNING)
        job.attempts += 1
        notify(StageChangeEvent(job_id=job.id, stage="validating", message="Validating request"))
        notify(
            LogEvent(level="INFO", message=f"Starting job {job.id} for query '{job.request.query}'")
        )

        # 2. Validation
        try:
            job.request.validate()
        except ValidationError as ve:
            job.transition_to(JobStatus.FAILED)
            job.result.message = str(ve)
            job.result.errors.append(str(ve))
            notify(LogEvent(level="ERROR", message=f"Validation error: {ve}"))
            notify(TerminalResultEvent(job_id=job.id, result=job.result))
            return job.result

        if token.is_cancelled():
            return self._handle_cancellation(job, notify)

        # 3. Output directory & manifest setup
        job_dir = get_job_output_dir(job.request.output_dir, job.request.query, job.id)
        manifest_mgr = ManifestManager(job_dir)
        downloaded_pin_map: Dict[str, str] = {}

        if not job.request.dry_run:
            ensure_safe_directory(job_dir)

        # Dry run execution check
        if job.request.dry_run:
            job.transition_to(JobStatus.COMPLETED)
            job.result.message = (
                f"[DRY-RUN] Validated plan for '{job.request.query}'. Output: {job_dir}"
            )
            notify(LogEvent(level="INFO", message=job.result.message))
            notify(TerminalResultEvent(job_id=job.id, result=job.result))
            return job.result

        # Load existing completed identifiers from manifest for resume
        existing_pin_ids = set()
        if not job.request.overwrite:
            existing_pin_ids = manifest_mgr.get_existing_completed_ids()

        # 4. Scrape / Search
        notify(StageChangeEvent(job_id=job.id, stage="scraping", message="Scraping Pinterest"))
        total_requested = job.request.images + job.request.videos + job.request.gifs
        overfetch_limit = min(total_requested * 3, 250)

        try:
            raw_items = self.adapter.scrape_or_search(
                mode=job.request.mode,
                query_or_url=job.request.query,
                limit=overfetch_limit,
                cookies_path=job.request.cookies_path,
                min_resolution=(job.request.min_width, job.request.min_height),
                backend=job.request.backend,
            )
        except Exception as se:
            job.transition_to(JobStatus.FAILED)
            job.result.message = f"Scrape error: {se}"
            job.result.errors.append(str(se))
            notify(LogEvent(level="ERROR", message=f"Scrape failed: {se}"))
            notify(TerminalResultEvent(job_id=job.id, result=job.result))
            return job.result

        if token.is_cancelled():
            return self._handle_cancellation(job, notify)

        # 5. Classify & Select
        notify(
            StageChangeEvent(job_id=job.id, stage="classifying", message="Classifying media items")
        )
        selected_items, counts = select_media_items(
            items=raw_items,
            requested_images=job.request.images,
            requested_videos=job.request.videos,
            requested_gifs=job.request.gifs,
        )

        # Filter out existing items if resuming
        to_download_items: List[Any] = []
        for item in selected_items:
            pin_id = get_media_identifier(item)
            if pin_id in existing_pin_ids and not job.request.overwrite:
                # Count as existing
                for mtype in (MediaType.IMAGE.value, MediaType.VIDEO.value, MediaType.GIF.value):
                    counts[mtype].existing += 1
            else:
                to_download_items.append(item)

        job.result.counts = counts
        notify(MediaCountsEvent(job_id=job.id, counts=counts))

        if not selected_items:
            job.transition_to(JobStatus.FAILED)
            job.result.message = "No media items matching requirements were found."
            manifest_mgr.save_manifest(job, downloaded_pin_map)
            notify(LogEvent(level="WARNING", message=job.result.message))
            notify(TerminalResultEvent(job_id=job.id, result=job.result))
            return job.result

        if token.is_cancelled():
            manifest_mgr.save_manifest(job, downloaded_pin_map)
            return self._handle_cancellation(job, notify)

        # 6. Download in Batches
        notify(
            StageChangeEvent(job_id=job.id, stage="downloading", message="Downloading media items")
        )
        total_to_download = len(to_download_items)
        downloaded_count = 0
        failed_count = 0

        for i in range(0, total_to_download, self.batch_size):
            if token.is_cancelled():
                manifest_mgr.save_manifest(job, downloaded_pin_map)
                return self._handle_cancellation(job, notify)

            batch = to_download_items[i : i + self.batch_size]

            try:
                paths = self.adapter.download_media_items(
                    media_items=batch,
                    output_dir=job_dir,
                    raw_video=job.request.raw_video,
                )
                for idx, p in enumerate(paths):
                    rel_p = str(p.relative_to(job_dir)) if p.is_relative_to(job_dir) else p.name
                    job.result.downloaded_files.append(rel_p)
                    if idx < len(batch):
                        item_id = get_media_identifier(batch[idx])
                        downloaded_pin_map[item_id] = rel_p

                downloaded_count += len(paths)
                failed_in_batch = len(batch) - len(paths)
                failed_count += failed_in_batch
            except Exception as de:
                failed_count += len(batch)
                job.result.errors.append(f"Batch download failed: {de}")
                notify(LogEvent(level="ERROR", message=f"Batch error: {de}"))

            # Update count summaries
            for mtype in (MediaType.IMAGE.value, MediaType.VIDEO.value, MediaType.GIF.value):
                counts[mtype].downloaded = min(
                    counts[mtype].selected, downloaded_count + counts[mtype].existing
                )
                counts[mtype].failed = max(0, counts[mtype].selected - counts[mtype].downloaded)

            manifest_mgr.save_manifest(job, downloaded_pin_map)
            notify(ProgressEvent(job_id=job.id, current=downloaded_count, total=total_to_download))
            notify(MediaCountsEvent(job_id=job.id, counts=counts))

            if token.is_cancelled():
                manifest_mgr.save_manifest(job, downloaded_pin_map)
                return self._handle_cancellation(job, notify)

        # 7. Finalize status
        if total_to_download > 0 and downloaded_count == 0 and len(existing_pin_ids) == 0:
            job.transition_to(JobStatus.FAILED)
            job.result.message = "Failed to download any media items."
        elif failed_count > 0:
            job.transition_to(JobStatus.PARTIAL)
            job.result.message = (
                f"Partially completed: downloaded {downloaded_count}/{total_to_download} items."
            )
        else:
            job.transition_to(JobStatus.COMPLETED)
            job.result.message = "Successfully downloaded/resumed all media items."

        manifest_mgr.save_manifest(job, downloaded_pin_map)
        notify(LogEvent(level="INFO", message=job.result.message))
        notify(TerminalResultEvent(job_id=job.id, result=job.result))
        return job.result

    def _handle_cancellation(self, job: Job, notify: Callable[[AppEvent], None]) -> ResultSummary:
        job.transition_to(JobStatus.CANCELLING)
        job.transition_to(JobStatus.CANCELLED)
        job.result.message = "Job execution was cancelled by user."
        notify(LogEvent(level="WARNING", message=f"Job {job.id} cancelled."))
        notify(TerminalResultEvent(job_id=job.id, result=job.result))
        return job.result
