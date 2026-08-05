# Pinterest Mass Downloader v1 Baseline Assessment

Captured: 2026-08-05

## Summary of Verified Baseline Problems

1. **Monolithic Design**: The entire application logic, UI, scraping calls, and threading reside in a single file `pinterest_downloader.py` (~1,160 lines).
2. **Unused Thread Slider**: The GUI exposes a thread count slider (`max_threads`), but the value is never used by the download worker.
3. **Private Upstream API Usage**: Downloads invoke internal private method `PinterestDL._download_and_save`.
4. **Unsafe Cancellation / Threading**: Stop handling marks the job complete while worker daemon threads are still active, allowing overlapping file writes and race conditions.
5. **Untyped Worker Results**: Exceptions, scrape failures, or empty search results are treated as completed jobs because progress/completion state relies on regex-parsing GUI log lines.
6. **Fragile State Management**: Progress bars and media counters are updated by matching text regexes against log output strings.
7. **Windows-Only OS Calls**: `os.startfile` is used directly for opening download folders, crashing on macOS and Linux.
8. **In-App Dependency Installation**: The GUI offers runtime dependency installation (`pip install` subprocess calls).
9. **Inaccurate CLI & Documentation**: `README.md` documents CLI flags and prebuilt executables that do not exist in the repo codebase.
10. **Missing Cookie Support**: Mentioned in README but not wired to `pinterest-dl`.
11. **No Test Suite or Packaging Scaffolding**: Absence of `pyproject.toml`, test files, linting config, or CI pipeline.
