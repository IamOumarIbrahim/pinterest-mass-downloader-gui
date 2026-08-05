# Architecture Overview — Pinterest Mass Downloader v2.0.0

## Layer Separation

`src/pinterest_mass_downloader/` is structured into decoupled layers:

```text
src/pinterest_mass_downloader/
├── domain/            # Core enums, errors, immutable DownloadRequest & Job models
├── infrastructure/    # Path sanitization, OS folder openers, logging helpers
├── services/          # Pinterest DL adapter, classifier, manifests, platformdirs persistence
├── application/       # Engine, cooperative cancellation tokens, QueueManager, typed events
└── ui/                # Tkinter app, controller/presenter, dark theme tokens, custom widgets
```

## Import Boundaries & Invariants

1. **Upstream Adapter Boundary**: Only `services/pinterest_adapter.py` may import `pinterest_dl`.
2. **UI Boundary**: Only modules under `ui/` may import `tkinter`.
3. **Domain Independence**: Domain models have zero dependencies on Tkinter, OS launchers, or `pinterest_dl`.
4. **Cancellable Worker Pool**: Worker threads are non-daemon (`thread.daemon = False`) and check cancellation tokens at batch checkpoints.
5. **No Monolithic Source**: Production modules are kept under 500 physical lines.
