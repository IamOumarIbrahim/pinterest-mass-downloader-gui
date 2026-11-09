"""
Pinterest Mass Downloader

    python pinterest_downloader.py                 open the app
    python pinterest_downloader.py --keyword cats  download from the command line

See README.md for all options.
"""

import sys


def main() -> int:
    if len(sys.argv) > 1:
        from pinmass.cli import main as cli_main
        return cli_main(sys.argv[1:])
    from pinmass.gui import main as gui_main
    gui_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
