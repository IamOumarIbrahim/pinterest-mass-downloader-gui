"""Queue manager supervising job lifecycle, threads, and persistence."""

import threading
from typing import Callable, List, Optional

from pinterest_mass_downloader.application.engine import CancellationToken, DownloadEngine
from pinterest_mass_downloader.application.events import AppEvent, LogEvent
from pinterest_mass_downloader.domain.enums import JobStatus
from pinterest_mass_downloader.domain.models import DownloadRequest, Job
from pinterest_mass_downloader.services.persistence import QueuePersistence
from pinterest_mass_downloader.services.pinterest_adapter import IPinterestAdapter


class QueueManager:
    """Manages the download queue, worker thread, and persistence."""

    def __init__(self, adapter: IPinterestAdapter, persistence: Optional[QueuePersistence] = None):
        self.adapter = adapter
        self.persistence = persistence or QueuePersistence()
        self.engine = DownloadEngine(adapter=self.adapter)

        self.jobs: List[Job] = self.persistence.load_queue()
        self.subscribers: List[Callable[[AppEvent], None]] = []

        self._worker_thread: Optional[threading.Thread] = None
        self._current_cancel_token: Optional[CancellationToken] = None
        self._lock = threading.Lock()

    def subscribe(self, callback: Callable[[AppEvent], None]) -> None:
        """Register event listener callback."""
        if callback not in self.subscribers:
            self.subscribers.append(callback)

    def notify(self, event: AppEvent) -> None:
        """Broadcast event to all subscribers."""
        for cb in self.subscribers:
            try:
                cb(event)
            except Exception:
                pass

    def add_job(self, request: DownloadRequest) -> Job:
        """Create and append a new job to the queue."""
        job = Job(request=request)
        with self._lock:
            self.jobs.append(job)
            self._save_state()
        self.notify(LogEvent(level="INFO", message=f"Added job {job.id} to queue."))
        return job

    def remove_job(self, job_id: str) -> bool:
        """Remove job from queue if not currently running."""
        with self._lock:
            for i, job in enumerate(self.jobs):
                if job.id == job_id:
                    if job.status in (JobStatus.RUNNING, JobStatus.CANCELLING):
                        return False
                    del self.jobs[i]
                    self._save_state()
                    return True
        return False

    def retry_job(self, job_id: str) -> bool:
        """Reset failed/cancelled/partial job to PENDING."""
        with self._lock:
            for job in self.jobs:
                if job.id == job_id:
                    if job.status in (JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.PARTIAL):
                        job.transition_to(JobStatus.PENDING)
                        self._save_state()
                        return True
        return False

    def clear_completed(self) -> None:
        """Clear completed jobs from queue."""
        with self._lock:
            self.jobs = [j for j in self.jobs if j.status != JobStatus.COMPLETED]
            self._save_state()

    def is_running(self) -> bool:
        """Check if worker thread is active."""
        return self._worker_thread is not None and self._worker_thread.is_alive()

    def start_queue(self) -> bool:
        """Start queue worker thread if not already running."""
        with self._lock:
            if self.is_running():
                return False

            self._current_cancel_token = CancellationToken()
            self._worker_thread = threading.Thread(target=self._run_loop, name="PMDWorkerThread")
            self._worker_thread.daemon = False
            self._worker_thread.start()
            return True

    def stop_queue(self) -> None:
        """Request cancellation of currently running job and queue worker."""
        with self._lock:
            if self._current_cancel_token:
                self._current_cancel_token.cancel()

    def _run_loop(self) -> None:
        """Sequential queue execution loop running in background thread."""
        while True:
            job_to_run: Optional[Job] = None
            with self._lock:
                if self._current_cancel_token and self._current_cancel_token.is_cancelled():
                    break
                # Pick first pending job
                for job in self.jobs:
                    if job.status == JobStatus.PENDING:
                        job_to_run = job
                        break

            if not job_to_run:
                break

            # Execute job
            self.engine.run_job(
                job=job_to_run,
                cancel_token=self._current_cancel_token,
                event_cb=self.notify,
            )

            with self._lock:
                self._save_state()

    def _save_state(self) -> None:
        """Save current queue state."""
        try:
            self.persistence.save_queue(self.jobs)
        except Exception:
            pass
