"""Integration tests verifying documented CLI commands."""

from pinterest_mass_downloader.cli import main


def test_documented_help_command(capsys):
    assert main(["--help"]) == 0
    out = capsys.readouterr().out
    assert "Pinterest Mass Downloader v2.0.0 CLI" in out


def test_documented_doctor_command(capsys):
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "Doctor Report" in out


def test_documented_dry_run_keyword_command(tmp_path, capsys):
    assert (
        main(
            [
                "download",
                "--keyword",
                "modern architecture",
                "--output",
                str(tmp_path),
                "--images",
                "5",
                "--dry-run",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "[DRY-RUN]" in out


def test_documented_dry_run_url_command(tmp_path, capsys):
    assert (
        main(
            [
                "download",
                "--url",
                "https://www.pinterest.com/example/board/",
                "--output",
                str(tmp_path),
                "--images",
                "10",
                "--dry-run",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "[DRY-RUN]" in out
