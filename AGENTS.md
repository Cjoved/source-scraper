# Source Scraper Agent Guide

## Scope
- This repository scrapes PRiSM data using two pipelines:
  - `export_yield_csv` / `export_yield`: HTTP API bulk export to CSV.
  - Browser pipelines (`browser_csv` / default): Scrapling page scraping, optional table-to-CSV and corpus output.

## Project Layout
- `main.py`: entrypoint.
- `src/scraper/`: orchestration, clients, parsers, spiders.
- `src/formatter/`: CSV shaping/writers.
- `src/services/`: config, checkpoints, logging.
- `src/utils/`: network/retry/url/date helpers.
- `tests/`: unit tests.
- `data/`: runtime outputs/checkpoints.

## Standard Commands
- Install core deps: `uv sync`
- Install browser deps: `uv sync --extra browser`
- Install Scrapling fetchers: `uv run scrapling install`
- Run app: `uv run python main.py`
- Run tests: `uv run python -m unittest discover -s tests -p "test_*.py" -v`

## Environment Presets
- Yield export mode:
  - `PRISM_JOB=export_yield_csv`
- Browser table CSV mode:
  - `PRISM_JOB=browser_csv`
  - `PRISM_URL=https://prism.philrice.gov.ph/dataproducts/`
  - `PRISM_BROWSER_SAVE_CORPUS=false`

## Output Contracts
- Yield export CSV: `data/prism_processed/prism_yield_export.csv`
- Browser tables CSV: `data/prism_processed/prism_browser_tables.csv`
- Browser corpus JSONL: `data/prism_processed/prism_corpus.jsonl`
- Checkpoints:
  - `data/checkpoints/prism_yield_export_checkpoint.json`
  - `data/checkpoints/prism_checkpoint.json`

## Coding Rules
- Keep scraper layering explicit:
  - HTTP/browser calls in `clients`
  - extraction logic in `parsers`
  - orchestration loops in `spiders`
  - output shaping/writing in `formatter`
- Use `data_path()` from `src/services/config.py` for output paths.
- Do not hardcode absolute machine paths.
- Add/update unit tests for parser and formatter behavior changes.

## Operational Rules
- Prefer checkpoint-safe updates; avoid breaking resume behavior.
- Do not commit runtime artifacts from `data/` except tracked `.gitkeep` files.
- Keep `.env` examples mode-specific; avoid mixing conflicting job settings.
