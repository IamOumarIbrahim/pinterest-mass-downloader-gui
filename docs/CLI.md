# CLI Reference — Pinterest Mass Downloader

The `pmd` command line interface supports headless execution, environment diagnostics, and automated scripting.

## Entrypoints

- `pmd [command] [options]`
- `pinterest-mass-downloader [command] [options]`
- `python -m pinterest_mass_downloader [command] [options]`

## Commands

### `gui`
Launches the desktop Tkinter application.

### `doctor`
Runs environment diagnostic checks (Python, OS, Tkinter, `pinterest-dl`, FFmpeg, directory permissions). Does not contact Pinterest.

### `download`
Runs a media download job.

Options:
- `--keyword TEXT`: Search query
- `--url URL`: Pinterest board or pin URL
- `--output PATH`: Base output directory path
- `--images N`: Image limit (default: 50)
- `--videos N`: Video limit (default: 0)
- `--gifs N`: GIF limit (default: 0)
- `--min-width N`: Minimum width in pixels
- `--min-height N`: Minimum height in pixels
- `--backend api|chromium|firefox`: Scraper engine (default: api)
- `--cookies PATH`: Path to user cookies JSON file
- `--raw-video`: Skip FFmpeg video stream remuxing
- `--overwrite`: Overwrite existing files
- `--json-report PATH`: Output path for JSON result report
- `--dry-run`: Validate plan without downloading
- `--verbose`: Enable detailed log output

## Exit Codes

- `0`: Completed successfully
- `2`: Invalid arguments or validation failure
- `3`: Partial result
- `4`: Operational failure
- `130`: Interrupted/cancelled by user
