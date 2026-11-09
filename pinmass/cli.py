"""Command-line mode: `python pinterest_downloader.py --keyword fortnite --limit 30`."""

from __future__ import annotations

import argparse
import queue
import sys
import threading

from .matching import MatchSettings
from .worker import Job, Worker


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pinterest_downloader.py",
        description="Bulk download Pinterest pictures, videos and GIFs. "
                    "Run without arguments to open the app.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--phone", metavar="FOLDER",
                     help="share FOLDER with your phone over Wi-Fi (browse + share, no copying)")
    src.add_argument("--keyword", "-k", help="search term, e.g. 'fortnite'")
    src.add_argument("--board", "-b", help="board or pin URL")
    p.add_argument("--limit", "-n", type=int, default=50, help="number of pictures (default 50)")
    p.add_argument("--videos", type=int, default=0, help="number of videos (default 0)")
    p.add_argument("--gifs", type=int, default=0, help="number of GIFs (default 0)")
    p.add_argument("--out", "-o", default="./downloads", help="output folder (default ./downloads)")
    p.add_argument("--threads", type=int, default=8, help="parallel downloads (default 8)")
    m = p.add_argument_group("matching a reference image")
    m.add_argument("--reference", "-r", help="path to the reference image")
    m.add_argument("--similar", action="store_true", help="keep pins that look like the reference")
    m.add_argument("--colors", action="store_true", help="keep pins with the reference's colours")
    m.add_argument("--tolerance", type=float, default=50,
                   help="colour tolerance 0 (same amounts) to 100 (any amounts), default 50")
    m.add_argument("--closeness", type=float, default=50,
                   help="look-alike strictness 0 (loose) to 100 (very close), default 50")
    return p


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    if args.phone:
        from .phone import serve_forever
        serve_forever(args.phone)
        return 0
    if (args.similar or args.colors) and not args.reference:
        print("--similar/--colors need --reference IMAGE", file=sys.stderr)
        return 2
    if args.reference and not (args.similar or args.colors):
        args.similar = True
    job = Job(
        query=args.keyword or args.board,
        out_dir=args.out,
        counts={"image": max(0, args.limit), "video": max(0, args.videos),
                "gif": max(0, args.gifs)},
        match=MatchSettings(reference=args.reference, look=args.similar, colors=args.colors,
                            color_tolerance=args.tolerance, closeness=args.closeness),
        threads=max(1, min(args.threads, 32)),
    )
    events: queue.Queue = queue.Queue()
    worker = Worker(job, events)
    t = threading.Thread(target=worker.run, daemon=True)
    t.start()
    try:
        while True:
            ev = events.get()
            if ev.type == "log":
                print(ev.text, flush=True)
            elif ev.type == "done":
                break
    except KeyboardInterrupt:
        worker.stop()
        print("Stopping…")
        t.join(timeout=5)
        return 130
    return 0 if sum(worker.saved.values()) else 1
