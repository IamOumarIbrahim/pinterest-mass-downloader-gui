<div align="center">
  <h1>Pinterest Mass Downloader</h1>
  <p><strong>Fast desktop application for bulk downloading Pinterest media</strong></p>

  <p>
    <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10+-blue.svg?style=flat-square&logo=python&logoColor=white" alt="Python" /></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square" alt="License: MIT" /></a>
    <img src="https://img.shields.io/badge/Platform-Windows-lightgrey.svg?style=flat-square" alt="Platform" />
  </p>
</div>

<p align="center">
  <img src="assets/demo.gif" alt="Pinterest Downloader Live Demo" width="100%" />
</p>

Multi-threaded desktop GUI for bulk downloading Pinterest images, videos, and GIFs by board URL or keyword search.

## Quickstart

```bash
git clone https://github.com/IamOumarIbrahim/pinterest-mass-downloader-gui.git
cd pinterest-mass-downloader-gui
pip install -r requirements.txt
python pinterest_downloader.py
```

### CLI Usage

```bash
# Download by board URL
python pinterest_downloader.py --board "https://pinterest.com/user/board" --out "./downloads"

# Download by keyword search
python pinterest_downloader.py --keyword "architecture design" --limit 100 --out "./downloads"
```

## Options

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--board` | URL of the Pinterest board | None |
| `--keyword` | Search term to scrape | None |
| `--limit` | Maximum number of pins | 50 |
| `--out` | Output destination folder | `./downloads` |

## License

MIT License.
