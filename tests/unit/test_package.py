"""Test basic package imports and CLI entrypoints."""

import pytest

import pinterest_mass_downloader
from pinterest_mass_downloader.cli import main
from pinterest_mass_downloader.version import __version__


def test_version_attribute():
    assert __version__ == "2.0.0"
    assert pinterest_mass_downloader.__version__ == "2.0.0"


def test_cli_help(capsys):
    assert main(["--help"]) == 0
    captured = capsys.readouterr()
    assert "Pinterest Mass Downloader v2.0.0 CLI" in captured.out


def test_cli_version(capsys):
    assert main(["--version"]) == 0
    captured = capsys.readouterr()
    assert "2.0.0" in captured.out


def test_cli_no_args(capsys):
    assert main([]) == 0
    captured = capsys.readouterr()
    assert "Launching Pinterest Mass Downloader GUI" in captured.out


def test_cli_doctor(capsys):
    assert main(["doctor"]) == 0
    captured = capsys.readouterr()
    assert "Doctor" in captured.out


def test_cli_gui(capsys):
    assert main(["gui"]) == 0
    captured = capsys.readouterr()
    assert "Launching GUI" in captured.out


def test_cli_download(capsys):
    assert main(["download"]) == 0
    captured = capsys.readouterr()
    assert "Download command" in captured.out


def test_cli_unknown(capsys):
    assert main(["invalid-arg"]) == 2
    captured = capsys.readouterr()
    assert "Unknown argument" in captured.out


def test_main_module_execution(monkeypatch):
    import runpy
    import sys

    monkeypatch.setattr(sys, "argv", ["pmd", "--version"])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("pinterest_mass_downloader", run_name="__main__")
    assert exc_info.value.code == 0
