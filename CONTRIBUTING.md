# Contributing to Pinterest Mass Downloader

Thank you for contributing!

## Development Setup

1. Clone the repository and install in editable mode with development dependencies:
   ```bash
   pip install -e ".[dev,build]"
   ```

2. Run the quality test suite:
   ```bash
   ruff format --check .
   ruff check .
   pytest --cov=pinterest_mass_downloader
   ```

3. Ensure all tests and coverage checks pass before submitting pull requests.
