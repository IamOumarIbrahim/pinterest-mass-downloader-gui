# Pinterest Mass Downloader v2.0.0 Release Notes

We are thrilled to release **Pinterest Mass Downloader v2.0.0**, a major architecture upgrade transforming the legacy single-file script into a maintainable, typed, cross-platform CLI and Tkinter GUI application.

## Key Highlights

- **Modular Architecture**: Complete refactoring into layered package design (`domain`, `application`, `services`, `infrastructure`, `ui`).
- **Real CLI**: `pmd` executable supporting `--dry-run`, `--json-report`, custom exit codes, and `pmd doctor`.
- **Refactored Dark GUI**: Responsive Tkinter interface with typed event polling, queue editing, and safe exit handling.
- **Cooperative Cancellation**: Non-daemon worker threads checking batch checkpoints for clean stopping.
- **Manifest Resume System**: `pmd-manifest.json` duplicate protection and partial job resuming.
- **Strict Privacy**: User-selected cookie files loaded strictly at runtime without storing secrets.
- **Comprehensive Quality Gate**: 80%+ test coverage, clean packaging, and build pipelines.
