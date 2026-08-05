"""Deterministic unit tests for engine and queue manager."""

from pinterest_mass_downloader.application.engine import CancellationToken, DownloadEngine
from pinterest_mass_downloader.application.queue_manager import QueueManager
from pinterest_mass_downloader.domain.enums import InputMode, JobStatus
from pinterest_mass_downloader.domain.models import DownloadRequest, Job
from pinterest_mass_downloader.services.persistence import QueuePersistence
from tests.fakes import FakePinterestAdapter, MockPinterestMedia


def test_successful_complete_job(tmp_path):
    media = [
        MockPinterestMedia(id="1", src="https://i.pinimg.com/1.jpg"),
        MockPinterestMedia(id="2", src="https://i.pinimg.com/2.jpg"),
    ]
    adapter = FakePinterestAdapter(media_items=media)
    engine = DownloadEngine(adapter=adapter, batch_size=2)

    req = DownloadRequest(mode=InputMode.KEYWORD, query="cars", output_dir=str(tmp_path), images=2)
    job = Job(request=req)

    events = []
    result = engine.run_job(job, event_cb=events.append)

    assert result.status == JobStatus.COMPLETED
    assert job.status == JobStatus.COMPLETED
    assert len(result.downloaded_files) == 2


def test_no_media_found_becomes_failed(tmp_path):
    adapter = FakePinterestAdapter(media_items=[])
    engine = DownloadEngine(adapter=adapter)

    req = DownloadRequest(mode=InputMode.KEYWORD, query="empty", output_dir=str(tmp_path), images=5)
    job = Job(request=req)

    result = engine.run_job(job)
    assert result.status == JobStatus.FAILED
    assert job.status == JobStatus.FAILED
    assert "No media items matching requirements" in result.message


def test_unexpected_adapter_exception(tmp_path):
    adapter = FakePinterestAdapter(raise_error=True)
    engine = DownloadEngine(adapter=adapter)

    req = DownloadRequest(mode=InputMode.KEYWORD, query="error", output_dir=str(tmp_path), images=5)
    job = Job(request=req)

    result = engine.run_job(job)
    assert result.status == JobStatus.FAILED
    assert "Scrape error" in result.message


def test_cancellation_before_scrape(tmp_path):
    media = [MockPinterestMedia(id="1", src="https://i.pinimg.com/1.jpg")]
    adapter = FakePinterestAdapter(media_items=media)
    engine = DownloadEngine(adapter=adapter)

    req = DownloadRequest(
        mode=InputMode.KEYWORD, query="cancel", output_dir=str(tmp_path), images=1
    )
    job = Job(request=req)
    token = CancellationToken()
    token.cancel()

    result = engine.run_job(job, cancel_token=token)
    assert result.status == JobStatus.CANCELLED
    assert job.status == JobStatus.CANCELLED


def test_queue_manager_add_and_start(tmp_path):
    media = [MockPinterestMedia(id="1", src="https://i.pinimg.com/1.jpg")]
    adapter = FakePinterestAdapter(media_items=media)
    q_file = tmp_path / "queue.json"
    persistence = QueuePersistence(queue_file=q_file)

    qm = QueueManager(adapter=adapter, persistence=persistence)
    req = DownloadRequest(mode=InputMode.KEYWORD, query="queue", output_dir=str(tmp_path), images=1)
    job = qm.add_job(req)
    assert job.status == JobStatus.PENDING

    started = qm.start_queue()
    assert started is True

    # Wait for thread to finish
    if qm._worker_thread:
        qm._worker_thread.join(timeout=3.0)

    assert job.status == JobStatus.COMPLETED


def test_queue_manager_rejected_start_when_running(tmp_path):
    adapter = FakePinterestAdapter()
    persistence = QueuePersistence(queue_file=tmp_path / "queue.json")
    qm = QueueManager(adapter=adapter, persistence=persistence)

    req = DownloadRequest(mode=InputMode.KEYWORD, query="test", output_dir=str(tmp_path), images=1)
    qm.add_job(req)
    qm.start_queue()

    # Second start while active should return False
    assert qm.start_queue() is False

    if qm._worker_thread:
        qm._worker_thread.join(timeout=3.0)


def test_queue_manager_retry_and_clear(tmp_path):
    adapter = FakePinterestAdapter()
    persistence = QueuePersistence(queue_file=tmp_path / "queue.json")
    qm = QueueManager(adapter=adapter, persistence=persistence)

    req = DownloadRequest(mode=InputMode.KEYWORD, query="test", output_dir=str(tmp_path), images=1)
    job = qm.add_job(req)
    job.status = JobStatus.FAILED

    assert qm.retry_job(job.id) is True
    assert job.status == JobStatus.PENDING

    job.status = JobStatus.COMPLETED
    qm.clear_completed()
    assert len(qm.jobs) == 0
