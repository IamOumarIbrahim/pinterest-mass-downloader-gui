"""Comprehensive unit tests for the command-line interface."""

import json

from pinterest_mass_downloader.cli import main
from tests.fakes import FakePinterestAdapter, MockPinterestMedia


def test_cli_doctor(capsys):
    exit_code = main(["doctor"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Doctor Report" in captured.out
    assert "app_version" in captured.out


def test_cli_download_dry_run_keyword(tmp_path, capsys):
    out_dir = tmp_path / "dry_run_out"
    exit_code = main(
        [
            "download",
            "--keyword",
            "architecture",
            "--output",
            str(out_dir),
            "--images",
            "2",
            "--dry-run",
        ]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "[DRY-RUN]" in captured.out


def test_cli_download_dry_run_url(tmp_path, capsys):
    out_dir = tmp_path / "dry_run_url"
    exit_code = main(
        [
            "download",
            "--url",
            "https://www.pinterest.com/example/board/",
            "--output",
            str(out_dir),
            "--images",
            "1",
            "--dry-run",
        ]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "[DRY-RUN]" in captured.out


def test_cli_download_validation_failure(tmp_path, capsys):
    # No keyword or url provided
    exit_code = main(["download", "--output", str(tmp_path)])
    assert exit_code == 2

    # Malformed URL
    exit_code = main(["download", "--url", "not-a-url", "--output", str(tmp_path)])
    assert exit_code == 2


def test_cli_download_with_fake_adapter(tmp_path, monkeypatch):
    media = [MockPinterestMedia(id="1", src="https://i.pinimg.com/1.jpg")]
    fake_adapter = FakePinterestAdapter(media_items=media)

    monkeypatch.setattr(
        "pinterest_mass_downloader.cli.PinterestDLAdapter",
        lambda: fake_adapter,
    )

    report_path = tmp_path / "report.json"
    exit_code = main(
        [
            "download",
            "--keyword",
            "nature",
            "--output",
            str(tmp_path),
            "--images",
            "1",
            "--json-report",
            str(report_path),
        ]
    )
    assert exit_code == 0
    assert report_path.exists()
    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_data["status"] == "completed"
