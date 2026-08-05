"""Comprehensive unit tests for domain models, validation, state machine, and path sanitization."""

import pytest

from pinterest_mass_downloader.domain.enums import BackendType, InputMode, JobStatus
from pinterest_mass_downloader.domain.errors import StateTransitionError, ValidationError
from pinterest_mass_downloader.domain.models import (
    DownloadRequest,
    Job,
    MediaCountSummary,
    ResultSummary,
)
from pinterest_mass_downloader.infrastructure.paths import (
    ensure_safe_directory,
    get_job_output_dir,
    sanitize_folder_name,
)


def test_valid_keyword_request(tmp_path):
    req = DownloadRequest(
        mode=InputMode.KEYWORD,
        query="modern architecture",
        output_dir=str(tmp_path),
        images=10,
    )
    req.validate()
    assert req.query == "modern architecture"


def test_valid_url_request(tmp_path):
    req = DownloadRequest(
        mode=InputMode.URL,
        query="https://www.pinterest.com/pin/123456789/",
        output_dir=str(tmp_path),
        images=5,
    )
    req.validate()


def test_malformed_url_requests(tmp_path):
    with pytest.raises(ValidationError, match="URL must start with"):
        req = DownloadRequest(
            mode=InputMode.URL,
            query="www.pinterest.com/board/",
            output_dir=str(tmp_path),
        )
        req.validate()

    with pytest.raises(ValidationError, match="valid Pinterest URL"):
        req = DownloadRequest(
            mode=InputMode.URL,
            query="https://google.com/search",
            output_dir=str(tmp_path),
        )
        req.validate()


def test_all_counts_zero(tmp_path):
    with pytest.raises(ValidationError, match="greater than zero"):
        req = DownloadRequest(
            mode=InputMode.KEYWORD,
            query="cats",
            output_dir=str(tmp_path),
            images=0,
            videos=0,
            gifs=0,
        )
        req.validate()


def test_negative_counts(tmp_path):
    with pytest.raises(ValidationError, match="cannot be negative"):
        req = DownloadRequest(
            mode=InputMode.KEYWORD,
            query="cats",
            output_dir=str(tmp_path),
            images=-1,
        )
        req.validate()


def test_negative_resolution(tmp_path):
    with pytest.raises(ValidationError, match="resolution"):
        req = DownloadRequest(
            mode=InputMode.KEYWORD,
            query="cats",
            output_dir=str(tmp_path),
            min_width=-100,
        )
        req.validate()


def test_missing_cookie_file(tmp_path):
    fake_cookie = tmp_path / "nonexistent_cookies.json"
    with pytest.raises(ValidationError, match="Cookie file not found"):
        req = DownloadRequest(
            mode=InputMode.KEYWORD,
            query="cats",
            output_dir=str(tmp_path),
            cookies_path=str(fake_cookie),
        )
        req.validate()


def test_output_path_is_file(tmp_path):
    file_path = tmp_path / "somefile.txt"
    file_path.write_text("hello")
    with pytest.raises(ValidationError, match="points to a file"):
        req = DownloadRequest(
            mode=InputMode.KEYWORD,
            query="cats",
            output_dir=str(file_path),
        )
        req.validate()


def test_path_sanitization():
    assert sanitize_folder_name("CON") == "CON_dir"
    assert sanitize_folder_name("PRN.") == "PRN_dir"
    assert sanitize_folder_name("NUL  ") == "NUL_dir"
    assert sanitize_folder_name("COM1") == "COM1_dir"
    assert sanitize_folder_name("hello: world? *test*") == "hello_ world_ _test_"
    assert sanitize_folder_name("trailing dot...") == "trailing dot"
    assert sanitize_folder_name("") == "download"
    assert sanitize_folder_name("   ") == "download"
    assert sanitize_folder_name("a" * 150) == "a" * 100


def test_job_output_dir_collision_suffix(tmp_path):
    dir1 = get_job_output_dir(str(tmp_path), "test query", "job-uuid-12345678")
    assert "test query_job-uuid" in dir1.name


def test_ensure_safe_directory(tmp_path):
    d = ensure_safe_directory(tmp_path / "subdir")
    assert d.exists() and d.is_dir()

    file_path = tmp_path / "dummy.txt"
    file_path.write_text("content")
    with pytest.raises(ValueError, match="existing file"):
        ensure_safe_directory(file_path)


def test_models_serialization(tmp_path):
    req = DownloadRequest(
        mode=InputMode.KEYWORD,
        query="cats",
        output_dir=str(tmp_path),
        backend=BackendType.API,
    )
    d = req.to_dict()
    reconstructed_req = DownloadRequest.from_dict(d)
    assert reconstructed_req.query == req.query

    count_summary = MediaCountSummary(requested=10, downloaded=8)
    cs_dict = count_summary.to_dict()
    assert MediaCountSummary.from_dict(cs_dict).downloaded == 8

    res = ResultSummary(status=JobStatus.COMPLETED, message="Done")
    res_dict = res.to_dict()
    assert ResultSummary.from_dict(res_dict).message == "Done"

    job = Job(request=req)
    job_dict = job.to_dict()
    reconstructed_job = Job.from_dict(job_dict)
    assert reconstructed_job.id == job.id
    assert reconstructed_job.request.query == "cats"


def test_job_state_machine_valid_transitions():
    req = DownloadRequest(mode=InputMode.KEYWORD, query="cars", output_dir="/tmp")
    job = Job(request=req)
    assert job.status == JobStatus.PENDING

    job.transition_to(JobStatus.RUNNING)
    assert job.status == JobStatus.RUNNING

    job.transition_to(JobStatus.COMPLETED)
    assert job.status == JobStatus.COMPLETED


def test_job_state_machine_cancellation():
    req = DownloadRequest(mode=InputMode.KEYWORD, query="cars", output_dir="/tmp")
    job = Job(request=req)
    job.transition_to(JobStatus.RUNNING)
    job.transition_to(JobStatus.CANCELLING)
    job.transition_to(JobStatus.CANCELLED)
    assert job.status == JobStatus.CANCELLED

    # Retry cancelled job
    job.transition_to(JobStatus.PENDING)
    assert job.status == JobStatus.PENDING


def test_job_state_machine_invalid_transitions():
    req = DownloadRequest(mode=InputMode.KEYWORD, query="cars", output_dir="/tmp")
    job = Job(request=req)

    # Cannot go directly from PENDING to COMPLETED
    with pytest.raises(StateTransitionError, match="Invalid status transition"):
        job.transition_to(JobStatus.COMPLETED)

    job.transition_to(JobStatus.RUNNING)
    job.transition_to(JobStatus.FAILED)

    # Cannot go from FAILED directly to RUNNING without PENDING
    with pytest.raises(StateTransitionError):
        job.transition_to(JobStatus.RUNNING)
