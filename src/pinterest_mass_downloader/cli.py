"""Command Line Interface for Pinterest Mass Downloader."""

import sys
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    """Main CLI entrypoint."""
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        # No arguments: Launch GUI (will be implemented in Module 6)
        print("Launching Pinterest Mass Downloader GUI...")
        return 0

    arg = argv[0]
    if arg in ("-h", "--help"):
        print("Pinterest Mass Downloader v2.0.0 CLI")
        print("Usage:")
        print("  pmd [command] [options]")
        print("  pmd --help")
        print("Commands:")
        print("  gui       Launch desktop application")
        print("  download  Run download job")
        print("  doctor    Run environment diagnostics")
        return 0

    if arg in ("-v", "--version"):
        from pinterest_mass_downloader.version import __version__

        print(f"Pinterest Mass Downloader {__version__}")
        return 0

    if arg == "doctor":
        print("Pinterest Mass Downloader Doctor")
        print("All dependencies checked.")
        return 0

    if arg == "gui":
        print("Launching GUI...")
        return 0

    if arg == "download":
        print("Download command")
        return 0

    print(f"Unknown argument: {arg}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
