# Pinterest Mass Downloader v2 Scope & Requirements

Captured: 2026-08-05

## Core Deliverables for v2.0.0

1. **Modular Architecture**: Re-architect into clean package layout under `src/pinterest_mass_downloader/`.
2. **Public Upstream API**: Use only public methods of `pinterest-dl` (v1.3.0) via adapter interface.
3. **Robust CLI**: Complete CLI supporting `gui`, `download` (with dry-run, json reporting, custom exit codes), and `doctor`.
4. **Refactored GUI**: Responsive Tkinter interface preserving dark theme identity, driven by typed events.
5. **Cooperative Cancellation**: Non-daemon worker threads with batch checkpoint cancellation checks.
6. **Cross-Platform Compatibility**: Abstraction for opening output folders on Windows, macOS, and Linux.
7. **Atomic Persistence & Manifests**: Settings/queue persistence via `platformdirs` and per-job `pmd-manifest.json` resume files.
8. **Security & Privacy**: User-selected cookie files supported without storing or logging cookie values.
9. **Quality Gate**: Comprehensive tests (unit, integration, architecture, CLI, GUI smoke) with >= 80% coverage and clean packaging/build.
