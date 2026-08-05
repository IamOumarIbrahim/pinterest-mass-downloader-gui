"""Unit tests for ManifestManager and job resume behavior."""

from pinterest_mass_downloader.domain.enums import InputMode, JobStatus
from pinterest_mass_downloader.domain.models import DownloadRequest, Job
from pinterest_mass_downloader.services.manifests import MANIFEST_FILENAME, ManifestManager


def test_manifest_creation_and_reading(tmp_path):
    mgr = ManifestManager(tmp_path)
    assert mgr.load_manifest() is None

    req = DownloadRequest(mode=InputMode.KEYWORD, query="architecture", output_dir=str(tmp_path))
    job = Job(request=req)
    job.status = JobStatus.COMPLETED

    mgr.save_manifest(job, downloaded_pin_map={"pin1": "pin1.jpg"})

    manifest = mgr.load_manifest()
    assert manifest is not None
    assert manifest["app_version"] == "2.0.0"
    assert manifest["job_id"] == job.id
    assert manifest["pin_ids"] == {"pin1": "pin1.jpg"}


def test_manifest_resume_skips_existing_files(tmp_path):
    mgr = ManifestManager(tmp_path)
    file_p = tmp_path / "pin1.jpg"
    file_p.write_bytes(b"content")

    req = DownloadRequest(mode=InputMode.KEYWORD, query="architecture", output_dir=str(tmp_path))
    job = Job(request=req)
    mgr.save_manifest(job, downloaded_pin_map={"pin1": "pin1.jpg"})

    existing = mgr.get_existing_completed_ids()
    assert "pin1" in existing


def test_manifest_missing_file_re_downloaded(tmp_path):
    mgr = ManifestManager(tmp_path)
    req = DownloadRequest(mode=InputMode.KEYWORD, query="architecture", output_dir=str(tmp_path))
    job = Job(request=req)
    mgr.save_manifest(job, downloaded_pin_map={"pin1": "pin1.jpg"})

    # File pin1.jpg was recorded but does NOT exist on disk
    existing = mgr.get_existing_completed_ids()
    assert "pin1" not in existing


def test_manifest_corrupt_recovery(tmp_path):
    manifest_p = tmp_path / MANIFEST_FILENAME
    manifest_p.write_text("INVALID JSON", encoding="utf-8")

    mgr = ManifestManager(tmp_path)
    assert mgr.load_manifest() is None
    assert (tmp_path / f"{MANIFEST_FILENAME}.bak").exists()


def test_manifest_secrets_absent(tmp_path):
    cookie_p = tmp_path / "cookies.json"
    cookie_p.write_text('{"secret_token": "abc123secret"}', encoding="utf-8")

    req = DownloadRequest(
        mode=InputMode.KEYWORD,
        query="architecture",
        output_dir=str(tmp_path),
        cookies_path=str(cookie_p),
    )
    job = Job(request=req)
    mgr = ManifestManager(tmp_path)
    mgr.save_manifest(job, downloaded_pin_map={"pin1": "pin1.jpg"})

    content = (tmp_path / MANIFEST_FILENAME).read_text(encoding="utf-8")
    assert "abc123secret" not in content
    assert "cookies_path" not in content
