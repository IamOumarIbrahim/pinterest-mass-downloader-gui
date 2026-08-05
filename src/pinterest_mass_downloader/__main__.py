"""Package execution entrypoint (python -m pinterest_mass_downloader)."""

import sys

from pinterest_mass_downloader.cli import main

if __name__ == "__main__":
    sys.exit(main())
