# Agent Scraper

## Buod ng Buong Project

Ang Agent Scraper ay isang end-to-end agricultural data platform para sa pangongolekta, pagproseso, pag-index, paghahanap, at pagpapaliwanag ng datos mula sa PRiSM, PSA OpenSTAT, PhilRice, PhilRice News, PinoyRice, at IRRI.

Hindi lang ito simpleng web scraper. Binubuo ito ng magkakaugnay na subsystem:

1. **Scrapers** — kumukuha ng structured at narrative data mula sa APIs at websites.
2. **Processors at validators** — naglilinis at naglalagay ng data sa standardized CSV at JSONL formats.
3. **Indexers** — naglalagay ng structured records at searchable knowledge sa Qdrant.
4. **FastAPI service** — nagbibigay ng secure HTTP endpoints para magamit ng ibang applications.
5. **AI agent** — inuunawa ang tanong, pinipili ang tamang read-only tool, kinukuha ang tunay na project data, at gumagawa ng source-aware na sagot.
6. **Chainlit UI** — chat interface para sa testing at farmer-facing demos.
7. **Orchestrator** — awtomatikong nagpapatakbo ng scraping, validation, indexing, backup, at alerts ayon sa schedule.
8. **Operations layer** — Docker, FlareSolverr, Qdrant, Wasabi backups, Telegram/Discord alerts, at production deployment.

Ang pangunahing layunin nito ay gawing reusable data and intelligence backend ang agricultural sources para sa Digisaka, WebGIS, dashboards, mobile applications, at iba pang systems.

---

## Bakit Ginawa ang Project

Ang agricultural information ay nanggagaling sa magkakaibang websites at formats:

- PRiSM yield data ay structured at maaaring manggaling sa API export o browser tables.
- OpenSTAT price data ay tabular at kailangang gawing consistent bago ma-query.
- PhilRice publications ay kadalasang PDF.
- PhilRice News, PinoyRice, at IRRI ay narrative web content.
- May mga source na dynamic, protected, mabagal, o kailangang gamitan ng browser automation.

Kung scraper lang ang system, makakakuha ito ng files pero mahirap pa ring gamitin ng ibang applications at ordinaryong users. Kaya dinagdagan ang project ng:

- standardized outputs;
- validation at checkpoints;
- searchable Qdrant indexes;
- versioned API;
- scheduled refresh;
- source-aware AI agent.

Ang resulta ay isang pipeline mula raw website hanggang farmer-friendly answer.

---

## High-Level Architecture

```text
PRiSM / OpenSTAT / PhilRice / PinoyRice / IRRI
                       |
                       v
            HTTP at browser scrapers
                       |
                       v
          Processing, cleaning, chunking
                       |
                       v
            CSV at canonical CPT JSONL
                       |
                       v
       Validation, checkpoints, run manifests
                       |
                       v
              Qdrant indexing layer
                       |
          +------------+-------------+
          |                          |
          v                          v
    FastAPI /v1 endpoints        AI agent tools
          |                          |
          +------------+-------------+
                       |
                       v
          Chainlit / Digisaka / WebGIS /
             dashboards / other APIs
```

---

## Main Project Flow

### 1. Data Collection

Ang source-specific scraper ang kumukuha ng data mula sa website o API.

Para sa canonical PRiSM implementation, explicit ang layering:

```text
client -> parser -> spider -> formatter
```

- **Client** — HTTP o browser communication.
- **Parser** — extraction ng values mula sa response o page.
- **Spider** — pagination, retries, loops, at orchestration.
- **Formatter** — final CSV o corpus output.

Para sa PhilRice, News, PinoyRice, OpenSTAT, at IRRI, nasa `src/openstat/` ang compatibility workflows at site-specific processors.

### 2. Processing

Ang raw data ay nililinis at kino-convert sa isa sa dalawang pangunahing contracts:

- **CSV** para sa structured yield at price data.
- **Canonical CPT JSONL** para sa narrative documents, articles, at PDF pages.

### 3. Validation

Sinusuri ang:

- required fields;
- empty text;
- duplicate `doc_id`;
- minimum text length;
- malformed JSONL;
- missing outputs;
- source-specific quality rules.

Ang bawat orchestrated run ay maaaring gumawa ng:

```text
data/runs/<run_id>/manifest.json
data/runs/<run_id>/validation_report.json
```

### 4. Indexing

Ang validated outputs ay ina-upsert sa Qdrant.

May dalawang klase ng indexed data:

- **Structured records** — para sa exact filters, lists, at deterministic summaries.
- **Knowledge vectors** — para sa natural-language hybrid search.

### 5. API Access

FastAPI ang stable boundary ng system. Hindi dapat direktang kumonekta sa Qdrant ang downstream applications.

### 6. Agent Reasoning

Kapag natural-language question ang request, inuunawa muna ng agent ang intent at context. Pagkatapos ay pumipili ito ng tamang tool, kumukuha ng data, sinusuri ang sources, at gumagawa ng sagot.

### 7. Scheduled Refresh

Ang orchestrator ang nagpapatakbo ng regular scrape → validate → index → backup lifecycle.

---

## Supported Data Sources

### PRiSM

Dalawang pangunahing data paths:

1. **Yield export**
   - Bulk extraction mula sa PRiSM HTTP API.
   - Output: `data/prism_processed/prism_yield_export.csv`
   - Checkpoint: `data/checkpoints/prism_yield_export_checkpoint.json`

2. **Browser scraping**
   - Dynamic table at narrative page extraction gamit ang Scrapling.
   - Table output: `data/prism_processed/prism_browser_tables.csv`
   - Optional corpus: `data/prism_processed/prism_corpus.jsonl`
   - RAG-ready chunked corpus: `data/prism_processed/prism_corpus_chunked.jsonl`

### PSA OpenSTAT

- Kumukuha ng agricultural price tables.
- Main structured output:

```text
data/openstat_processed/openstat_table.csv
```

- Ang OpenSTAT price table ay hindi bahagi ng narrative RAG collection.
- May sarili itong structured at knowledge collections para sa price queries.

### PhilRice Publications

- Publication/PDF scraping at processing.
- Sa stream mode: download → process → append corpus → delete temporary PDF.
- Output:

```text
data/philrice_processed/philrice_corpus.jsonl
```

- Qdrant `source_id`: `philrice`

### PhilRice News

- News/article scraping at text processing.
- Output:

```text
data/philrice_news_processed/philrice_news_corpus.jsonl
```

- Qdrant `source_id`: `philrice_news`

### PinoyRice

- Portal text at optional PDF processing.
- Main RAG output:

```text
data/pinoyrice_processed/pinoyrice_corpus.jsonl
```

- Qdrant `source_id`: `pinoyrice`

### IRRI

- IRRI Philippines pages at related narrative content.
- Output:

```text
data/irri_processed/irri_corpus.jsonl
```

- Qdrant `source_id`: `irri`

---

## Data Contracts

### Structured CSV

#### PRiSM yield

```text
data/prism_processed/prism_yield_export.csv
```

Ginagamit para sa:

- filtered yield records;
- deterministic yield summaries;
- yield knowledge search.

#### OpenSTAT prices

```text
data/openstat_processed/openstat_table.csv
```

Core fields:

- geolocation;
- commodity type;
- commodity;
- year;
- month;
- price.

Ginagamit para sa:

- exact price filters;
- deterministic price summaries;
- semantic price search.

### Canonical CPT JSONL

Ang bawat non-empty line ay isang JSON object. Core fields:

```json
{
  "text": "clean document text",
  "input": "same as text",
  "content": "optional copy of text",
  "source": "philrice_news",
  "doc_id": "stable-document-id",
  "url": "optional source URL",
  "title": "optional title",
  "filename": "optional filename",
  "page": 1
}
```

Important rules:

- UTF-8;
- one JSON object per line;
- non-empty `text`;
- non-empty, source-stable `doc_id`;
- duplicate `doc_id` values fail quality validation.

Validator:

```bash
uv run python -m src.scripts.validate_corpus
```

---

## Qdrant Design

### Default Collections

```text
prism_yield_records
prism_yield_knowledge
openstat_price_records
openstat_price_knowledge
agri_corpus_rag
```

Maaaring palitan ang corpus collection sa `CORPUS_RAG_COLLECTION`. Mahalagang pareho ang collection name ng indexer at API.

### Collection Responsibilities

#### `prism_yield_records`

Payload-oriented structured yield records para sa filters, pagination, at summaries.

#### `prism_yield_knowledge`

Textified yield rows para sa hybrid natural-language search.

#### `openstat_price_records`

Structured OpenSTAT price records para sa exact queries at deterministic aggregation.

#### `openstat_price_knowledge`

Textified price rows para sa semantic search.

#### `agri_corpus_rag`

Unified narrative collection para sa:

- `philrice`;
- `philrice_news`;
- `pinoyrice`;
- `irri`;
- optional `prism_browser`.

Ang indexer mismo ang naglalagay ng `source_id` ayon sa manifest. Halimbawa, lahat ng records mula sa PhilRice News file ay ini-index na may:

```json
{"source_id": "philrice_news"}
```

Ito ang ginagamit ng agent para hindi maghalo ang PhilRice News at IRRI kapag explicit ang source sa tanong.

### Index Commands

Yield:

```bash
uv run python main.py index --collections all
```

Prices:

```bash
uv run python main.py index-prices --collections all
```

All narrative corpora:

```bash
uv run python -m src.indexing.corpus_rag_indexer
```

One corpus source:

```bash
uv run python -m src.indexing.corpus_rag_indexer --source philrice_news
```

The indexers use stable point IDs and upsert behavior. Re-running is safe and does not intentionally create duplicate points for the same source/document ID.

---

## FastAPI Layer

Ang API ay versioned sa `/v1`.

### Main Endpoint Families

```text
GET  /v1/health

GET  /v1/yield
GET  /v1/yield/metadata
GET  /v1/yield/summary
GET  /v1/yield/export
POST /v1/knowledge/search

GET  /v1/prices
GET  /v1/prices/metadata
GET  /v1/prices/summary
GET  /v1/prices/export
POST /v1/prices/search

POST /v1/corpus/search
POST /v1/agent/chat

GET  /v1/index/status
POST /v1/index/refresh-metadata
POST /v1/prices/refresh-metadata
```

### API Responsibilities

- authentication through `X-API-Key`;
- public, agent, at admin access scopes;
- rate limiting;
- optional CORS;
- consistent error envelopes;
- request IDs at structured access logs;
- security headers;
- optional Swagger/ReDoc documentation.

### Auth Scopes

- **Public key** — yield/prices/corpus search, metadata, summary, health-backed reads.
- **Admin key** — export endpoints, `/v1/index/status`, metadata refresh.
- **Agent key** — `/v1/agent/chat`; dapat accepted din ng agent auth rules.
- Optional JWT — user identity only (`sub`, role, tenant). Hindi kapalit ng `X-API-Key`.

Default rate limits:

- read: `120/minute`
- search: `30/minute`
- export: `5/minute`
- health: `60/minute`
- agent: `10/minute`

### Access Pattern

Downstream applications should use:

```env
SOURCE_SCRAPER_API_URL=https://your-api-domain.example
SOURCE_SCRAPER_API_KEY=public-key
SOURCE_SCRAPER_AGENT_API_KEY=agent-key
```

Request header:

```http
X-API-Key: <key>
```

Ang ibang applications ay hindi dapat bigyan ng:

- Qdrant URL;
- Qdrant API key;
- admin API key, maliban kung operator application talaga.

---

## Bakit Ito Naging Agent

Ang LLM chatbot ay karaniwang kumukuha lamang ng user message at direktang bumubuo ng sagot. Ang Agent Scraper agent ay may controlled reasoning-and-tool loop.

### Agent Characteristics

#### 1. Lightweight context hints (keyword intent = fallback)

Optional request context: location, crop, language, source_ids.
Keyword `infer_farmer_intent` still exists but is **not** the planner authority — it only runs when the LLM PlanAgent fails (`plan_llm_fallback`).

#### 2. LLM structured PlanAgent (`src/agent/plan_schema.py` + `plan_agent.py`)

Authority: one structured LLM call emits `AgentPlan` / `PlanStep[]`, then `validate_agent_plan()` normalizes:

- tool allowlist + `AGENT_PLAN_MAX_STEPS` clamp;
- `source_ids` allowlist;
- commodity / date / location fill-ins;
- clarification when price/yield lacks location;
- multi-step OK for compound (`mixed`) questions.

On planner failure → legacy `infer_farmer_intent` + `build_search_plan` + warning `plan_llm_fallback`.

Pagkatapos ng plan: **Stage-1 retrieve + FlashRank**, tapos **Stage-2 LLM multi-query** lang kung weak ang Stage-1 (`AGENT_PLAN_REWRITE`). News/paper answers ay **exact titles/URLs**.

#### 3. May read-only tools

Available tools:

```text
summarize_yield
search_yield_knowledge
summarize_prices
search_prices
search_corpus
```

Ang deterministic summary tools ang ginagamit kapag exact numerical answer ang kailangan. Semantic search tools naman ang ginagamit para sa natural-language retrieval.

#### 4. Nakaka-observe ng tool results

Pagkatapos tumawag ng tool, ibinabalik sa model ang:

- result count;
- normalized arguments;
- summary;
- payload/hits;
- sources;
- errors.

Maaari itong humiling ng susunod na tool hanggang maabot ang configured tool-call limit.

#### 5. May tool-family guardrails

Follow-up model tool calls stay scoped to the **executed plan’s tool family**. Mixed multi-step plans (e.g. prices then corpus) allow those families; a single-family plan still blocks cross-family calls (`tool_scope_blocked`).

#### 6. May source grounding

Ang retrieved sources ay dumadaan sa:

- hard source-scope checks;
- intent-specific checks;
- relevance verification;
- deduplication.

Hindi dapat mag-cite ng IRRI result kapag explicit na PhilRice News lang ang hinihingi.

#### 7. May confidence at warnings

Response contract:

```text
answer
tasklist
tool_calls
sources
warnings
confidence
took_ms
```

Confidence behavior:

- **high** — may deterministic structured summary;
- **medium** — may relevant RAG/search sources;
- **low** — fallback, no result, provider/storage error, o insufficient grounding.

#### 8. May fallback behavior

Kapag unavailable ang model o Qdrant:

- hindi nito dapat imbentuhin ang data;
- nagbibigay ito ng warning;
- gumagamit ng deterministic/tool-backed fallback kung posible;
- nagre-return ng low confidence kapag walang sapat na evidence.

### Agent Loop

```text
User question
     |
     v
Lightweight hints (location/crop/language)
     |
     v
LLM structured PlanAgent → validate_agent_plan (multi-step OK)
     |-- fail --> legacy keyword intent + build_search_plan
     v
Execute plan steps (tools) — cascade + FlashRank for corpus
     |
     v
Weak corpus hit? (0 results / low score / vague+few)
     |-- no --> synthesize
     |-- yes + AGENT_PLAN_REWRITE --> Stage-2 multi-query + RRF + rerank
     v
Send prompt + tool observations to LangChain model (synthesize)
     |
     v
Optional follow-up tools (scoped to planned families)
     |
     v
Ground sources; news/paper/mixed corpus → exact title listing
     |
     v
Return answer + sources + warnings + confidence
```

Env: `AGENT_LLM_PLANNER`, `AGENT_PLAN_MAX_STEPS`, `AGENT_PLAN_REWRITE`, `AGENT_PLAN_MAX_QUERIES`, `AGENT_CASCADE_MIN_SCORE`, `AGENT_RERANK_ENABLED`, `AGENT_RERANK_CANDIDATES`.

### What the Agent Is Not

- Hindi nito awtomatikong sinisimulan ang scraping dahil lang may user question.
- Hindi ito nagsusulat, nagde-delete, o nagre-index sa pamamagitan ng user chat.
- Hindi ito direct Qdrant administrator.
- Hindi ito kapalit ng deterministic API para sa exact analytics.
- Wala itong server-side persistent conversation memory sa kasalukuyang design; ang request/history ang nagbibigay ng chat context.

Ito ay intentionally **read-only data agent** para mas ligtas sa production.

---

## Chainlit UI

Ang Chainlit ay thin frontend para sa `/v1/agent/chat`.

Responsibilities:

- farmer-facing chat;
- source display;
- warnings;
- confidence;
- tool trace;
- response timing;
- chat/tasklist profiles;
- source scoping commands.

Hindi nito ginagawa ang reasoning o Qdrant search mismo. FastAPI agent endpoint pa rin ang source of truth. Hindi rin ito nagsa-scrape, nag-i-index, o nagsusulat sa Qdrant. Session history ay local sa UI (roughly last messages), hindi server-side persistent memory.

Local:

```bash
uv run chainlit run src/agent/ui_chainlit.py -w --port 8001
```

Sa Docker, dapat ang internal agent URL ay:

```env
AGENT_UI_API_URL=http://api:8000/v1/agent/chat
```

Hindi `127.0.0.1:8000`, dahil ang `127.0.0.1` sa Chainlit container ay ang Chainlit container mismo.

Implementation note: sa `src/agent/ui_chainlit.py`, may dalawang `@cl.on_chat_start` handlers. Ang profile helper ay kasalukuyang naka-decorate din bilang `on_chat_start` sa halip na `@cl.set_chat_profiles`. Suriin ito bago i-treat ang chat profiles bilang fully production-ready.

---

## Orchestrator at Scheduler

Ang `src/orchestrator/` at `orchestrator.yaml` ang production automation layer.

### Supported Operations

```bash
uv run python -m src.orchestrator list
uv run python -m src.orchestrator run <job_id>
uv run python -m src.orchestrator run --all
uv run python -m src.orchestrator run --due
uv run python -m src.orchestrator serve
uv run python -m src.orchestrator test-alerts
```

### Main Scheduled Jobs

- `philrice`
- `philrice_news`
- `pinoyrice`
- `irri`
- `openstat`
- `openstat_index`
- `prism_scrape`
- `prism_yield`
- `prism_index`
- `corpus_rag_index`
- `corpus_backup_wasabi`

Timezone:

```text
Asia/Manila
```

### Orchestrator Responsibilities

- cron scheduling;
- per-job environment overrides;
- timeout handling;
- browser-job lock;
- Qdrant at FlareSolverr preflight;
- output validation;
- run manifests;
- structured logging;
- Wasabi upload;
- Qdrant snapshots;
- Telegram/Discord/local alerts;
- optional AI-assisted error explanation.

### Stream Processing

Para sa large source pipelines, supported ang stream pattern:

```text
download -> process -> append JSONL -> checkpoint -> delete temporary raw file
```

Pinapababa nito ang disk usage at pinapanatiling resumable ang jobs.

---

## Backup at Recovery

### Wasabi

Maaaring i-upload ang:

- corpus files;
- checkpoints;
- dated releases;
- Qdrant collection snapshots.

Pagkatapos ng successful scrape jobs, automatic ang per-job corpus/checkpoint backup. Pagkatapos ng index jobs, snapshot ng existing Qdrant collections ang ina-upload.

### Qdrant Snapshots

Ang system ay gumagawa ng snapshot para sa existing collections at ina-upload sa configured Wasabi prefix.

Restore utility:

```bash
uv run python -m src.storage.wasabi_restore --list-dates
uv run python -m src.storage.wasabi_restore --all
uv run python -m src.storage.wasabi_restore --all --reindex
uv run python -m src.storage.wasabi_restore --qdrant --tier latest
```

Possible options include listing restore dates, restoring Qdrant snapshots, at rebuilding indexes.

---

## Docker at Production Topology

### Services

```text
Apache/Nginx HTTPS reverse proxy
             |
             v
      source-scraper-api :8000
             |
             +---- Qdrant Docker network ---- qdrant-vector-db :6333
             |
             +---- Chainlit :8001 (internal/testing)

source-scraper-scheduler
             |
             +---- Qdrant
             +---- FlareSolverr :8191
             +---- data/ volume
```

### Ports

- `8000` — FastAPI.
- `8001` — Chainlit.
- `6333` — Qdrant HTTP.
- `6334` — Qdrant gRPC.
- `8191` — FlareSolverr internal service.
- `80/443` — reverse proxy / HTTPS.

Qdrant at FlareSolverr should not be publicly exposed.

### Qdrant Networking

Kapag hiwalay ang Qdrant compose stack, kailangang sumali ang API at scheduler sa Qdrant external Docker network.

Typical production values:

```env
DOCKER_QDRANT_URL=http://qdrant-vector-db:6333
QDRANT_DOCKER_NETWORK=qdrant_default
```

Ang Python application mismo ay nagbabasa ng `QDRANT_URL`. Ang compose variable na `DOCKER_QDRANT_URL` ay helper na kino-convert ng compose sa container `QDRANT_URL`.

### Why Docker Runtime Uses Direct Commands

Ginagamit ang `uv sync` sa image build para i-install ang dependencies sa `/app/.venv`.

Sa runtime, direct commands ang ginagamit:

```text
uvicorn main:app
chainlit run ...
python -m src.orchestrator serve
```

Hindi kailangan ang `uv run` sa locked-down `appuser` runtime, at iniiwasan nito ang writable-cache permission errors.

---

## Security Model

### API Authentication

- `API_KEYS_PUBLIC` — read endpoints.
- `API_KEYS_AGENT` — agent chat.
- `API_KEYS_ADMIN` — export at operator actions.

Ang agent key ay kailangang nasa `API_KEYS_AGENT` at sa accepted public key set ayon sa current auth flow.

### Production Rules

- `APP_ENV=production`
- `API_AUTH_DISABLED=false`
- `API_DOCS_ENABLED=false` unless intentionally enabled
- `AGENT_ALLOW_PUBLIC=false`
- HTTPS in front of API
- Qdrant bound privately
- FlareSolverr internal only
- real secrets only in `.env` or secret manager
- no runtime `data/` artifacts in Git

### Agent Safety

- read-only tools;
- max tool-call limit;
- rate limiting;
- source-scope validation;
- low-confidence behavior for missing evidence;
- warnings instead of hidden failures;
- no admin operations from chat.

---

## Project Structure

```text
main.py                         unified CLI and FastAPI app export
orchestrator.yaml               schedules and job overrides

src/scraper/                    canonical PRiSM scraper
src/openstat/                   PhilRice/OpenSTAT/PinoyRice/IRRI workflows
src/formatter/                  output shaping and CSV writers
src/services/                   shared configuration and processing
src/utils/                      shared network, ID, chunk, CPT, JSONL helpers
src/indexing/                   yield, price, and corpus indexers
src/storage/                    Qdrant and Wasabi adapters
src/api/                        FastAPI routes, auth, middleware, schemas
src/agent/                      intent, planner, tools, prompts, orchestrator, UI
src/orchestrator/               scheduler, runners, validation, alerts

data/                           runtime outputs and checkpoints
tests/                          unit tests
docs/                           setup, API, deployment, migration, operations
```

---

## Common Commands

### Install

```bash
uv sync
uv sync --extra api --extra agent --extra ui
uv sync --extra orchestrator --extra browser --extra openstat
uv run scrapling install
uv run playwright install
```

### Run Core Services

```bash
uv run python main.py
uv run python main.py openstat
uv run python main.py api --port 8000
uv run chainlit run src/agent/ui_chainlit.py -w --port 8001
```

### Index

```bash
uv run python main.py index --collections all
uv run python main.py index-prices --collections all
uv run python -m src.indexing.corpus_rag_indexer
```

### Validate and Test

```bash
uv run python -m src.scripts.validate_corpus
uv run python -m unittest discover -s tests -p "test_*.py" -v
```

### Docker

```bash
docker compose -f docker-compose.qdrant.yml up -d
docker compose -f docker-compose.deploy.yml --profile ui --profile scheduler up -d --build
```

---

## Example User Question Flows

### Price Question

```text
"Magkano ang palay sa Nueva Ecija?"
  -> intent: price_query
  -> crop alias normalization
  -> summarize_prices
  -> OpenSTAT structured records
  -> deterministic PHP price summary
```

### Yield Question

```text
"Ano ang average yield sa Laguna noong 2024?"
  -> intent: yield_query
  -> location/year extraction
  -> summarize_yield
  -> PRiSM structured records
  -> deterministic yield summary
```

### News Question

```text
"Ano ang latest news mula sa PhilRice?"
  -> intent: news_query
  -> source scope: philrice_news
  -> search_corpus(sort_by=latest)
  -> Qdrant filter: source_id=philrice_news
  -> grounded response with source
```

### Advisory Question

```text
"Ano ang gagawin kapag naninilaw ang dahon ng palay?"
  -> intent: advisory_query
  -> search relevant narrative corpus
  -> retrieve PhilRice/IRRI/PinoyRice evidence
  -> source-aware advisory with warning if evidence is weak
```

---

## Known Operational Lessons

1. **Indexer at API must use the same collection name.**
   - Example: kung indexer uses `agri_corpus` pero API uses `agri_corpus_rag`, zero hits ang result.

2. **A source must actually be indexed.**
   - Existing JSONL file does not automatically mean it is already in Qdrant.

3. **Docker localhost is container-local.**
   - Chainlit container uses `http://api:8000`, not `127.0.0.1:8000`.

4. **Host-only Qdrant ports are not reachable through the host loopback from another container.**
   - Use a shared Docker network and `http://qdrant-vector-db:6333`.

5. **Structured data and narrative RAG have different collections.**
   - OpenSTAT prices use price collections, not `agri_corpus_rag`.

6. **A 0-result response is different from Qdrant unavailable.**
   - `no_results` means search worked but no matching point exists.
   - `qdrant_unavailable` means connection, collection, API key, model cache, or storage operation failed.

7. **Swagger may be intentionally disabled in production.**
   - API can be healthy even when `/v1/docs` returns 404.

8. **CLI option for yield indexing is `--collections all`, not `--all`.**
   - Correct: `uv run python main.py index --collections all`

9. **Old docker-compose 1.29.2 may fail with `KeyError: 'ContainerConfig'` on recreate.**
   - Prefer `down` → remove containers → `up -d` instead of `--force-recreate`.

10. **Hybrid search uses dense + sparse retrieval.**
   - Dense: FastEmbed model such as `BAAI/bge-small-en-v1.5`
   - Sparse: BM25
   - Fusion default: RRF

---

## Current Product Role

Agent Scraper should remain the agricultural data and intelligence backend:

```text
Agent Scraper responsibilities:
- scrape
- process
- validate
- index
- search
- summarize
- provide source-aware agent answers
- schedule refreshes
- back up data

Digisaka / consumer app responsibilities:
- user accounts
- application permissions
- frontend experience
- user-specific business workflows
- call Agent Scraper through HTTPS + API key
```

This separation keeps Qdrant private, makes the data reusable across projects, and avoids duplicating scraper and AI retrieval logic in every application.

---

## Final Summary

Agent Scraper started as a scraper-oriented project but evolved into an agentic agricultural data platform because it now performs a complete evidence-based decision loop:

```text
collect -> clean -> validate -> index -> understand -> plan -> retrieve ->
observe -> ground -> answer -> schedule -> back up
```

It became an **agent** not merely because it uses an LLM, but because it:

- understands intent and context;
- creates a query plan;
- chooses among specialized tools;
- observes tool results;
- enforces tool and source boundaries;
- iterates within a controlled limit;
- reports sources, warnings, confidence, and timing;
- refuses to present unsupported data as reliable.

The scraper and scheduler keep the knowledge current. Qdrant makes it searchable. FastAPI makes it reusable. The agent makes the data understandable to people.
