# Source Scraper

PRiSM-focused data project with three layers:

- **Yield export (HTTP API):** bulk CSV extraction across year/semester/region/province.
- **Browser scrape (Scrapling):** dynamic page scraping with optional table-to-CSV export and corpus output.
- **HTTP API (FastAPI + Qdrant):** versioned `/v1/` service that exposes structured
  yield queries, deterministic summaries, bulk export, and a pure hybrid (dense + sparse)
  semantic search endpoint over the same CSV. See [docs/api.md](docs/api.md).

## Features

- Job-based execution via `PRISM_JOB` (`export_yield_csv`, `browser_csv`, etc.)
- Checkpoint-aware resumable runs
- Structured scraper layering (`clients` -> `parsers` -> `spiders` -> `formatter`)
- Environment-driven tuning for rate limits, retries, delays, and browser behavior
- FastAPI service with two Qdrant collections (`prism_yield_records`,
  `prism_yield_knowledge`) and an idempotent indexer.
- Unit tests for scraper, services, indexer, and every API route (offline fakes).

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

Install API stack (required for the FastAPI service + indexer):

```bash
uv sync --extra api
```

## Running

`main.py` is a single entry point with three subcommands:

```bash
uv run python main.py                # default: scrape (same as before)
uv run python main.py scrape         # explicit scrape mode
uv run python main.py api            # start FastAPI via uvicorn
uv run python main.py index --all    # run the Qdrant indexer

uv run uvicorn main:app              # uvicorn directly (uses re-exported `app`)
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

### Mode 3: Facebook Profile (`fb_page`)

Monitors a third-party Facebook profile for the **latest post only** (permalink + images). Uses auto-login, writes JSONL only when `post_id` changes, then logs out. Images stay on disk for a future AI orchestration step (not deleted by the scraper).

`.env` example:

```env
PRISM_JOB=fb_page

FB_PROFILE_URL=https://www.facebook.com/liezl.p.aquino
FB_EMAIL=your_account@example.com
FB_PASSWORD=your_password

FB_SCRAPLING_MODE=stealth
FB_HEADLESS=true
FB_JS_SETTLE_SECONDS=10
FB_LOGIN_DELAY_MIN=1.5
FB_LOGIN_DELAY_MAX=3.5
FB_LOGIN_TYPING_DELAY_MS=85
FB_LOGIN_PAGE_WAIT=2.5
FB_LOGIN_AFTER_SUBMIT_WAIT=4.0
FB_LOGOUT_AFTER=true
FB_KEEP_IMAGES=true
FB_DOWNLOAD_IMAGES=true
FB_PROFILE_USE_ALL_TAB=true
FB_DEBUG_SAVE_HTML=false
```

`FB_PROFILE_USE_ALL_TAB` opens the profile **All** tab (not `/posts`) and targets the first post under the **Other posts** divider (skips pinned posts and comment threads). Set `FB_DEBUG_SAVE_HTML=true` to write `data/prism_processed/fb_debug_last.html` when extraction finds no valid post.

Outputs:

- `data/prism_processed/fb_liezl_posts.jsonl`
- `data/prism_processed/fb_liezl_images/{post_id}_{n}.jpg`
- `data/checkpoints/fb_liezl_checkpoint.json`

**Manual smoke:** `uv sync --extra browser`, `uv run scrapling install`, set `.env`, then `uv run python main.py scrape`. Run twice the same day; the second run should skip JSONL append if the latest post is unchanged.

**Schedule (Windows, 5 PM Manila):** Task Scheduler → Daily 17:00 → action `uv run python main.py scrape` in the repo root (ensure `.env` has `PRISM_JOB=fb_page`). Use timezone `(UTC+08:00) Kuala Lumpur, Singapore`.

**Risks:** Meta Terms restrict automated access; account checkpoints/captcha may require `FB_HEADLESS=false`. Use a dedicated Facebook account, not your primary profile.

## Environment Reference (Common)

- `PRISM_JOB`: route selector (`export_yield_csv`, `export_yield`, `browser_csv`, `browser_tables_csv`, `fb_page`)
- `PRISM_URL` / `PRISM_URLS`: required for browser jobs
- `PRISM_SCRAPLING_MODE`: `fetch` | `stealth` | `dynamic`
- `PRISM_CONTENT_SELECTOR`: optional CSS selector override for focused extraction
- `PRISM_REWRITE_DATAPRODUCTS_TO_APP`: rewrite `/dataproducts/` to dynamic app endpoint
- `PRISM_RESUME_CHECKPOINT`: enable/disable resume behavior

## API service (Qdrant + FastAPI)

```bash
# Install API dependencies
uv sync --extra api

# Run Qdrant locally
docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant

# Index the yield CSV into Qdrant (structured + knowledge collections)
uv run python main.py index --collections all

# Start the API (either of these works)
uv run python main.py api --reload --port 8000
uv run uvicorn main:app --reload --port 8000
```

Full endpoint reference and configuration in [docs/api.md](docs/api.md).

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
- **FB login fails / checkpoint page**
  - Set `FB_HEADLESS=false`, complete any challenge manually, then retry.
- **No post found on FB profile**
  - Confirm you can see the timeline when logged in manually; profile may be private.

## Notes

- Checkpoints are updated incrementally for long-running jobs.
- Keep runtime artifacts in `data/` out of commits except tracked placeholders (e.g., `.gitkeep`).