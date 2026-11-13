"""Command-line mode: `python pinterest_downloader.py --keyword fortnite --limit 30`."""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time

from . import library
from .matching import MatchSettings
from .worker import Job, Worker, follow_job


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
    src.add_argument("--check-follows", action="store_true",
                     help="fetch what's new for everything you follow")
    src.add_argument("--follows", action="store_true", help="list what you follow")
    src.add_argument("--unfollow", metavar="NAME", help="stop following a search or board")
    p.add_argument("--follow", action="store_true",
                   help="with --keyword/--board: remember it, and fetch only what's new on "
                        "later --check-follows runs (--limit etc. become the most per check)")
    p.add_argument("--limit", "-n", type=int, default=50, help="number of pictures (default 50)")
    p.add_argument("--videos", type=int, default=0, help="number of videos (default 0)")
    p.add_argument("--gifs", type=int, default=0, help="number of GIFs (default 0)")
    p.add_argument("--out", "-o", default="./downloads", help="output folder (default ./downloads)")
    p.add_argument("--threads", type=int, default=8, help="parallel downloads (default 8)")
    p.add_argument("--cookies", metavar="FILE",
                   help="sign in with cookies exported from your browser (cookies.txt or JSON); "
                        "remembered for later runs. Needed for private boards.")
    p.add_argument("--sign-out", action="store_true", help="forget the saved Pinterest login")
    p.add_argument("--min-size", type=int, default=0, metavar="PIXELS",
                   help="only originals whose shorter side is at least this many pixels")
    p.add_argument("--shape", choices=("any", "tall", "wide", "square"), default="any",
                   help="only tall (phone wallpaper), wide (desktop) or square pictures")
    p.add_argument("--allow-duplicates", action="store_true",
                   help="download pictures even if the library says you already have them")
    m = p.add_argument_group("matching a reference image")
    m.add_argument("--reference", "-r", help="path to the reference image")
    m.add_argument("--similar", action="store_true", help="keep pins that look like the reference")
    m.add_argument("--colors", action="store_true", help="keep pins with the reference's colours")
    m.add_argument("--tolerance", type=float, default=50,
                   help="colour tolerance 0 (same amounts) to 100 (any amounts), default 50")
    m.add_argument("--closeness", type=float, default=50,
                   help="look-alike strictness 0 (loose) to 100 (very close), default 50")
    m.add_argument("--describe", "-d", default="", metavar="TEXT",
                   help="keep pins that fit a description, e.g. \"line drawing, no words\" "
                        "(uses the smart model; about 150 MB download the first time)")
    m.add_argument("--classic", action="store_true",
                   help="don't use the smart model; compare shapes and edges only")
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
    from . import scraper, settings
    if args.sign_out:
        settings.save_cookies(None)
    if args.cookies:
        try:
            jar = scraper.read_cookies(args.cookies)
        except OSError as exc:
            print(f"Couldn't read {args.cookies}: {exc}", file=sys.stderr)
            return 2
        if not scraper.signed_in(jar):
            print("Those cookies aren't from a signed-in Pinterest session. Sign in to "
                  "pinterest.com in your browser, then export the cookies again.", file=sys.stderr)
            return 2
        settings.save_cookies(jar)
    jar = settings.load_cookies()
    if scraper.signed_in(jar):
        scraper.sign_in(jar)
        print("Signed in to Pinterest with your saved login.")
    lib = library.shared()
    if args.follows:
        for f in lib.follows():
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(f.checked)) if f.checked else "never"
            print(f"{f.query}  →  {f.folder}  (checked {when}, {f.total} fetched so far)")
        return 0
    if args.unfollow:
        gone = [f for f in lib.follows() if f.query.lower() == args.unfollow.lower()]
        for f in gone:
            lib.unfollow(f.id)
        print(f"Stopped following {len(gone)}." if gone else "You don't follow that.")
        return 0 if gone else 1
    if args.check_follows:
        total = 0
        for f in lib.follows():
            print(f"── {f.query}")
            n = _run(follow_job(f, lib, max(1, min(args.threads, 32))))
            if n < 0:
                return 130
            lib.follow_checked(f.id, n)
            total += n
        print(f"{total} new files.")
        return 0
    job = Job(
        query=args.keyword or args.board,
        out_dir=args.out,
        counts={"image": max(0, args.limit), "video": max(0, args.videos),
                "gif": max(0, args.gifs)},
        match=MatchSettings(reference=args.reference, look=args.similar, colors=args.colors,
                            color_tolerance=args.tolerance, closeness=args.closeness,
                            smart=not args.classic, describe=args.describe),
        threads=max(1, min(args.threads, 32)),
        library=library.shared(), skip_owned=not args.allow_duplicates,
        min_side=max(0, args.min_size), shape=args.shape,
    )
    if args.follow:
        f = lib.follow(job.query, os.path.abspath(job.out_dir), job.counts, job.min_side, job.shape)
        job.follow_id = f.id
        job.out_dir = f.folder
        print(f"Following “{job.query}”. Run with --check-follows to fetch what's new.")
    n = _run(job)
    if n < 0:
        return 130
    if job.follow_id is not None:
        lib.follow_checked(job.follow_id, n)
    return 0 if n else 1


def _run(job: Job) -> int:
    """Run one job, printing its log. Returns files saved, or -1 if interrupted."""
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
        return -1
    return sum(worker.saved.values())
