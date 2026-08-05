# v2.0.0 Migration Guide

## Breaking Changes & Upgrades from v1.x

1. **CLI Commands**: `python pinterest_downloader.py` now functions as a CLI compatibility wrapper. Standard CLI usage uses `pmd [command]` (`gui`, `download`, `doctor`).
2. **Package Structure**: Logic has been refactored into `src/pinterest_mass_downloader/`.
3. **Queue & Manifest Files**: Jobs automatically maintain `pmd-manifest.json` in their output directories for resume capability.
4. **Thread Slider Removed**: The manual thread slider in GUI was replaced by upstream concurrent worker pool management in `pinterest-dl`.
