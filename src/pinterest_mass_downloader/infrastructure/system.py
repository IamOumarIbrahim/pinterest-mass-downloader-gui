"""Cross-platform system operations (opening file explorer folders)."""

import os
import platform
import subprocess
from pathlib import Path


def open_folder(path: Path) -> None:
    """Open folder in OS default file manager cross-platform."""
    target_path = Path(path).resolve()
    if not target_path.exists():
        target_path.mkdir(parents=True, exist_ok=True)

    system_name = platform.system()
    if system_name == "Windows":
        os.startfile(target_path)
    elif system_name == "Darwin":  # macOS
        subprocess.run(["open", str(target_path)], check=False)
    else:  # Linux / Unix
        subprocess.run(["xdg-open", str(target_path)], check=False)
