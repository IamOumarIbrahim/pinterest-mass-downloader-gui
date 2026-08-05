"""Path sanitization, safe directory creation, and system path helpers."""

import hashlib
import re
from pathlib import Path

WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


def sanitize_folder_name(name: str, max_length: int = 100) -> str:
    """Sanitize string for cross-platform directory name safety."""
    if not name or not name.strip():
        name = "download"

    # Replace invalid characters
    clean = re.sub(r'[\\/:*?"<>|]', "_", name)

    # Replace whitespace and control chars with single underscore or space
    clean = re.sub(r"\s+", " ", clean).strip()

    # Strip trailing dots or spaces (illegal on Windows)
    clean = clean.rstrip(". ")

    if not clean:
        clean = "download"

    # Check Windows reserved names
    upper_base = clean.split(".")[0].upper()
    if upper_base in WINDOWS_RESERVED_NAMES:
        clean = f"{clean}_dir"

    # Truncate to max length
    if len(clean) > max_length:
        clean = clean[:max_length].strip(". ")

    return clean


def get_job_output_dir(base_output_dir: str, query: str, job_id: str) -> Path:
    """Generate safe, collision-resistant output directory path for a job."""
    base_path = Path(base_output_dir)
    sanitized_query = sanitize_folder_name(query, max_length=50)

    # Derive short suffix from job_id or hash
    suffix = job_id[:8] if job_id else hashlib.md5(query.encode("utf-8")).hexdigest()[:8]

    folder_name = f"{sanitized_query}_{suffix}"
    job_dir = base_path / folder_name
    return job_dir


def ensure_safe_directory(path: Path) -> Path:
    """Ensure directory exists safely without resolving to a file."""
    if path.exists() and path.is_file():
        raise ValueError(f"Path points to an existing file: {path}")

    path.mkdir(parents=True, exist_ok=True)
    return path
