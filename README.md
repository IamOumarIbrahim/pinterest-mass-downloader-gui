<div align="center">
  <h1>🛑 Pinterest Mass Downloader</h1>
  <p><strong>A fast desktop application for bulk downloading Pinterest media</strong></p>

  [![Python](https://img.shields.io/badge/Python-3.10+-blue.svg?style=flat-square&logo=python&logoColor=white)](#)
  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
  [![Platform](https://img.shields.io/badge/Platform-Windows_11-lightgrey.svg?style=flat-square)](#)

  <br />
  [![pinterest-dl](https://img.shields.io/badge/Backend-pinterest--dl-E60023.svg?style=flat-square)](#)
</div>

<p align="center">
  <img src="assets/demo.gif" alt="Pinterest Downloader Live Demo" width="100%" />
</p>

> [!IMPORTANT]
> **Account Requirement**: Pinterest frequently updates their scraping protections; you may need to provide session cookies for large batch downloads.

Pinterest Mass Downloader is a fast, threaded desktop application for bulk downloading Pinterest images, videos, and GIFs by keyword search or board URL, featuring a premium dark-themed GUI. It simplifies the archival of visual references and mood boards without manually saving each pin.

```python
// Command line execution example
python pinterest_downloader.py --board "https://pinterest.com/user/board" --out "./downloads"
```

<br />

## 📖 Table of Contents
- [What is Pinterest Mass Downloader?](#-what-is-pinterest-mass-downloader)
- [Key Features](#-key-features)
- [System Architecture](#-system-architecture)
- [Setup & Installation](#-setup--installation)
- [How to Use](#-how-to-use)
- [Reference Tables](#-reference-tables)
- [Scope & Limitations](#-scope--limitations)
- [File Structure](#-file-structure)
- [Troubleshooting](#-troubleshooting)
- [Contributing](#-contributing)
- [License](#-license)

---

## 💡 What is Pinterest Mass Downloader?

Archiving full mood boards or reference collections from Pinterest manually takes hours and often results in compressed or incomplete downloads. 

Instead of manual right-clicking, Pinterest Mass Downloader automates the process:
- **Bulk Extraction**: Pulls entire boards or keyword search results instantly.
- **Threaded Downloading**: Maximizes your bandwidth to pull media in parallel.
- **Premium GUI**: Provides an easy-to-use dark-themed interface for non-technical users.

---

## ✨ Key Features

- ⚡ **Multi-Threaded**: Downloads concurrent media streams to saturate your connection.
- 🎨 **Dark-Themed GUI**: Built with modern UI libraries for a clean desktop experience.
- 🔗 **Board & Keyword Support**: Scrape directly from a curated URL or a broad keyword query.
- 📦 **Standalone Executable**: Ships with a pre-compiled `.exe` so no Python installation is required.

---

## ⚙️ System Architecture

Data flow from the Pinterest servers to your local storage via the application.

```mermaid
graph TD
    [User GUI] --> [Thread Manager]
    [Thread Manager] --> [Scraper Engine]
    [Scraper Engine] --> [Pinterest CDN]
    [Pinterest CDN] --> [Local Storage]

    classDef default fill:#0f172a,stroke:#3b82f6,stroke-width:2px,color:#fff;
    classDef process fill:#1e1b4b,stroke:#a855f7,stroke-width:2px,color:#fff;
    class [Thread Manager],[Scraper Engine] process;
```

> [!NOTE]
> **Design Decision**: A threaded architecture was chosen over async/await to easily integrate with standard UI framework event loops without complex thread-safety issues.

---

## 🚀 Setup & Installation

### Option A: 1-Click Setup (Windows)
```cmd
pinterest_downloader.exe
```
Just run the pre-compiled executable, no installation needed.

### Option B: Manual Installation

```bash
git clone https://github.com/username/pinterest.git
cd pinterest
pip install -r requirements.txt
```

🔍 **Verification Command**:
```bash
python pinterest_downloader.py --help
```
*Expected Output*: Displays the CLI help menu.

---

## 🖥️ How to Use

1. Launch `pinterest_downloader.exe`.
2. Paste your target Board URL or type a search query.
3. Select an output directory and click "Start Download".

```bash
# Alternative CLI usage
python pinterest_downloader.py --keyword "cyberpunk city" --limit 100
```

---

## 📊 Reference Tables

| CLI Flag | Description | Default |
| :--- | :--- | :--- |
| `--board` | URL of the Pinterest board | None |
| `--keyword` | Search term to scrape | None |
| `--limit` | Maximum number of pins | 50 |

---

## 🔬 Scope & Limitations

- **Scraping Protections**: Pinterest may block IP addresses that scrape too aggressively.
- **Private Boards**: Cannot currently scrape private boards without manual cookie injection.

---

## 📁 File Structure

```
pinterest/
├── assets/
│   └── demo.gif               - Demo preview animation
├── pinterest_downloader.py    - Main application logic
├── pinterest_downloader.spec  - PyInstaller build spec
├── implementation_plan.md     - Developer roadmap
├── requirements.txt           - Python dependencies
└── README.md                  - Project documentation
```

---

## 🩹 Troubleshooting

| Issue | Root Cause | Resolution |
| :--- | :--- | :--- |
| Downloads failing instantly | Rate limiting | Wait 24 hours or use a VPN to change your IP |
| Executable blocked | Windows SmartScreen | Click "More info" and "Run anyway" |

---

## 🧩 Contributing

To contribute, review `implementation_plan.md` for upcoming features. The UI layer and the scraping engine are intentionally decoupled to allow easy updates to the scraper when Pinterest changes its API.

---

## 📄 License
MIT © 2024 Author(https://github.com/username)

<div align="center">

If Pinterest Mass Downloader saved you hours of right-clicking, a ⭐ helps other people find it.

</div>
