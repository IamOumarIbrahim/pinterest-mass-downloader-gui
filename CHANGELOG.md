# Changelog

All notable changes to Pinterest Mass Downloader will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-08-05

### Added
- Modular package structure under `src/pinterest_mass_downloader/`.
- Full-featured CLI entrypoint `pmd` supporting `gui`, `download`, and `doctor`.
- Cooperative batch cancellation tokens preventing orphaned worker threads.
- `pmd-manifest.json` per-job manifest files for resumable downloads and duplicate protection.
- Atomic persistence for settings and queue using `platformdirs`.
- User-supplied cookies file support loaded strictly at runtime.
- Comprehensive test suite covering unit, integration, architecture, CLI, and GUI smoke.
- Continuous integration and build release workflows.

### Changed
- Refactored single-file monolithic codebase into clean domain, service, application, infrastructure, and UI layers.
- Upgraded upstream integration to use only verified public APIs of `pinterest-dl` (v1.3.0).
- Converted legacy `pinterest_downloader.py` into a lightweight compatibility launcher.

### Removed
- Removed non-functional thread slider from GUI in favor of upstream concurrent pool processing.
- Removed private upstream function calls (`_download_and_save`).
