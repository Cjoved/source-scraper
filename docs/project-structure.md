# Source-Scraper Project Structure

This is the canonical folder guide to avoid confusion when adding files.

## Root

- `main.py` - Unified CLI entrypoint (`scrape`, `openstat`, `api`, `index`)
- `pyproject.toml` / `uv.lock` - Dependency and lock management
- `.env` - Runtime configuration (local only; do not commit secrets)

## Source Code

- `src/scraper/` - Canonical PRiSM implementation
  - `clients/` - network/browser clients
  - `parsers/` - extractors/parsers
  - `spiders/` - orchestration runners
- `src/openstat/` - OpenStat compatibility implementation
  - `main.py` - OpenStat workflow dispatch
  - `scrapers/` - OpenStat crawler flows
  - `services/` - OpenStat processing flows
  - `agri_corpus/` - chunking/pdf/cpt helpers
  - `utils/` - OpenStat helper utilities
- `src/services/` - shared service-layer logic
- `src/formatter/` - CSV and output formatting
- `src/api/` - FastAPI HTTP API
- `src/indexing/` - CSV-to-Qdrant indexing
- `src/storage/` - persistence adapters
- `src/models/` - data models
- `src/utils/` - shared utility helpers

## Documentation

- `docs/api.md` - API guide
- `docs/deploy.md` - deployment plan
- `docs/migration/` - OpenStat migration artifacts
- `docs/project-structure.md` - this structure guide

## Runtime Data (not for commits)

- `data/checkpoints/`
- `data/prism_processed/`
- other `data/*` outputs from scraper workflows

