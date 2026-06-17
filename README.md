# Pinterest Mass Downloader

A fast, threaded desktop application for bulk downloading Pinterest images, videos, and GIFs.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![GUI](https://img.shields.io/badge/GUI-Tkinter-orange)

## Features

- 🔍 **Keyword Search** — search by any keyword (e.g. *"Fortnite cosplays"*)
- 🌐 **Board / Pin URL** — paste any Pinterest board or pin URL to bulk download
- 🖼️ **3 Independent Sliders** — separate count controls for **Pictures**, **Videos**, and **GIFs**
- ✅ **Accurate media filtering** — uses a 2-step scrape→classify→download pipeline to ensure only the correct media types are downloaded
- ⚡ **Threaded downloads** — adjustable parallel thread count (1–32)
- 📁 **Folder picker** — native OS file explorer dialog
- 📋 **Live activity log** — color-coded real-time console output
- ⏹️ **Stop button** — gracefully cancel downloads mid-way
- 🎨 **Premium dark theme** — Pinterest red accent, Segoe UI typography

## Screenshots

> Run the app to see the full UI in action.

## Requirements

- Python 3.10+
- `pinterest-dl` (installed automatically on first run)

## Installation

```bash
git clone https://github.com/IamOumarIbrahim/pinterest-mass-downloader.git
cd pinterest-mass-downloader
pip install -r requirements.txt
```

## Usage

```bash
python pinterest_downloader.py
```

On first launch, if `pinterest-dl` is not installed, the app will prompt you to install it automatically.

### Keyword Search
1. Select **Keyword Search** mode
2. Type your query (e.g. `Fortnite cosplays`)
3. Set counts for Pictures / Videos / GIFs using the sliders
4. Choose an output folder
5. Click **START DOWNLOAD**

### Board / Pin URL
1. Select **Board / Pin URL** mode (or just paste a Pinterest URL — it auto-detects)
2. Paste the board URL (e.g. `https://www.pinterest.com/username/board-name/`)
3. Set your counts and output folder
4. Click **START DOWNLOAD**

## How Media Filtering Works

Unlike naive approaches that download everything and hope for the best, this app uses a proper pipeline:

1. **Scrape** — fetch 4× the total requested count as a metadata buffer (no files downloaded yet)
2. **Classify** — each `PinterestMedia` object is inspected:
   - `pin.video_stream is not None` → **Video**
   - `pin.src.endswith('.gif')` → **GIF**
   - Anything else → **Image**
3. **Slice** — take only the exact count you asked for per type
4. **Download** — download each type separately with the correct stream flag

## Dependencies

| Package | Purpose |
|---|---|
| `pinterest-dl` | Core Pinterest scraping & downloading |
| `tkinter` | GUI (built into Python) |
| `requests` | HTTP requests (transitive dep) |

## Powered By

- [pinterest-dl](https://github.com/sean1832/pinterest-dl) by sean1832

## Disclaimer

This tool is for **personal and educational use only**. Automated scraping may conflict with Pinterest's [Terms of Service](https://developers.pinterest.com/terms/). Use responsibly.

## License

MIT
