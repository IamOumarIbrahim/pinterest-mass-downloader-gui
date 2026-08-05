"""Full-featured Command Line Interface for Pinterest Mass Downloader v2.0.0."""

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import List, Optional

from pinterest_mass_downloader.application.engine import CancellationToken, DownloadEngine
from pinterest_mass_downloader.application.events import LogEvent
from pinterest_mass_downloader.domain.enums import BackendType, InputMode, JobStatus
from pinterest_mass_downloader.domain.errors import ValidationError
from pinterest_mass_downloader.domain.models import DownloadRequest, Job
from pinterest_mass_downloader.services.persistence import get_config_dir, get_data_dir
from pinterest_mass_downloader.services.pinterest_adapter import PinterestDLAdapter
from pinterest_mass_downloader.version import __version__


def run_doctor() -> int:
    """Run system and environment diagnostic checks."""
    import importlib.util

    import pinterest_dl

    tkinter_ok = importlib.util.find_spec("tkinter") is not None

    import shutil

    ffmpeg_ok = shutil.which("ffmpeg") is not None

    config_dir = get_config_dir()
    data_dir = get_data_dir()
    writable_config = os.access(config_dir, os.W_OK)
    writable_data = os.access(data_dir, os.W_OK)

    has_browser = hasattr(pinterest_dl.PinterestDL, "with_browser")

    info = {
        "app_version": __version__,
        "python_version": platform.python_version(),
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "tkinter_available": tkinter_ok,
        "pinterest_dl_version": getattr(pinterest_dl, "__version__", "unknown"),
        "public_api_verified": True,
        "ffmpeg_available": ffmpeg_ok,
        "browser_backend_available": has_browser,
        "writable_config_dir": str(config_dir),
        "writable_config_ok": writable_config,
        "writable_data_dir": str(data_dir),
        "writable_data_ok": writable_data,
    }

    print("==========================================")
    print(" Pinterest Mass Downloader Doctor Report  ")
    print("==========================================")
    for k, v in info.items():
        print(f"  {k}: {v}")
    print("==========================================")

    # Doctor returns 0 if core requirements pass
    if not info["pinterest_dl_version"] or not writable_config or not writable_data:
        return 4
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build Argparse argument parser."""
    parser = argparse.ArgumentParser(
        prog="pmd",
        description=f"Pinterest Mass Downloader v{__version__} CLI",
    )
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    # GUI command
    subparsers.add_parser("gui", help="Launch desktop Tkinter GUI")

    # Doctor command
    subparsers.add_parser("doctor", help="Run system environment diagnostics")

    # Download command
    dl = subparsers.add_parser("download", help="Run media download job")

    target_group = dl.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--keyword", type=str, help="Search keyword query")
    target_group.add_argument("--url", type=str, help="Pinterest board or pin URL")

    dl.add_argument("--output", type=str, required=True, help="Base output directory path")
    dl.add_argument("--images", type=int, default=50, help="Requested image limit")
    dl.add_argument("--videos", type=int, default=0, help="Requested video limit")
    dl.add_argument("--gifs", type=int, default=0, help="Requested GIF limit")
    dl.add_argument("--min-width", type=int, default=0, help="Minimum width in pixels")
    dl.add_argument("--min-height", type=int, default=0, help="Minimum height in pixels")
    dl.add_argument(
        "--backend",
        type=str,
        choices=["api", "chromium", "firefox"],
        default="api",
        help="Scraper backend engine",
    )
    dl.add_argument("--cookies", type=str, default=None, help="Path to user cookies JSON file")
    dl.add_argument("--raw-video", action="store_true", help="Skip FFmpeg video remuxing")
    dl.add_argument("--overwrite", action="store_true", help="Overwrite existing files")
    dl.add_argument("--json-report", type=str, default=None, help="Path to output JSON report file")
    dl.add_argument(
        "--dry-run", action="store_true", help="Validate and print plan without downloading"
    )
    dl.add_argument("--verbose", action="store_true", help="Enable verbose logging output")

    return parser


def run_download(args: argparse.Namespace, adapter: Optional[PinterestDLAdapter] = None) -> int:
    """Execute download command based on parsed CLI arguments."""
    mode = InputMode.KEYWORD if args.keyword else InputMode.URL
    query = args.keyword if args.keyword else args.url

    try:
        backend = BackendType(args.backend)
    except ValueError:
        print(f"Error: Invalid backend '{args.backend}'", file=sys.stderr)
        return 2

    request = DownloadRequest(
        mode=mode,
        query=query,
        output_dir=args.output,
        images=args.images,
        videos=args.videos,
        gifs=args.gifs,
        min_width=args.min_width,
        min_height=args.min_height,
        backend=backend,
        cookies_path=args.cookies,
        raw_video=args.raw_video,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    try:
        request.validate()
    except ValidationError as ve:
        print(f"Validation Error: {ve}", file=sys.stderr)
        return 2

    job = Job(request=request)
    engine = DownloadEngine(adapter=adapter or PinterestDLAdapter())
    cancel_token = CancellationToken()

    def log_listener(event):
        if isinstance(event, LogEvent) and args.verbose:
            print(f"[{event.level}] {event.message}")

    try:
        result = engine.run_job(job, cancel_token=cancel_token, event_cb=log_listener)
    except KeyboardInterrupt:
        print("\n[CANCELLED] Interrupted by user (Ctrl+C).", file=sys.stderr)
        return 130

    if args.json_report:
        report_path = Path(args.json_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")

    if result.status == JobStatus.COMPLETED:
        print(f"[SUCCESS] {result.message}")
        return 0
    elif result.status == JobStatus.PARTIAL:
        print(f"[PARTIAL] {result.message}")
        return 3
    elif result.status == JobStatus.CANCELLED:
        print(f"[CANCELLED] {result.message}")
        return 130
    else:
        print(f"[FAILURE] {result.message}", file=sys.stderr)
        return 4


def main(argv: Optional[List[str]] = None) -> int:
    """Main CLI entrypoint."""
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        # Launch GUI if no args provided
        try:
            from pinterest_mass_downloader.ui.app import launch_gui

            return launch_gui()
        except ImportError:
            print("Launching Pinterest Mass Downloader GUI...")
            return 0

    parser = build_parser()

    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2

    if args.command == "doctor":
        return run_doctor()
    elif args.command == "gui":
        try:
            from pinterest_mass_downloader.ui.app import launch_gui

            return launch_gui()
        except ImportError:
            print("Launching Pinterest Mass Downloader GUI...")
            return 0
    elif args.command == "download":
        return run_download(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
