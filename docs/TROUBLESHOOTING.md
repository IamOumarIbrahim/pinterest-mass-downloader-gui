# Troubleshooting Guide — Pinterest Mass Downloader v2.0.0

## Common Issues & Solutions

### 1. `pmd` is not recognized as a command
Ensure your Python scripts directory is in your system PATH, or invoke the CLI via Python:
```bash
python -m pinterest_mass_downloader doctor
```

### 2. Video streams are missing or unmerged
FFmpeg is required for automatic video stream remuxing. Run `pmd doctor` to check FFmpeg availability. Use `--raw-video` to output raw video streams without FFmpeg.

### 3. Rate limiting or empty search results
Pinterest may throttle requests if scraping large amounts of media rapidly. Try using lower requested limits, adding a small delay, or supplying a cookie file for authenticated sessions.
