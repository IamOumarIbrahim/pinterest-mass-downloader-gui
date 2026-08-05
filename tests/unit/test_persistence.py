"""Unit tests for settings and queue persistence."""

import json
import pytest

from pinterest_mass_downloader.domain.enums import InputMode, JobStatus
from pinterest_mass_downloader.domain.errors import PersistenceError
from pinterest_mass_downloader.domain.models import DownloadRequest, Job
from pinterest_mass_downloader.services.persistence import (
    QueuePersistence,
    SettingsManager,
    atomic_write_json,
    get_config_dir,
    get_data_dir,
)


def test_platform_dirs_exist():
    assert get_config_dir().exists()
    assert get_data_dir().exists()


def test_atomic_write_json(tmp_path):
    file_p = tmp_path / "test.json"
    data = {"key": "value"}
    atomic_write_json(file_p, data)
    assert file_p.exists()
    assert json.loads(file_p.read_text(encoding="utf-8")) == data


def test_settings_save_and_load(tmp_path):
    set_file = tmp_path / "settings.json"
    mgr = SettingsManager(settings_file=set_file)
    defaults = mgr.load_settings()
    assert defaults["default_images"] == 50

    defaults["default_images"] = 100
    mgr.save_settings(defaults)

    loaded = mgr.load_settings()
    assert loaded["default_images"] == 100


def test_settings_corrupt_recovery(tmp_path):
    set_file = tmp_path / "settings.json"
    set_file.write_text("NOT VALID JSON!!!", encoding="utf-8")
    mgr = SettingsManager(settings_file=set_file)

    loaded = mgr.load_settings()
    assert loaded["default_images"] == 50
    assert (tmp_path / "settings.json.bak").exists()


def test_queue_save_and_load(tmp_path):
    q_file = tmp_path / "queue.json"
    q = QueuePersistence(queue_file=q_file)

    req = DownloadRequest(mode=InputMode.KEYWORD, query="nature", output_dir=str(tmp_path))
    job1 = Job(request=req)
    q.save_queue([job1])

    loaded = q.load_queue()
    assert len(loaded) == 1
    assert loaded[0].id == job1.id
    assert loaded[0].request.query == "nature"


def test_queue_import_export(tmp_path):
    q_file = tmp_path / "queue.json"
    export_file = tmp_path / "exported.json"
    q = QueuePersistence(queue_file=q_file)

    req = DownloadRequest(mode=InputMode.KEYWORD, query="nature", output_dir=str(tmp_path))
    job = Job(request=req)
    q.export_queue(export_file, [job])

    assert export_file.exists()

    imported_jobs = q.import_queue(export_file)
    assert len(imported_jobs) == 1
    assert imported_jobs[0].request.query == "nature"


def test_queue_import_nonexistent_file(tmp_path):
    q = QueuePersistence()
    with pytest.raises(PersistenceError, match="does not exist"):
        q.import_queue(tmp_path / "missing.json")


def test_queue_interrupted_job_recovery(tmp_path):
    q_file = tmp_path / "queue.json"
    q = QueuePersistence(queue_file=q_file)

    req = DownloadRequest(mode=InputMode.KEYWORD, query="nature", output_dir=str(tmp_path))
    job = Job(request=req)
    job.transition_to(JobStatus.RUNNING)

    q.save_queue([job])

    # Reloading interrupted queue must mark job FAILED, not RUNNING
    reloaded = q.load_queue()
    assert reloaded[0].status == JobStatus.FAILED
    assert "Interrupted" in reloaded[0].result.message


def test_queue_absence_of_cookie_content(tmp_path):
    q_file = tmp_path / "queue.json"
    q = QueuePersistence(queue_file=q_file)

    cookie_p = tmp_path / "my_cookies.json"
    cookie_p.write_text('{"secret": "session_token_123"}', encoding="utf-8")

    req = DownloadRequest(
        mode=InputMode.KEYWORD,
        query="nature",
        output_dir=str(tmp_path),
        cookies_path=str(cookie_p),
    )
    job = Job(request=req)
    q.save_queue([job])

    content = q_file.read_text(encoding="utf-8")
    assert "session_token_123" not in content
    data = json.loads(content)
    saved_path = data["jobs"][0]["request"]["cookies_path"]
    assert Path(saved_path) == cookie_p
