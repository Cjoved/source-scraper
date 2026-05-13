# PRiSM API (v1)

Versioned HTTP API on top of the scraped PRiSM yield CSV, backed by Qdrant.
All endpoints live under `/v1/`. Response shapes are stable per endpoint —
each route has a single responsibility.

## Quick Start

```bash
# 1. Install API deps
uv sync --extra api

# 2. Run Qdrant locally (Docker)
docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant

# 3. Index the yield CSV into Qdrant
uv run python main.py index --collections all

# 4. Start the API (either of these works)
uv run python main.py api --reload --port 8000
uv run uvicorn main:app --reload --port 8000
```

OpenAPI docs (when `API_DOCS_ENABLED=true`):

- Swagger: <http://localhost:8000/v1/docs>
- ReDoc:   <http://localhost:8000/v1/redoc>
- JSON:    <http://localhost:8000/v1/openapi.json>

## Configuration

All variables are loaded once at startup via `pydantic-settings`. Defaults
work for local development.

| Variable | Default | Description |
| --- | --- | --- |
| `API_TITLE` | `PRiSM API` | OpenAPI title |
| `API_VERSION` | `1.0.0` | OpenAPI version label |
| `API_DOCS_ENABLED` | `true` | Toggle `/v1/docs`, `/v1/redoc`, `/v1/openapi.json` |
| `API_LOG_LEVEL` | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `API_LOG_JSON` | `true` | JSON logs in production; `false` for human-readable dev logs |
| `API_CORS_ORIGINS` | `""` | Comma-separated list; empty disables CORS |
| `API_KEYS_PUBLIC` | `""` | Comma-separated public-tier API keys |
| `API_KEYS_ADMIN` | `""` | Comma-separated admin-tier API keys |
| `API_AUTH_DISABLED` | `false` | Bypass auth for local dev/tests |
| `RATE_LIMIT_READ` | `120/minute` | List, metadata, summary, status |
| `RATE_LIMIT_SEARCH` | `30/minute` | Knowledge search |
| `RATE_LIMIT_EXPORT` | `5/minute` | Bulk export |
| `EXPORT_MAX_ROWS` | `100000` | Hard cap on export rows |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant endpoint |
| `QDRANT_API_KEY` | unset | API key for hosted Qdrant |
| `QDRANT_TIMEOUT_SECONDS` | `30` | Per-request timeout |
| `QDRANT_RECORDS_COLLECTION` | `prism_yield_records` | Structured collection name |
| `QDRANT_KNOWLEDGE_COLLECTION` | `prism_yield_knowledge` | Hybrid collection name |
| `EMBEDDING_DENSE_MODEL` | `BAAI/bge-small-en-v1.5` | FastEmbed dense model |
| `EMBEDDING_SPARSE_MODEL` | `Qdrant/bm25` | FastEmbed sparse model |
| `CSV_SOURCE_RELPATH` | `prism_processed/prism_yield_export.csv` | Source under `data/` |

## Auth

API keys are sent in the `X-API-Key` header. There are two tiers:

- `public` — read endpoints (list, metadata, summary, knowledge search).
- `admin`  — export and index admin endpoints.

Set the keys via `API_KEYS_PUBLIC` and `API_KEYS_ADMIN`. For local development
or tests, set `API_AUTH_DISABLED=true` to bypass.

## Errors

All non-2xx responses use this envelope:

```json
{
  "error": {
    "code": "INVALID_FILTER",
    "message": "...",
    "details": { "field": "year", "value": 2030 }
  }
}
```

Common codes: `VALIDATION_ERROR`, `INVALID_FILTER`, `UNAUTHORIZED`,
`FORBIDDEN`, `RATE_LIMITED`, `QDRANT_UNAVAILABLE`, `INTERNAL_ERROR`.

## Endpoints

### `GET /v1/health` — public
Liveness and Qdrant connectivity. Returns `503` with `Retry-After: 30` when
Qdrant is unreachable.

```bash
curl -H "X-API-Key: $KEY" http://localhost:8000/v1/health
```

### `GET /v1/yield` — public
Paginated structured listing. Supports `year`, `semester`, `region`,
`province`, `municipality`, `min_yield`, `max_yield`, `limit`, `offset`.

```bash
curl -H "X-API-Key: $KEY" \
  "http://localhost:8000/v1/yield?region=CAR&year=2019&limit=10"
```

### `GET /v1/yield/metadata` — public
Distinct values for UI dropdowns; served from in-memory cache.

```bash
curl -H "X-API-Key: $KEY" http://localhost:8000/v1/yield/metadata
```

### `GET /v1/yield/summary` — public
Deterministic aggregation. Returns overall stats, plus by-year and by-semester
breakdowns. CSV-mtime-keyed cache.

```bash
curl -H "X-API-Key: $KEY" \
  "http://localhost:8000/v1/yield/summary?province=Abra&year_min=2019&year_max=2025"
```

### `GET /v1/yield/export` — admin
Bulk dump as a stream. `format=ndjson` (default) or `format=csv`. Same filter
params as `/v1/yield`.

```bash
curl -H "X-API-Key: $ADMIN_KEY" \
  "http://localhost:8000/v1/yield/export?format=ndjson&region=CAR" > car.ndjson

curl -H "X-API-Key: $ADMIN_KEY" \
  "http://localhost:8000/v1/yield/export?format=csv" > prism_yield.csv
```

### `POST /v1/knowledge/search` — public
Hybrid semantic search (dense + sparse, fused with RRF). Pure retrieval —
no internal routing to summary/list behaviors.

```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"query":"Bangued Abra 2018 first sem","limit":5,"min_score":0.3}' \
  http://localhost:8000/v1/knowledge/search
```

### `GET /v1/index/status` — admin
Per-collection counts, schema version, source file mtime, source row count.

```bash
curl -H "X-API-Key: $ADMIN_KEY" http://localhost:8000/v1/index/status
```

### `POST /v1/index/refresh-metadata` — admin
Rebuild the in-memory metadata cache after a re-index.

```bash
curl -X POST -H "X-API-Key: $ADMIN_KEY" \
  http://localhost:8000/v1/index/refresh-metadata
```

## Indexing CLI

```bash
uv run python -m src.indexing.cli --help
uv run python -m src.indexing.cli --collections all
uv run python -m src.indexing.cli --collections structured
uv run python -m src.indexing.cli --collections knowledge
uv run python -m src.indexing.cli --source path/to/custom.csv --batch-size 128
```

The indexer is idempotent: row identity is a stable hash of
`year|semester_code|region|province|municipality`.

## Eval

A small natural-language eval set lives in
[`tests/eval/yield_queries.jsonl`](../tests/eval/yield_queries.jsonl). Run
against a live API to inspect retrieval quality after textifier/embedding
changes:

```bash
uv run python -m tests.eval.run_eval --base-url http://localhost:8000
```

## Module Layout

```
src/
  api/
    app.py              FastAPI factory; lifespan loads metadata cache.
    settings.py         Pydantic-settings; env validated once at startup.
    errors.py           ApiError, ErrorCode, error handlers.
    deps.py             FastAPI `Depends` providers.
    auth.py             X-API-Key middleware + public/admin scopes.
    rate_limit.py       slowapi limiter + handler.
    logging.py          structlog + request-id middleware.
    schemas.py          Pydantic v2 request/response models.
    metadata_cache.py   In-memory snapshot; atomic refresh.
    routes/             health, yield_data, knowledge, admin.
  services/
    aggregation.py      Pure aggregation over normalized rows.
    filters.py          Builds YieldFilter from API params.
    textify.py          row_to_passage(row) -> str.
  storage/
    qdrant_store.py     QdrantStoreProtocol + concrete impl.
  indexing/
    yield_indexer.py    One CSV pass, writes to both collections.
    cli.py              `python -m src.indexing.cli ...`
```
