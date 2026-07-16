# Production Environment Guide

Beginner-friendly explanation of **every env var that matters in production**.

> **How to use this file**  
> 1. Read each section.  
> 2. Copy values into `.env.shared`, `.env.api`, and `.env.scheduler` (or one `.env` for a first deploy).  
> 3. Replace every `replace-with-*` with a real secret (`openssl rand -hex 32`).  
> 4. Never commit real `.env` files to Git.

See also: [`.env.example`](../.env.example) (machine-readable template).

---

## Big picture (3 boxes)

```
.env.shared     → Qdrant + shared paths (API + scheduler both need this)
.env.api        → API keys, docs, agent LLM, JWT
.env.scheduler  → Scrapers, FlareSolverr, Wasabi, alerts
```

| Box | What it powers |
|-----|----------------|
| **Shared** | Connection to the vector database |
| **API** | HTTP `/v1/*` + AI agent chat (+ Chainlit UI vars if `--profile ui`) |
| **Scheduler** | Auto scrapes + backups + failure alerts |

Your **local** `.env` can stay for laptop scraping.  
**Production** on Hostinger should use the split above (see `docker-compose.prod.yml`).

---

## Must set vs optional

| Priority | Meaning |
|----------|---------|
| **MUST** | Production will be insecure or will fail without this |
| **RECOMMENDED** | Strongly wanted for real ops |
| **OPTIONAL** | Defaults are fine; change only when needed |

---

# Part 1 — `.env.shared`

## Runtime

### `APP_ENV` — **MUST**
- **What:** Profile name: `production` / `development` / `test`
- **Production:** `production`
- **Why:** Stops dangerous settings like auth disabled from being allowed by accident

### `ALLOW_AUTH_DISABLED` — **MUST**
- **What:** Emergency switch to allow `API_AUTH_DISABLED=true` outside local/dev
- **Production:** `false`
- **Why:** Never open the API without keys on a public server

---

## Qdrant (vector database)

### `QDRANT_URL` — **MUST**
- **What:** Where the API/indexer talks to Qdrant
- **Production (same VPS):** `http://127.0.0.1:6333`
- **Docker network:** often set via compose as `http://qdrant-vector-db:6333`
- **Why:** Without this, search/index cannot reach the DB

### `QDRANT_API_KEY` — **MUST**
- **What:** Password for Qdrant
- **Production:** Same key as the Qdrant Docker server `.env`
- **Why:** Qdrant rejects requests without the matching key

### `QDRANT_TIMEOUT_SECONDS` — OPTIONAL
- **What:** How long to wait for Qdrant answers
- **Default:** `30` (local often uses higher, e.g. `180`)
- **Production tip:** `30`–`120` is fine

### `QDRANT_LOCAL_INFERENCE_BATCH_SIZE` — OPTIONAL
- **What:** Embedding batch size on the machine running index/API
- **Default:** `256`

### `DOCKER_QDRANT_URL` — OPTIONAL (compose only)
- **What:** Host-side helper; compose copies this into container `QDRANT_URL`
- **Example:** `http://qdrant-vector-db:6333`
- **Not read by Python directly**

---

## Collection names (OPTIONAL — defaults work)

| Variable | Default | Meaning |
|----------|---------|---------|
| `QDRANT_RECORDS_COLLECTION` | `prism_yield_records` | Yield table data |
| `QDRANT_KNOWLEDGE_COLLECTION` | `prism_yield_knowledge` | Yield semantic search |
| `QDRANT_PRICE_RECORDS_COLLECTION` | `openstat_price_records` | Price table data |
| `QDRANT_PRICE_KNOWLEDGE_COLLECTION` | `openstat_price_knowledge` | Price semantic search |
| `CORPUS_RAG_COLLECTION` | `agri_corpus_rag` | Articles / PDFs / news |

Change only if you renamed collections on purpose.

---

## Embeddings / search (OPTIONAL — defaults work)

| Variable | Default | Meaning |
|----------|---------|---------|
| `EMBEDDING_DENSE_MODEL` | `BAAI/bge-small-en-v1.5` | Vector model for meaning search |
| `EMBEDDING_SPARSE_MODEL` | `Qdrant/bm25` | Keyword-style search |
| `EMBEDDING_DENSE_SIZE` | `384` | Vector size (must match model) |
| `HYBRID_PREFETCH_MULTIPLIER` | `4` | Search prefetch tuning |
| `HYBRID_FUSION` | `rrf` | How dense+sparse results merge |

---

## Data file paths (OPTIONAL)

| Variable | Default | Meaning |
|----------|---------|---------|
| `SCHEMA_VERSION` | `v1` | Tag written into indexed payloads |
| `CSV_SOURCE_RELPATH` | `prism_processed/prism_yield_export.csv` | Yield CSV for indexer |
| `OPENSTAT_CSV_SOURCE_RELPATH` | `openstat_processed/openstat_table.csv` | Prices CSV for indexer |

Paths are relative to the project `data/` folder.

---

# Part 2 — `.env.api`

## Authentication — **MUST**

### `API_AUTH_DISABLED`
- **Production:** `false`
- **Meaning:** If `true`, anyone can call the API as admin (dangerous)

### `API_KEYS_PUBLIC`
- **What:** Keys for normal read access (`/v1/yield`, search, prices, corpus…)
- **Format:** comma-separated
- **Who gets this:** Other VPS / apps that only need to read data

### `API_KEYS_ADMIN`
- **What:** Keys for sensitive ops (export, index status, refresh metadata)
- **Who gets this:** You / operators only — **never** give to the other VPS casually

### `API_KEYS_AGENT`
- **What:** Key allowed to call `/v1/agent/chat`
- **Important rule from code:** the agent key must **also** be listed in `API_KEYS_PUBLIC`  
  (or you use an admin key for agent)
- **Example:**
  ```env
  API_KEYS_PUBLIC=pub_aaa,agent_bbb
  API_KEYS_AGENT=agent_bbb
  API_KEYS_ADMIN=adm_ccc
  ```

### `AGENT_ALLOW_PUBLIC`
- **Production:** `false`
- **Meaning:** If `true`, a normal public key can use the agent (LLM cost risk)

---

## API ops

### `API_DOCS_ENABLED` — **MUST**
- **Production:** `false`
- **Meaning:** Hides `/v1/docs` and OpenAPI from the internet

### `API_LOG_JSON` — RECOMMENDED
- **Production:** `true`
- **Meaning:** Machine-readable logs

### `API_LOG_LEVEL` — OPTIONAL
- **Default:** `INFO`  
- Use `WARNING` if logs are too noisy

### `API_TITLE` / `API_VERSION` — OPTIONAL
- Display names for the API

### `API_CORS_ORIGINS` — OPTIONAL
- **Leave empty** if only servers call the API (other VPS = server-to-server)
- Set only if a **browser** frontend calls the API  
  Example: `https://app.yourcompany.com`

---

## Rate limits — OPTIONAL (defaults are good)

| Variable | Default | Protects |
|----------|---------|----------|
| `RATE_LIMIT_READ` | `120/minute` | List endpoints |
| `RATE_LIMIT_SEARCH` | `30/minute` | Search |
| `RATE_LIMIT_EXPORT` | `5/minute` | Big CSV exports |
| `RATE_LIMIT_HEALTH` | `60/minute` | Health checks |
| `RATE_LIMIT_AGENT` | `10/minute` | Agent / LLM cost |

Also optional:
- `EXPORT_MAX_ROWS` (default `100000`)
- `SUMMARY_CACHE_SIZE` (default `256`)
- `DEFAULT_SEARCH_LIMIT` (default `10`)
- `DEFAULT_MIN_SCORE` (default `0.0`)

---

## Agent (LLM) — **MUST if agent is ON**

### `AGENT_ENABLED`
- `true` = `/v1/agent/chat` works  
- `false` = agent off (safer if you only need data API)

### `AGENT_PROVIDER`
- Allowed: `deepseek`, `kimi`, `openai_compatible`

### `AGENT_API_KEY`
- Your LLM vendor key (DeepSeek / Kimi / OpenRouter…)  
- **Different** from `API_KEYS_AGENT`  
  - `API_KEYS_AGENT` = who may call *your* API  
  - `AGENT_API_KEY` = key *your* API uses to call the LLM

### `AGENT_MODEL`
- Example: `deepseek-chat` or `deepseek-reasoner`

### `AGENT_BASE_URL` — OPTIONAL
- Custom base URL; DeepSeek often works without it  
- Required for some OpenAI-compatible providers

### `AGENT_TIMEOUT_SECONDS` — OPTIONAL (default `60`)
### `AGENT_MAX_TOOL_CALLS` — OPTIONAL (default `4`, max `8`)
### `AGENT_DEFAULT_MODE` — OPTIONAL (`tasklist` or `chat`)
### `AGENT_SUMMARIZE_MAX_ROWS` — OPTIONAL (default `10000`)

---

## JWT — OPTIONAL (leave off unless you use it)

| Variable | Production default |
|----------|--------------------|
| `JWT_AUTH_ENABLED` | `false` |
| `JWT_REQUIRED_FOR_AGENT` | `false` |
| `JWT_SECRET` | empty unless JWT on |
| `JWT_ALGORITHM` | `HS256` |
| `JWT_ISSUER` / `JWT_AUDIENCE` | empty unless JWT on |

---

## Chainlit UI — OPTIONAL (verify / staging)

Put these in **`.env.api`** (same box as API keys). Chainlit is **not** required for API-only Hostinger deploy; use it to **test/verify** the agent after Qdrant + index.

### When to turn it on
- Local or Hostinger **verify**: `docker compose --profile ui …`
- Skip for first public API ship if you only need `/v1/*`
- Do **not** open port `8001` to the public internet without Chainlit password/OAuth

### `AGENT_UI_API_URL` — RECOMMENDED when using UI
- **What:** Full URL Chainlit POSTs to (`/v1/agent/chat`)
- **Local process:** `http://127.0.0.1:8000/v1/agent/chat`
- **Docker compose:** leave unset — default is `http://api:8000/v1/agent/chat` (container → `api` service)
- **Wrong:** bare `http://127.0.0.1:8000` (missing `/v1/agent/chat`)

### `AGENT_UI_API_KEY` — **MUST when API auth is on**
- **What:** Sent as `X-API-Key` from Chainlit → API
- **Production / Hostinger:** set to the same value as one entry in `API_KEYS_AGENT` (and that key must also be in `API_KEYS_PUBLIC`)
- **Local with `API_AUTH_DISABLED=true`:** can leave empty

### `AGENT_UI_TIMEOUT_SECONDS` — OPTIONAL
- **Default:** `90` (code) / often `60` in examples
- Raise if agent + Qdrant summaries are slow over SSH tunnel

### Docker commands (Hostinger / local)

```bash
# Local (Qdrant on host or tunnel)
docker compose --profile ui up -d --build

# Deploy compose + UI
docker compose -f docker-compose.deploy.yml --profile ui up -d --build

# Prod-shaped: Chainlit ONLY on 127.0.0.1:8001
docker compose -f docker-compose.deploy.yml -f docker-compose.prod.yml --profile ui up -d --build
```

| Piece | Value |
|-------|--------|
| UI URL | `http://127.0.0.1:8001` |
| Prod bind | `127.0.0.1:8001` (SSH tunnel from laptop) |
| API inside Docker | `http://api:8000` |
| Image | same Dockerfile; includes `--extra ui` (Chainlit) |

### Example block for `.env.api`

```env
# Chainlit verify UI (docker --profile ui)
AGENT_UI_API_URL=http://api:8000/v1/agent/chat
AGENT_UI_API_KEY=agent_...   # same as API_KEYS_AGENT entry
AGENT_UI_TIMEOUT_SECONDS=90
```

See also: [`docs/AGENT_UI.md`](AGENT_UI.md).

---

# Part 3 — `.env.scheduler`

## FlareSolverr / browser

### `FLARESOLVERR_URL` — **MUST for OpenSTAT**
- Docker: `http://flaresolverr:8191`
- Local: `http://127.0.0.1:8191`

### `HEADLESS` — RECOMMENDED
- `true` on servers (no visible browser window)
- PinoyRice uses **`HEADLESS` only** (there is no working `PINOYRICE_HEADLESS`)

### Per-site headless (OPTIONAL)
`PRISM_HEADLESS`, `PHILRICE_HEADLESS`, `PHILRICE_NEWS_HEADLESS`, `IRRI_HEADLESS`, `OPENSTAT_HEADLESS`

### `URL_ALLOW_PRIVATE_TARGETS` — **MUST stay false**
- **Production:** `false`  
- Prevents SSRF-style private network scraping

---

## Workflow flags (OPTIONAL — orchestrator usually overrides)

| Variable | Default in docs | Meaning |
|----------|-----------------|---------|
| `PHILRICE` | `false` | PhilRice PDF job |
| `PHILRICE_NEWS` | `false` | News job |
| `PINOYRICE` | `false` | PinoyRice job |
| `OPENSTAT` | `true` | OpenSTAT prices |
| `IRRI` | `false` | IRRI job |
| `PRISM` | `false` | PRiSM job |

`orchestrator.yaml` sets these per scheduled job — you often don’t need to set them in prod env.

---

## Orchestrator logging / validation — OPTIONAL

| Variable | Default | Meaning |
|----------|---------|---------|
| `ORCHESTRATOR_LOG_DIR` | `data/logs` | Log folder |
| `ORCHESTRATOR_LOG_JSON` | `true` | JSON logs |
| `ORCHESTRATOR_LOG_LEVEL` | `INFO` | Log level |
| `ORCHESTRATOR_VALIDATE_QUALITY` | `true` | Corpus quality checks |
| `VALIDATE_MIN_TEXT_CHARS` | `100` | Min text length |
| `VALIDATE_MAX_EMPTY_LINE_PCT` | `5` | Empty-line threshold |

---

## Scraper tuning (OPTIONAL)

Defaults in code are usually enough. Common ones:

### PhilRice / News / PinoyRice / IRRI
- `*_STREAM_PROCESS=true` — download → process → delete (good for VPS disk)
- `*_FRESH_CORPUS=true` — **one-time reset only**; don’t leave on forever
- delay / retry / chunk settings — only if scrapes fail or are too aggressive

### OpenSTAT
| Variable | Notes |
|----------|--------|
| `OPENSTAT_URLS` | Comma-separated URL list (**this name**, not `URLS`) |
| `RESUME_CHECKPOINT` | `false` on monthly full refresh (orchestrator default behavior) |
| `OPENSTAT_MAX_YEARS_PER_BATCH` | Default `4` |
| `OPENSTAT_WRITE_LINE_CORPUS` | Default `false` |

### PRiSM yield export
| Variable | Notes |
|----------|--------|
| `PRISM_JOB` | e.g. `export_yield_csv` |
| `PRISM_EXPORT_YEAR_MIN` / `MAX` | Year range |
| `PRISM_EXPORT_*` delay/retries/cooldown | Politeness to the API |

---

## Wasabi backups — RECOMMENDED in production

| Variable | Meaning |
|----------|---------|
| `WASABI_ENABLED` | `true` to turn backups on |
| `WASABI_ACCESS_KEY` / `WASABI_SECRET_KEY` | Credentials |
| `WASABI_BUCKET` | Bucket name |
| `WASABI_REGION` / `WASABI_ENDPOINT` | Wasabi region endpoint |
| `WASABI_CORPUS_PREFIX` | Where corpus files go |
| `WASABI_CHECKPOINT_PREFIX` | Where checkpoints go |
| `WASABI_QDRANT_PREFIX` | Where Qdrant snapshots go |
| `WASABI_DATED_RETENTION` | How many dated copies to keep |
| `WASABI_BACKUP_FAIL_JOB` | `true` = fail the job if upload fails |

If you are not ready for Wasabi yet: `WASABI_ENABLED=false`.

---

## Alerts — RECOMMENDED

| Variable | Meaning |
|----------|---------|
| `ALERT_ENABLED` | Master switch (**code default is `false`** — set `true` to enable) |
| `ALERT_LOCAL_FILE` | Write `data/alerts/...` on disk |
| `ALERT_INCLUDE_TRACEBACK` | **Production: `false`** (don’t leak stack traces to Discord/Telegram) |
| `ALERT_ON_SUCCESS` | **Production: `true`** — confirm jobs finished OK |
| `ALERT_ON_TIMEOUT` / `ALERT_ON_WARNING` | Optional extra pings (default off = less noise) |
| `ALERT_TELEGRAM_BOT_TOKEN` + `ALERT_TELEGRAM_CHAT_ID` | Telegram |
| `ALERT_DISCORD_WEBHOOK_URL` | Discord |
| `ALERT_NTFY_TOPIC` / `ALERT_NTFY_SERVER` | ntfy |
| `ALERT_WEBHOOK_URL` / `ALERT_SLACK_WEBHOOK_URL` | Generic / Slack |
| SMTP `ALERT_EMAIL_*` / `ALERT_SMTP_*` | Email alerts |

---

# Part 4 — Qdrant server file (separate!)

On Hostinger, next to `docker-compose.qdrant.yml`:

```env
QDRANT_API_KEY=same-key-as-app
```

Compose maps this to Qdrant’s `QDRANT__SERVICE__API_KEY`.  
**Do not confuse** this tiny file with the full app `.env`.

---

# Part 5 — Cheat sheet: who gets which key

| Secret | Put in | Give to |
|--------|--------|---------|
| `API_KEYS_PUBLIC` | `.env.api` | Other VPS / read-only apps |
| `API_KEYS_AGENT` | `.env.api` | Agent clients only |
| `AGENT_UI_API_KEY` | `.env.api` | Chainlit container only (same as an agent key) |
| `API_KEYS_ADMIN` | `.env.api` | You / ops only |
| `AGENT_API_KEY` | `.env.api` | Nobody else (LLM vendor key) |
| `QDRANT_API_KEY` | shared + Qdrant server | Never the other VPS |
| Wasabi keys | `.env.scheduler` | Nobody else |
| Telegram / Discord | `.env.scheduler` | Nobody else |

```
Other VPS  →  HTTPS API  →  uses PUBLIC key
                       ↘ never Qdrant
                       ↘ never ADMIN key (unless needed)
```

---

# Part 6 — Minimal production set (API + Agent + Scheduler)

Use this as the **smallest complete** prod starter.  
Still replace every `...` with real secrets. Full knob list = [`.env.example`](../.env.example).

For `docker-compose.prod.yml`, you can put **all of this in one file per role**, or start with one file copied three ways — just don’t put admin/LLM keys only in scheduler.

```env
# ========== RUNTIME (shared) ==========
APP_ENV=production
ALLOW_AUTH_DISABLED=false

# ========== QDRANT (shared + same key on Qdrant server .env) ==========
QDRANT_URL=http://127.0.0.1:6333
# If API/scheduler run in Docker on same host network:
# DOCKER_QDRANT_URL=http://qdrant-vector-db:6333
QDRANT_API_KEY=...
QDRANT_TIMEOUT_SECONDS=30

# Defaults OK — listed so you know they exist
QDRANT_RECORDS_COLLECTION=prism_yield_records
QDRANT_KNOWLEDGE_COLLECTION=prism_yield_knowledge
QDRANT_PRICE_RECORDS_COLLECTION=openstat_price_records
QDRANT_PRICE_KNOWLEDGE_COLLECTION=openstat_price_knowledge
CORPUS_RAG_COLLECTION=agri_corpus_rag
CSV_SOURCE_RELPATH=prism_processed/prism_yield_export.csv
OPENSTAT_CSV_SOURCE_RELPATH=openstat_processed/openstat_table.csv
EMBEDDING_DENSE_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_SPARSE_MODEL=Qdrant/bm25
EMBEDDING_DENSE_SIZE=384
HYBRID_FUSION=rrf
SCHEMA_VERSION=v1

# ========== API AUTH (.env.api) ==========
API_AUTH_DISABLED=false
API_DOCS_ENABLED=false
API_LOG_JSON=true
API_LOG_LEVEL=INFO
# Leave empty for server-to-server (other VPS). Set only for browser frontends:
# API_CORS_ORIGINS=https://your-frontend.example

# Agent key MUST also appear in API_KEYS_PUBLIC (see auth.py require_agent)
API_KEYS_PUBLIC=pub_...,agent_...
API_KEYS_ADMIN=adm_...
API_KEYS_AGENT=agent_...
AGENT_ALLOW_PUBLIC=false

RATE_LIMIT_READ=120/minute
RATE_LIMIT_SEARCH=30/minute
RATE_LIMIT_EXPORT=5/minute
RATE_LIMIT_HEALTH=60/minute
RATE_LIMIT_AGENT=10/minute
EXPORT_MAX_ROWS=100000

# ========== AGENT LLM (.env.api) ==========
# API_KEYS_AGENT = who may call YOUR /v1/agent/chat
# AGENT_API_KEY  = YOUR server calling DeepSeek/Kimi/etc.
AGENT_ENABLED=true
AGENT_ALLOW_PUBLIC=false
AGENT_PROVIDER=deepseek
AGENT_BASE_URL=
AGENT_API_KEY=...
AGENT_MODEL=deepseek-chat
AGENT_TIMEOUT_SECONDS=60
AGENT_MAX_TOOL_CALLS=4
AGENT_DEFAULT_MODE=tasklist
AGENT_SUMMARIZE_MAX_ROWS=10000

JWT_AUTH_ENABLED=false
JWT_REQUIRED_FOR_AGENT=false

# ========== CHAINLIT UI (.env.api) — only with --profile ui ==========
# AGENT_UI_API_URL=http://api:8000/v1/agent/chat
# AGENT_UI_API_KEY=agent_...
# AGENT_UI_TIMEOUT_SECONDS=90

# ========== SCHEDULER / BROWSER (.env.scheduler) ==========
FLARESOLVERR_URL=http://flaresolverr:8191
HEADLESS=true
PRISM_HEADLESS=true
PHILRICE_HEADLESS=true
PHILRICE_NEWS_HEADLESS=true
IRRI_HEADLESS=true
OPENSTAT_HEADLESS=true
URL_ALLOW_PRIVATE_TARGETS=false

PHILRICE_STREAM_PROCESS=true
PHILRICE_NEWS_STREAM_PROCESS=true
PINOYRICE_STREAM_PROCESS=true
IRRI_STREAM_PROCESS=true

ORCHESTRATOR_LOG_JSON=true
ORCHESTRATOR_LOG_LEVEL=INFO
ORCHESTRATOR_VALIDATE_QUALITY=true

# OpenSTAT URL list uses this name (NOT "URLS")
# OPENSTAT_URLS=https://...,https://...
RESUME_CHECKPOINT=false

# ========== WASABI (.env.scheduler) — ON for automated backups ==========
WASABI_ENABLED=true
WASABI_ACCESS_KEY=...
WASABI_SECRET_KEY=...
WASABI_BUCKET=agent-scraper
WASABI_REGION=ap-southeast-1
WASABI_ENDPOINT=https://s3.ap-southeast-1.wasabisys.com
WASABI_CORPUS_PREFIX=corpus-data/
WASABI_CHECKPOINT_PREFIX=Checkpoint/
WASABI_QDRANT_PREFIX=qdrant-data/
WASABI_DATED_RETENTION=2
WASABI_BACKUP_FAIL_JOB=true

# ========== ALERTS (.env.scheduler) — ON for automated ops ==========
ALERT_ENABLED=true
ALERT_LOCAL_FILE=true
ALERT_INCLUDE_TRACEBACK=false
ALERT_ON_TIMEOUT=false
ALERT_ON_SUCCESS=true
ALERT_ON_WARNING=false
ALERT_TELEGRAM_BOT_TOKEN=...
ALERT_TELEGRAM_CHAT_ID=...
ALERT_DISCORD_WEBHOOK_URL=...
```

### Also create on the Qdrant host (tiny file)

```env
QDRANT_API_KEY=...   # SAME value as above
```

### Required for your automatic production stack

| Piece | Env | Why |
|-------|-----|-----|
| Wasabi | `WASABI_ENABLED=true` + keys | Auto backup after scrapes/index |
| Telegram | `ALERT_TELEGRAM_*` | Push when jobs fail |
| Discord | `ALERT_DISCORD_WEBHOOK_URL` | Team channel alerts |

Keep secrets in **`.env.scheduler`** only (not in files you give to the other VPS).

### Still add later (ops, not blocking env)

- `OPENSTAT_URLS` if you need custom PSA tables  
- Scraper delay / cooldown knobs if jobs fail or are too slow  
- HTTPS / domain / Nginx in front of the API

---

# Part 7 — Common mistakes

| Mistake | Fix |
|---------|-----|
| `API_AUTH_DISABLED=true` on public Hostinger | Set `false` + real keys |
| Using `URLS=` for OpenSTAT | Use **`OPENSTAT_URLS=`** |
| Spaces like `QDRANT_API_KEY = value` | Use `QDRANT_API_KEY=value` |
| Giving admin key to other VPS | Give public key only |
| Exposing Qdrant port 6333 | Keep localhost; API is the public face |
| Publishing Chainlit `8001` on `0.0.0.0` | Use prod override `127.0.0.1:8001` + SSH tunnel |
| `AGENT_UI_API_URL=http://127.0.0.1:8000` (no path) | Use full `…/v1/agent/chat` (or Docker `http://api:8000/v1/agent/chat`) |
| Leaving `*_FRESH_CORPUS=true` | One-time reset only |
| Putting LLM/Wasabi keys in `.env.scheduler` **and** sharing that file | Keep secrets split |

---

## Related docs

- [`.env.example`](../.env.example) — full template from code analysis  
- [`docs/deploy.md`](deploy.md) — API deploy plan  
- [`docs/AGENT_UI.md`](AGENT_UI.md) — Chainlit local + Docker  
- [`docs/SECURITY_REVIEW.md`](SECURITY_REVIEW.md) — security checklist  
- [`docs/SCHEDULER_SETUP.md`](SCHEDULER_SETUP.md) — auto scrapes / cron  

---

*Last aligned with codebase env reads (Settings + `os.getenv` inventory).*
