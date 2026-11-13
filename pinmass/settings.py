"""Remembers the user's choices between runs."""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {
    "folder": str(Path.home() / "Downloads" / "Pinterest"),
    "subfolders": True,
    "image": 50, "video": 0, "gif": 0,
    "threads": 8,
    "look": True, "colors": False,
    "color_tolerance": 50, "closeness": 50,
    "smart": True, "describe": "",
    "pick_first": False,
    "skip_owned": True,
    "min_side": 0, "shape": "any",
    "follow_autocheck": True,
    "reference": "",
    "appearance": "System",
    "recent": [],
}


def _path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "PinterestMassDownloader" / "settings.json"


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        data.update(json.loads(_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return data


def save(data: dict) -> None:
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def cookies_path() -> Path:
    return _path().parent / "cookies.json"


def load_cookies() -> dict:
    try:
        data = json.loads(cookies_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cookies(cookies: dict | None) -> None:
    """Remember the Pinterest login (None = forget it)."""
    p = cookies_path()
    try:
        if cookies:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(cookies), encoding="utf-8")
        elif p.exists():
            p.unlink()
    except OSError:
        pass
