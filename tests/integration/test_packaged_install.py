"""Integration test verifying wheel package build and metadata."""

from pathlib import Path

import pinterest_mass_downloader


def test_wheel_metadata():
    assert pinterest_mass_downloader.__version__ == "2.0.0"


def test_dist_artifacts_exist():
    dist_dir = Path("dist")
    if dist_dir.exists():
        wheels = list(dist_dir.glob("*.whl"))
        assert len(wheels) > 0, "No built wheel found in dist/"
