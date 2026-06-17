# Source Scraper Agent Guide

## Scope
- This repository scrapes PRiSM data:
  - `export_yield_csv` / `export_yield`: HTTP API bulk export to CSV.
  - Browser pipelines (`browser_csv` / default): Scrapling page scraping, optional table-to-CSV and corpus output.
  - OpenStat compatibility workflows via `python main.py openstat` (PhilRice, PhilRice News, PinoyRice, OpenSTAT, IRRI).

## Project Layout
- `main.py`: entrypoint.
- `src/orchestrator/`: scheduled runs via `orchestrator.yaml` (`python -m src.orchestrator`).
- `src/scraper/`: canonical PRiSM orchestration, clients, parsers, spiders.
- `src/openstat/`: OpenStat compatibility package.
  - `src/openstat/scrapers/`: OpenStat workflow scrapers (PhilRice, News, PinoyRice, OpenSTAT, IRRI).
  - `src/openstat/services/`: OpenStat post-processing pipelines.
  - `src/openstat/agri_corpus/`: text/pdf/cpt helpers used by OpenStat services.
  - `src/openstat/utils/`: OpenStat-specific network/db helpers.
  - `src/openstat/main.py`: OpenStat workflow dispatcher.
- `src/formatter/`: CSV shaping/writers.
- `src/services/`: config, checkpoints, logging, PRiSM/OpenSTAT processing (`prism.py`, `openstat_cpt.py`).
- `src/utils/`: canonical shared helpers (`net`, `url_id`, `text_chunk`, `cpt`, `jsonl`).
- `src/indexing/`: yield CSV indexer (`yield_indexer.py`), OpenSTAT price indexer (`price_indexer.py`), and unified RAG corpus indexer (`corpus_rag_indexer.py`, manifest in `corpus_manifest.py`).
- OpenStat `agri_corpus/` re-exports `chunk_text`, `make_cpt_record`, `safe_id_from_url` from `src/utils/`; site-specific PDF/txt helpers stay there.
- `docs/migration/`: OpenStat migration runbooks, acceptance matrix, and rollback manifest.
- `tests/`: unit tests.
- `data/`: runtime outputs/checkpoints.

## Standard Commands
- Install core deps: `uv sync`
- Install orchestrator deps: `uv sync --extra orchestrator` (add `--extra api` for `prism_index`, `openstat_index`, `corpus_rag_index`)
- Install browser deps: `uv sync --extra browser`
- Install Scrapling fetchers: `uv run scrapling install`
- Run app: `uv run python main.py`
- Run OpenStat compatibility workflows: `uv run python main.py openstat`
- Run scheduled jobs: `uv run python -m src.orchestrator run <job_id>` | `run --all` | `run --due` | `serve`
- Test alerts: `uv run python -m src.orchestrator test-alerts` (Telegram/Discord from `.env`)
- Run artifacts: `data/runs/<run_id>/manifest.json` + `validation_report.json`; logs: `data/logs/orchestrator.jsonl`
- After monthly yield export, `prism_index` refreshes Qdrant for the API (or `python main.py index`)
- After monthly scrapes, `corpus_rag_index` indexes five narrative JSONL corpora into `agri_corpus_rag` (or `python -m src.indexing.corpus_rag_indexer`). OpenSTAT outputs `openstat_table.csv` indexed via `openstat_index` into `openstat_price_records` / `openstat_price_knowledge` (not RAG).
- OpenSTAT price API: `GET /v1/prices`, `POST /v1/prices/search` (after `openstat_index`)
- Corpus RAG search: `POST /v1/corpus/search` (yield search stays on `/v1/knowledge/search`)
- Scheduler + API stack: `docs/SCHEDULER_SETUP.md` (cron, Task Scheduler, browser lock, FlareSolverr, Qdrant)
- Run tests: `uv run python -m unittest discover -s tests -p "test_*.py" -v`
- Validate corpora: `uv run python -m src.scripts.validate_corpus` (see `docs/DATA_FORMAT_SPEC.md`)

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
- Unified RAG index collection: `agri_corpus_rag` (env `CORPUS_RAG_COLLECTION`, default `agri_corpus_rag`)
- OpenSTAT price collections: `openstat_price_records`, `openstat_price_knowledge` (env `QDRANT_PRICE_RECORDS_COLLECTION`, `QDRANT_PRICE_KNOWLEDGE_COLLECTION`)
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
- PhilRice default pipeline: `PHILRICE_STREAM_PROCESS=true` — download → process → append `philrice_corpus.jsonl` → delete PDF (`PHILRICE_DELETE_PDF_AFTER_CLEAN`, default on in stream mode). Batch mode: set `PHILRICE_STREAM_PROCESS=false`.
- PhilRice News, PinoyRice, IRRI: same stream pattern (`PHILRICE_NEWS_STREAM_PROCESS`, `PINOYRICE_STREAM_PROCESS`, `IRRI_STREAM_PROCESS`). Use `*_FRESH_CORPUS=true` once when resetting checkpoint/corpus; see `docs/SCHEDULER_SETUP.md`.
- Wasabi: per-job upload after successful runs; Qdrant snapshots after index jobs; restore with `uv run python -m src.storage.wasabi_restore` (`--list-dates`, `--reindex`, `--qdrant`).
- Prefer checkpoint-safe updates; avoid breaking resume behavior.
- Do not commit runtime artifacts from `data/` except tracked `.gitkeep` files.
- Keep `.env` examples mode-specific; avoid mixing conflicting job settings.
