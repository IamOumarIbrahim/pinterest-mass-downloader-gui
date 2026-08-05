"""Atomic persistence for app settings and download queue using platformdirs."""

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from platformdirs import PlatformDirs

from pinterest_mass_downloader.domain.enums import JobStatus
from pinterest_mass_downloader.domain.errors import PersistenceError
from pinterest_mass_downloader.domain.models import Job

APP_NAME = "pinterest-mass-downloader"
APP_AUTHOR = "IamOumarIbrahim"
SCHEMA_VERSION = 1

dirs = PlatformDirs(appname=APP_NAME, appauthor=APP_AUTHOR)


def get_config_dir() -> Path:
    config_path = Path(dirs.user_config_dir)
    config_path.mkdir(parents=True, exist_ok=True)
    return config_path


def get_data_dir() -> Path:
    data_path = Path(dirs.user_data_dir)
    data_path.mkdir(parents=True, exist_ok=True)
    return data_path


def atomic_write_json(file_path: Path, data: Any) -> None:
    """Write data to JSON atomically via a temporary file."""
    target_dir = file_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile("w", dir=target_dir, delete=False, encoding="utf-8") as tf:
        temp_name = tf.name
        json.dump(data, tf, indent=2, ensure_ascii=False)

    shutil.move(temp_name, file_path)


class SettingsManager:
    """Manages application settings persistence."""

    def __init__(self, settings_file: Optional[Path] = None):
        self.settings_file = settings_file or (get_config_dir() / "settings.json")

    def load_settings(self) -> Dict[str, Any]:
        """Load settings JSON or return defaults on missing/corrupt file."""
        if not self.settings_file.exists():
            return self._default_settings()

        try:
            with open(self.settings_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Settings JSON must be an object.")
            return data.get("settings", self._default_settings())
        except Exception:
            # Backup corrupt file
            bak_path = self.settings_file.with_suffix(".json.bak")
            try:
                shutil.copy(self.settings_file, bak_path)
            except Exception:
                pass
            return self._default_settings()

    def save_settings(self, settings: Dict[str, Any]) -> None:
        """Save settings dictionary to file."""
        payload = {
            "version": SCHEMA_VERSION,
            "settings": settings,
        }
        atomic_write_json(self.settings_file, payload)

    def _default_settings(self) -> Dict[str, Any]:
        return {
            "default_output_dir": str(Path.home() / "Downloads" / "Pinterest"),
            "default_images": 50,
            "default_videos": 0,
            "default_gifs": 0,
            "default_min_width": 0,
            "default_min_height": 0,
            "default_backend": "api",
            "dark_mode": True,
        }


class QueuePersistence:
    """Manages queue persistence and import/export."""

    def __init__(self, queue_file: Optional[Path] = None):
        self.queue_file = queue_file or (get_data_dir() / "queue.json")

    def load_queue(self) -> List[Job]:
        """Load job queue, restoring interrupted jobs safely."""
        if not self.queue_file.exists():
            return []

        try:
            with open(self.queue_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            raw_jobs = data.get("jobs", [])
            jobs = []
            for jdict in raw_jobs:
                job = Job.from_dict(jdict)
                # Recover interrupted running/cancelling jobs safely
                if job.status in (JobStatus.RUNNING, JobStatus.CANCELLING):
                    job.status = JobStatus.FAILED
                    job.result.status = JobStatus.FAILED
                    job.result.message = "Interrupted by unexpected application shutdown."
                jobs.append(job)
            return jobs
        except Exception:
            bak_path = self.queue_file.with_suffix(".json.bak")
            try:
                shutil.copy(self.queue_file, bak_path)
            except Exception:
                pass
            return []

    def save_queue(self, jobs: List[Job]) -> None:
        """Save current queue jobs to JSON file."""
        payload = {
            "version": SCHEMA_VERSION,
            "jobs": [j.to_dict() for j in jobs],
        }
        atomic_write_json(self.queue_file, payload)

    def export_queue(self, target_file: Path, jobs: List[Job]) -> None:
        """Export queue to custom JSON file without sensitive data."""
        payload = {
            "version": SCHEMA_VERSION,
            "jobs": [j.to_dict() for j in jobs],
        }
        atomic_write_json(target_file, payload)

    def import_queue(self, source_file: Path) -> List[Job]:
        """Import queue from external JSON file."""
        if not source_file.exists():
            raise PersistenceError(f"Import file does not exist: {source_file}")

        try:
            with open(source_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            raw_jobs = data.get("jobs", [])
            jobs = [Job.from_dict(jdict) for jdict in raw_jobs]
            return jobs
        except Exception as e:
            raise PersistenceError(f"Failed to import queue JSON: {e}")
