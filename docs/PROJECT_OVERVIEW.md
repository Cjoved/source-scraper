# Source Scraper Project Overview

## Summary

Source Scraper is an agricultural data collection and retrieval system for PRiSM, OpenSTAT, PhilRice, PinoyRice, and IRRI sources. It collects structured crop/yield/price data and narrative agriculture content, validates the outputs, indexes searchable records into Qdrant, and exposes the data through a FastAPI service and an optional AI chat UI.

The project is designed for scheduled scraping, resumable jobs, data quality checks, API access, and farmer-facing data assistance.

## Main Goals

- Collect PRiSM yield data through HTTP export and browser scraping.
- Run OpenSTAT-compatible workflows for agricultural price and corpus sources.
- Build clean CSV/JSONL outputs for analytics, indexing, and retrieval.
- Index structured records and narrative corpora into Qdrant.
- Provide API endpoints for yield, price, and corpus search.
- Provide an AI agent that can answer questions using project data and sources.
- Send clear Telegram/Discord alerts when scheduled scraper jobs fail.

## Core Components

### Scraper Layer

The canonical PRiSM scraper lives in `src/scraper/`.

- `clients/` handles HTTP and browser calls.
- `parsers/` extracts data from pages or responses.
- `spiders/` runs scraping loops.
- `formatter/` shapes CSV and output files.

Supported PRiSM modes:

- Yield export CSV through the PRiSM HTTP API.
- Browser table scraping from PRiSM pages.
- Optional browser corpus output for narrative text.

### OpenSTAT Compatibility Layer

OpenSTAT-compatible workflows live in `src/openstat/`.

This layer handles:

- PhilRice publications.
- PhilRice News.
- PinoyRice.
- OpenSTAT price tables.
- IRRI content.

The OpenSTAT layer keeps site-specific scraping and processing logic separate while reusing shared utilities from `src/utils/`.

### Orchestrator

Scheduled jobs live in `src/orchestrator/` and are configured through `orchestrator.yaml`.

The orchestrator supports:

- Running one job by ID.
- Running all enabled jobs.
- Running due jobs based on cron schedules.
- Long-running scheduler mode.
- Browser job locking to avoid overlapping browser-heavy jobs.
- Preflight checks for FlareSolverr and Qdrant.
- Corpus validation after scrape jobs.
- Wasabi backup and Qdrant snapshot workflows.
- Telegram, Discord, and local-file alerts.

### API Service

The FastAPI service lives in `src/api/`.

Main API capabilities:

- Structured PRiSM yield queries.
- Yield summary endpoints.
- OpenSTAT price endpoints.
- Hybrid semantic search through Qdrant.
- Corpus RAG search over agricultural documents/news.
- AI agent chat endpoint at `/v1/agent/chat`.

The API is designed to be read-only for user-facing data access.

### Indexing

Indexing logic lives in `src/indexing/`.

Important indexers:

- `yield_indexer.py` indexes PRiSM yield records and yield knowledge.
- `price_indexer.py` indexes OpenSTAT price records and price knowledge.
- `corpus_rag_indexer.py` indexes narrative corpora into the unified RAG collection.

Default Qdrant collections:

- `prism_yield_records`
- `prism_yield_knowledge`
- `openstat_price_records`
- `openstat_price_knowledge`
- `agri_corpus_rag`

### AI Agent

The AI agent lives in `src/agent/`.

It provides:

- Chat and tasklist modes.
- LangChain-based model integration.
- Tool calling over read-only project data.
- Source-aware responses with citations and warnings.
- Query planning for vague farmer questions.
- Optional Chainlit demo UI.
- AI-assisted error explanations for failed scraper jobs.

Supported model providers:

- DeepSeek.
- Kimi/Moonshot.
- OpenAI-compatible providers such as OpenRouter.

### AI Error Explainer

When an orchestrator job fails, the AI Error Explainer can add a human-readable explanation to alerts.

It explains:

- What likely happened.
- Why the scraper or job failed.
- What the operator should check next.
- What command can be used to retry.

If AI is not configured, the system still generates a deterministic fallback explanation.

The explanation is stored in:

```text
data/runs/<run_id>/manifest.json
```

It also appears in:

- Telegram alerts.
- Discord alerts.
- Local alert JSON files.

## Data Flow

```text
Source websites / APIs
        |
        v
Scraper or OpenSTAT workflow
        |
        v
CSV / JSONL outputs under data/
        |
        v
Validation and run manifest
        |
        v
Qdrant indexing
        |
        v
FastAPI endpoints and AI agent tools
        |
        v
User-facing API, Chainlit UI, or downstream apps
```

## Important Outputs

```text
data/prism_processed/prism_yield_export.csv
data/prism_processed/prism_browser_tables.csv
data/prism_processed/prism_corpus.jsonl
data/openstat_processed/openstat_table.csv
data/runs/<run_id>/manifest.json
data/runs/<run_id>/validation_report.json
data/logs/orchestrator.jsonl
data/alerts/
```

Runtime outputs under `data/` are not intended for normal commits.

## Common Commands

Install core dependencies:

```bash
uv sync
```

Install API and agent dependencies:

```bash
uv sync --extra api --extra agent
```

Install orchestrator dependencies:

```bash
uv sync --extra orchestrator
```

Install browser/OpenSTAT dependencies:

```bash
uv sync --extra browser --extra openstat
uv run scrapling install
uv run playwright install
```

Run the app:

```bash
uv run python main.py
```

Run OpenSTAT workflows:

```bash
uv run python main.py openstat
```

Start the API:

```bash
uv run python main.py api --reload --port 8000
```

Run scheduled jobs:

```bash
uv run python -m src.orchestrator list
uv run python -m src.orchestrator run philrice
uv run python -m src.orchestrator run --all
uv run python -m src.orchestrator run --due
uv run python -m src.orchestrator serve
```

Send a test alert:

```bash
uv run python -m src.orchestrator test-alerts
```

Run tests:

```bash
uv run python -m unittest discover -s tests -p "test_*.py" -v
```

## Environment Notes

Common `.env` settings include:

```env
PRISM_JOB=export_yield_csv
AGENT_ENABLED=true
AGENT_PROVIDER=deepseek
AGENT_API_KEY=your_key_here
AGENT_MODEL=deepseek-chat
QDRANT_URL=http://localhost:6333
ALERT_ENABLED=true
```

Do not commit real `.env` files or secrets.

## Optional UI

The optional demo UI uses Chainlit.

Relevant files:

```text
src/agent/ui_chainlit.py
src/agent/ui_helpers.py
.chainlit/config.toml
chainlit.md
public/agent.css
public/theme.json
public/AgriAgent.svg
```

The UI is intended for demo and farmer-facing interaction. The API remains the source of truth.

## Next Plan / Plan Of Action

### 1. Deployment Readiness

Prepare the project for stable production-style deployment.

- Finalize `.env` profiles for local, staging, and production.
- Run the API behind a process manager or container runtime.
- Run Qdrant as a persistent service with volume backups.
- Run FlareSolverr and browser dependencies only on workers that need browser scraping.
- Configure scheduled jobs through Windows Task Scheduler, cron, or `src.orchestrator serve`.
- Enable Telegram/Discord alerts for failed jobs, warnings, and optional success notifications.
- Validate Wasabi backup and Qdrant snapshot restore flow.
- Add a deployment checklist for API, scheduler, Qdrant, FlareSolverr, and alert credentials.

Recommended deployment units:

- Docker stack: API service on port `8000` plus an optional scheduler profile for scraper/orchestrator automation.
- Qdrant service: external persistent vector database, reached through `QDRANT_URL` or `DOCKER_QDRANT_URL`.
- FlareSolverr/browser worker: compose-managed helper for protected/browser-heavy scraper flows, not required by the API service.
- Optional Chainlit UI: demo/chat frontend on a separate port such as `8001`, outside the Docker stack.

### 2. Production Monitoring

Improve observability before exposing the system to real users.

- Keep `data/runs/<run_id>/manifest.json` as the primary run artifact.
- Use `data/logs/orchestrator.jsonl` for structured job logs.
- Send failed job alerts to Telegram and Discord.
- Include AI Error Explainer output in alerts for faster troubleshooting.
- Track validation failures separately from scraper crashes.
- Add a regular restore test for Wasabi and Qdrant snapshots.
- Add a lightweight health dashboard for API, Qdrant, scheduler, latest run status, and alert status.

### 3. WebGIS Integration

Expose the collected and indexed data to a WebGIS application.

Possible integration approach:

- Use the FastAPI service as the backend data API.
- Add WebGIS-friendly endpoints for map filters such as region, province, municipality, crop, year, semester, and commodity.
- Return GeoJSON-compatible responses for map layers when geometry is available.
- Join PRiSM yield records with administrative boundary data for choropleth maps.
- Expose OpenSTAT price data as province/region-level map overlays.
- Add time-series endpoints for charts beside the map.
- Add source metadata so each map popup can show where the data came from.
- Keep heavy RAG/corpus search separate from map layer endpoints to keep WebGIS fast.

Suggested WebGIS features:

- Yield map by province/municipality.
- Price trend overlay by commodity and market area.
- Search panel for PhilRice, IRRI, PinoyRice, and OpenSTAT corpus content.
- Map popup with yield/price summary and source links.
- AI question box that can answer map-aware questions using selected location context.

Example future API shape:

```text
GET /v1/map/yield?province=Laguna&year=2024
GET /v1/map/prices?commodity=palay&region=CALABARZON
GET /v1/map/corpus/search?q=rice+disease&source_id=irri
POST /v1/agent/chat
```

### 4. Digisaka Integration

Use Source Scraper as a data and intelligence backend for Digisaka.

Possible Digisaka integration points:

- Farmer-facing chat assistant for palay yield, price, news, and advisory questions.
- Price lookup for commodities using OpenSTAT indexed records.
- Location-aware yield summaries using PRiSM data.
- News and advisory search from PhilRice, IRRI, PinoyRice, and related corpora.
- Admin dashboard for latest scraper runs, failed jobs, and data freshness.
- Push or in-app notifications when important agriculture updates are scraped.
- WebGIS map layers embedded into Digisaka dashboards.

Recommended integration pattern:

- Digisaka frontend calls Source Scraper API endpoints.
- Digisaka backend stores user profiles, permissions, and app-specific workflows.
- Source Scraper remains responsible for scraping, validation, indexing, and source-aware answers.
- AI responses should return sources, warnings, confidence, and tool traces so Digisaka can display trustworthy answers.

Farmer-facing experience:

- User asks a simple question in Tagalog, Cebuano, or Taglish.
- The agent normalizes crop, place, year, and intent.
- The system chooses the right data tool: yield, price, news, or corpus search.
- The answer includes plain-language explanation plus source references.
- If the question is vague, the system asks a short clarification instead of guessing too much.

### 5. Data Quality And Governance

Before full production use, strengthen data quality controls.

- Define freshness targets per source.
- Track last successful scrape per job.
- Add data completeness checks for required fields.
- Add duplicate and empty-record thresholds.
- Version released datasets under `data/releases/`.
- Document source limitations and acceptable use.
- Keep source URLs, filenames, and scrape timestamps in outputs.
- Add manual review flow for suspicious or low-confidence AI answers.

### 6. Security And Access Control

Harden the system before external exposure.

- Keep API keys and model keys only in `.env` or secret manager.
- Use public/admin API key scopes already supported by the API.
- Put the API behind HTTPS in staging/production.
- Rate-limit public endpoints.
- Avoid exposing raw stack traces to end users.
- Keep detailed errors in manifests and alerts for operators only.
- Make AI tools read-only unless future admin tools are explicitly designed and reviewed.

### 7. Suggested Milestones

Recommended next milestones:

- Milestone 1: stabilize API, scheduler, Qdrant, alerts, and backup on one deployment host.
- Milestone 2: deploy Chainlit demo UI for internal testing and farmer-facing demos.
- Milestone 3: add WebGIS-ready map endpoints and boundary joins.
- Milestone 4: connect Digisaka frontend/backend to Source Scraper APIs.
- Milestone 5: add production dashboard for data freshness, job health, and alert history.
- Milestone 6: run pilot testing with real farmer-style questions and update prompts/tools based on findings.

## Commit Guidance

Include source code, tests, and documentation that are part of the feature being pushed.

Avoid committing:

- Runtime outputs under `data/`.
- Local `.env` files.
- Chainlit generated translation files under `.chainlit/translations/`.
- Temporary automation notes unless they are intentionally part of the change.

## Recommended Reading

- `README.md` for install and run instructions.
- `docs/api.md` for API endpoint details.
- `docs/AGENT_API.md` for AI agent usage.
- `docs/AGENT_UI.md` for Chainlit UI setup.
- `docs/SCHEDULER_SETUP.md` for scheduled jobs and alerts.
- `docs/DATA_FORMAT_SPEC.md` for corpus/output format requirements.
- `docs/project-structure.md` for folder ownership and layout.
