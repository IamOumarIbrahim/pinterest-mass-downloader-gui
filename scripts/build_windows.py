"""Script to build standalone Windows executable via PyInstaller."""

import subprocess
import sys
from pathlib import Path


def main():
    print("Building standalone Windows executable with PyInstaller...")

    root_dir = Path(__file__).parent.parent.resolve()
    entry_point = root_dir / "pinterest_downloader.py"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name=pinterest_downloader",
        "--clean",
        str(entry_point),
    ]

    res = subprocess.run(cmd, cwd=root_dir)
    if res.returncode != 0:
        print("PyInstaller build failed!", file=sys.stderr)
        return res.returncode

    print("PyInstaller build complete: dist/pinterest_downloader/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
