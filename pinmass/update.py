"""Telling the user when a newer version is out.

The app asks GitHub for the latest release at most once a day and, if it is
newer than this copy, shows a button that opens the download page. Nothing is
downloaded or installed automatically. Set "check_updates": false in
settings.json to switch it off.
"""

from __future__ import annotations

import re
import time
from typing import Optional

REPO = "IamOumarIbrahim/pinterest-mass-downloader-gui"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGE = f"https://github.com/{REPO}/releases/latest"
EVERY = 24 * 3600


def parse(version: str) -> tuple:
    """'v4.1.0' → (4, 1, 0). Anything after the numbers (-beta, +build) is ignored."""
    m = re.match(r"\s*v?(\d+(?:\.\d+)*)", version or "")
    return tuple(int(p) for p in m.group(1).split(".")) if m else ()


def newer(latest: str, current: str) -> bool:
    a, b = parse(latest), parse(current)
    n = max(len(a), len(b))
    return bool(a) and a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def latest(timeout: float = 6) -> Optional[tuple[str, str]]:
    """(version, page to download it from) of the newest release, or None."""
    import requests
    try:
        r = requests.get(API, timeout=(4, timeout), headers={
            "Accept": "application/vnd.github+json", "User-Agent": "pinterest-mass-downloader"})
        if r.status_code != 200:
            return None
        data = r.json()
        tag = data.get("tag_name") or ""
        return (tag.lstrip("v"), data.get("html_url") or PAGE) if parse(tag) else None
    except (requests.RequestException, ValueError):
        return None


def check(cfg: dict, current: str, fetch=latest) -> Optional[tuple[str, str]]:
    """(version, url) if a newer release exists. Looks online at most once a
    day (remembered in *cfg*); otherwise answers from what it saw last time."""
    if not cfg.get("check_updates", True):
        return None
    if time.time() - float(cfg.get("update_checked", 0)) >= EVERY:
        found = fetch()
        cfg["update_checked"] = time.time()
        if found:
            cfg["update_seen"] = list(found)
    seen = cfg.get("update_seen")
    if seen and len(seen) == 2 and newer(seen[0], current):
        return seen[0], seen[1]
    return None
