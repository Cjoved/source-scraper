# Source-Scraper Project Structure

This is the canonical folder guide to avoid confusion when adding files.

## Root

- `main.py` - Unified CLI entrypoint (`scrape`, `openstat`, `api`, `index`)
- `orchestrator.yaml` - Scheduled job definitions (cron, env overrides)
- `docker-compose.yml` - FlareSolverr + Qdrant for local OpenSTAT / API stack
- `pyproject.toml` / `uv.lock` - Dependency and lock management
- `.env` - Runtime configuration (local only; do not commit secrets)

## Source Code

- `src/scraper/` - Canonical PRiSM implementation
  - `clients/` - network/browser clients
  - `parsers/` - extractors/parsers
  - `spiders/` - orchestration runners
- `src/openstat/` - OpenStat compatibility implementation
  - `main.py` - OpenStat workflow dispatch
  - `env_flags.py` - workflow `.env` toggles (PHILRICE, OPENSTAT, etc.)
  - `scrapers/` - OpenStat crawler flows
  - `services/` - OpenStat processing flows
  - `agri_corpus/` - re-exports + PDF/txt CPT helpers (`txt_cpt.py`, `pdf_utils.py`)
  - `utils/` - Playwright wait helpers + re-exported network checks from `src/utils/net.py`
- `src/orchestrator/` - scheduled runs (`python -m src.orchestrator`; loads `orchestrator.yaml`)
  - `lock.py` - browser job overlap lock (`data/checkpoints/orchestrator_browser.lock`)
  - `preflight.py` - FlareSolverr + Qdrant health checks before OpenSTAT / prism_index
  - `serve.py` - APScheduler long-running `run --due` poller
- `src/services/` - shared service-layer logic (`config.py`, `checkpoint.py`, `prism.py`, `openstat_cpt.py`)
- `src/formatter/` - CSV and output formatting
- `src/api/` - FastAPI HTTP API
- `src/indexing/` - CSV-to-Qdrant indexing
- `src/storage/` - persistence adapters
- `src/models/` - data models
- `src/utils/` - canonical shared helpers
  - `net.py` - internet availability / `require_internet`
  - `url_id.py` - `safe_id_from_url`
  - `text_chunk.py` - `chunk_text`
  - `cpt.py` - `make_cpt_record`
  - `jsonl.py` - `append_jsonl`

## Documentation

- `docs/api.md` - API guide
- `docs/deploy.md` - deployment plan
- `docs/SCHEDULER_SETUP.md` - orchestrator cron / Task Scheduler / serve setup
- `docs/migration/` - OpenStat migration artifacts
- `docs/project-structure.md` - this structure guide

## Runtime Data (not for commits)

- `data/checkpoints/`
- `data/prism_processed/`
- `data/openstat_processed/` — OpenSTAT table CSV + `openstat_corpus.jsonl`
- `data/philrice_processed/`, `data/pinoyrice_processed/`, `data/philrice_news_processed/`, `data/irri_processed/`
- `data/manual_downloads/` — manual OpenSTAT Excel fallback
- other `data/*` outputs from scraper workflows

