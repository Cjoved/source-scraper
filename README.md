# Source Scraper

PRiSM-focused data scraping project with two production-ready pipelines:

- **Yield export (HTTP API):** bulk CSV extraction across year/semester/region/province.
- **Browser scrape (Scrapling):** dynamic page scraping with optional table-to-CSV export and corpus output.

## Features

- Job-based execution via `PRISM_JOB` (`export_yield_csv`, `browser_csv`, etc.)
- Checkpoint-aware resumable runs
- Structured scraper layering (`clients` -> `parsers` -> `spiders` -> `formatter`)
- Environment-driven tuning for rate limits, retries, delays, and browser behavior
- Unit tests for parser and runner core paths

## Project Structure

```text
source-scraper/
├─ main.py
├─ pyproject.toml
├─ src/
│  ├─ scraper/
│  │  ├─ clients/
│  │  ├─ parsers/
│  │  ├─ spiders/
│  │  ├─ prism.py
│  │  ├─ prism_constants.py
│  │  └─ prism_browser_config.py
│  ├─ formatter/
│  ├─ services/
│  ├─ utils/
│  └─ models/
├─ tests/
└─ data/
```

## Requirements

- Python `>=3.12`
- [uv](https://docs.astral.sh/uv/)

## Installation

Install core dependencies:

```bash
uv sync
```

Install browser stack (required for Scrapling browser jobs):

```bash
uv sync --extra browser
uv run scrapling install
```

## Running

Run the application:

```bash
uv run python main.py
```

### Mode 1: Yield Export (HTTP -> CSV)

Use this for full yield-table export.

`.env` example:

```env
PRISM_JOB=export_yield_csv
PRISM_EXPORT_DELAY=1.0
PRISM_EXPORT_JITTER=0.55
PRISM_EXPORT_YEAR_MIN=2018
PRISM_EXPORT_YEAR_MAX=2026
PRISM_EXPORT_RETRIES=5
PRISM_EXPORT_TIMEOUT=90
PRISM_EXPORT_COOLDOWN_EVERY=75
PRISM_EXPORT_COOLDOWN_SECONDS=12
```

Output:

- `data/prism_processed/prism_yield_export.csv`
- `data/checkpoints/prism_yield_export_checkpoint.json`

### Mode 2: Browser Tables CSV (Scrapling -> CSV)

Use this for browser-rendered table extraction from target URL(s).

`.env` example:

```env
PRISM_JOB=browser_csv
PRISM_URL=https://prism.philrice.gov.ph/dataproducts/
PRISM_SCRAPLING_MODE=stealth
PRISM_JS_SETTLE_SECONDS=8
PRISM_BROWSER_SAVE_CORPUS=false
PRISM_BROWSER_TABLE_MAX_COLS=32
```

Outputs:

- `data/prism_processed/prism_browser_tables.csv`
- Optional corpus output:
  - `data/prism_processed/prism_corpus.jsonl`
  - `data/prism_txt/`
- `data/checkpoints/prism_checkpoint.json`

## Environment Reference (Common)

- `PRISM_JOB`: route selector (`export_yield_csv`, `export_yield`, `browser_csv`, `browser_tables_csv`)
- `PRISM_URL` / `PRISM_URLS`: required for browser jobs
- `PRISM_SCRAPLING_MODE`: `fetch` | `stealth` | `dynamic`
- `PRISM_CONTENT_SELECTOR`: optional CSS selector override for focused extraction
- `PRISM_REWRITE_DATAPRODUCTS_TO_APP`: rewrite `/dataproducts/` to dynamic app endpoint
- `PRISM_RESUME_CHECKPOINT`: enable/disable resume behavior

## Testing

Run unit tests:

```bash
uv run python -m unittest discover -s tests -p "test_*.py" -v
```

## Troubleshooting

- **`No valid PRISM_URL / PRISM_URLS`**
  - You are in browser mode without URL input. Set `PRISM_URL` or switch to yield mode.
- **`unrecognized subcommand 'scrapling'`**
  - Use `uv run scrapling install` (not `uv scrapling install`).
- **No tables in browser CSV**
  - Increase `PRISM_JS_SETTLE_SECONDS` or set `PRISM_CONTENT_SELECTOR` for current DOM.

## Notes

- Checkpoints are updated incrementally for long-running jobs.
- Keep runtime artifacts in `data/` out of commits except tracked placeholders (e.g., `.gitkeep`).