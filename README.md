# Pinterest Mass Downloader v2.0.0

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

A powerful, cross-platform Pinterest mass downloader featuring a responsive dark Tkinter GUI and a feature-rich CLI (`pmd`).

> **Disclaimer**: This is an unofficial, community-maintained tool not affiliated with or endorsed by Pinterest. Users are responsible for complying with Pinterest Terms of Service, rate limits, and copyright laws.

---

## Features

- **Tkinter Desktop GUI**: Preserves dark Pinterest visual identity with responsive queue management.
- **Full-featured CLI**: `pmd` command supporting dry-runs, JSON reports, custom exit codes, and environment diagnostics (`pmd doctor`).
- **Keyword & URL Modes**: Support for search queries as well as Pinterest board and pin URLs.
- **Media Classification**: Separate counts for Images, Videos, and GIFs with resolution bounds.
- **Cooperative Cancellation**: Safe batch checkpoints so worker threads never leave orphaned processes or corrupted files.
- **Atomic Persistence & Resume**: Automatic job state persistence via `platformdirs` and per-job `pmd-manifest.json` resume tracking.
- **Privacy & Security**: User-selected cookie files loaded at runtime without copying credentials into app state or logs.

---

## Installation

```bash
# Clone repository
git clone https://github.com/IamOumarIbrahim/pinterest-mass-downloader-gui.git
cd pinterest-mass-downloader-gui

# Install in editable mode with development dependencies
pip install -e ".[dev,build]"
```

---

## Quick Usage

### Desktop GUI
Launch the desktop application using any of the following entrypoints:
```bash
pmd gui
pinterest-mass-downloader gui
python -m pinterest_mass_downloader gui
python pinterest_downloader.py
```

### Command Line Interface (CLI)

```bash
# Environment diagnostics check
pmd doctor

# Dry-run search plan without downloading
pmd download --keyword "architecture" --output ./downloads --images 5 --dry-run

# Real keyword download job
pmd download --keyword "modern living room" --output ./downloads --images 20 --videos 2

# Board/Pin URL download with custom cookies
pmd download --url "https://www.pinterest.com/example/board/" --output ./downloads --images 50 --cookies ./my_cookies.json
```

---

## Documentation

- [Architecture Guide](docs/ARCHITECTURE.md)
- [CLI Reference](docs/CLI.md)
- [GUI Guide](docs/GUI.md)
- [Privacy & Cookies Policy](docs/PRIVACY_AND_COOKIES.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [v2.0.0 Migration Notes](docs/v2/MIGRATION.md)
- [v2.0.0 Release Notes](docs/v2/RELEASE_NOTES.md)

---

## License

Distributed under the [MIT License](LICENSE).
