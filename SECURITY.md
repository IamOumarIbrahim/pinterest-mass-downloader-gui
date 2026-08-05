# Security Policy — Pinterest Mass Downloader

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 2.0.x   | :white_check_mark: |
| < 2.0   | :x:                |

## Reporting a Vulnerability

Please report security issues or credential leak concerns via email to `iamoumaribrahim@gmail.com`.

## Security Guarantees

- **No Secret Persistence**: Cookie files and authentication tokens are never stored in settings, queue state, manifest files, or logs.
- **Path Sanitization**: All query strings and folder paths are sanitized against directory traversal attacks.
