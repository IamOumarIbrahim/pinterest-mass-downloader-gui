"""Job output manifest management for duplicate protection and resume."""

import datetime
import json
from pathlib import Path
from typing import Any, Dict, Optional

from pinterest_mass_downloader.domain.models import Job
from pinterest_mass_downloader.services.persistence import atomic_write_json
from pinterest_mass_downloader.version import __version__

MANIFEST_FILENAME = "pmd-manifest.json"
MANIFEST_VERSION = "2.0.0"


class ManifestManager:
    """Manages creation, reading, atomic updates, and resume checks for pmd-manifest.json."""

    def __init__(self, job_dir: Path):
        self.job_dir = Path(job_dir)
        self.manifest_path = self.job_dir / MANIFEST_FILENAME

    def load_manifest(self) -> Optional[Dict[str, Any]]:
        """Load manifest if present and valid; back up corrupt manifest."""
        if not self.manifest_path.exists():
            return None

        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Manifest root must be an object.")
            return data
        except Exception:
            bak_path = self.manifest_path.with_suffix(".json.bak")
            try:
                self.manifest_path.rename(bak_path)
            except Exception:
                pass
            return None

    def get_existing_completed_ids(self, manifest: Optional[Dict[str, Any]] = None) -> set:
        """Return set of pin IDs / identifiers whose downloaded files exist on disk."""
        if manifest is None:
            manifest = self.load_manifest()

        if not manifest:
            return set()

        existing_ids = set()
        recorded_pins = manifest.get("pin_ids", {})

        for pin_id, rel_path in recorded_pins.items():
            full_path = self.job_dir / rel_path
            if full_path.exists() and full_path.is_file() and full_path.stat().st_size > 0:
                existing_ids.add(pin_id)

        return existing_ids

    def save_manifest(
        self,
        job: Job,
        downloaded_pin_map: Dict[str, str],  # pin_id -> relative file path
    ) -> None:
        """Save or update job manifest atomically without secrets."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        existing = self.load_manifest() or {}

        # Merge pin_ids
        merged_pins = existing.get("pin_ids", {})
        merged_pins.update(downloaded_pin_map)

        # Ensure no cookies or secrets are stored in request settings
        clean_request = job.request.to_dict()
        clean_request.pop("cookies_path", None)

        payload = {
            "app_version": __version__,
            "manifest_version": MANIFEST_VERSION,
            "job_id": job.id,
            "source_mode": job.request.mode.value,
            "query_or_url": job.request.query,
            "created_at": existing.get("created_at", job.created_at),
            "updated_at": now_iso,
            "request_settings": clean_request,
            "status": job.status.value,
            "counts": {k: v.to_dict() for k, v in job.result.counts.items()},
            "downloaded_files": job.result.downloaded_files,
            "pin_ids": merged_pins,
            "errors": job.result.errors,
            "message": job.result.message,
        }

        atomic_write_json(self.manifest_path, payload)
