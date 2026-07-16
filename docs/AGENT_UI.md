# Agent UI Demo

Phase 7 adds an optional Chainlit demo UI for `/v1/agent/chat`.

This UI is intentionally thin. It calls the existing FastAPI endpoint and renders the response fields; it does not change agent behavior, persist conversations server-side, scrape data, index data, or write to Qdrant.

## Why Chainlit

- Chainlit is built for chat-first AI apps and fits the agent's conversational flow.
- It can show source-aware responses, warnings, and tool traces without building a custom frontend.
- Streamlit is better for dashboards and dataframes; Gradio is better for quick ML model demos. This project needs a chat demo over an existing API.

## Install

```bash
uv sync --extra api --extra agent --extra ui
```

## Run (local process)

Terminal 1, start the API:

```bash
uv run uvicorn main:app --reload
```

Terminal 2, start the Chainlit UI:

```bash
uv run chainlit run src/agent/ui_chainlit.py -w --port 8001
```

Open the Chainlit URL printed in the terminal, usually `http://localhost:8001`. Keep FastAPI on `http://127.0.0.1:8000` so the UI can call `/v1/agent/chat` without a port conflict.

## Run (Docker)

Chainlit is an optional compose profile (`ui`). It uses the same image as the API (includes `--extra ui`) and calls the `api` service over the Docker network.

```bash
# Local stack + UI
docker compose --profile ui up -d --build

# Deploy compose + UI
docker compose -f docker-compose.deploy.yml --profile ui up -d --build

# Prod overrides: Chainlit on 127.0.0.1:8001 only
docker compose -f docker-compose.deploy.yml -f docker-compose.prod.yml --profile ui up -d --build
```

- UI: `http://127.0.0.1:8001`
- Inside containers, `AGENT_UI_API_URL` defaults to `http://api:8000/v1/agent/chat`
- Set `AGENT_UI_API_KEY` in `.env` / `.env.api` when API auth is enabled

## Production security

- Do **not** expose Chainlit publicly without Chainlit password/OAuth enabled.
- Prefer `--profile ui` only for verify/staging; prod override binds `127.0.0.1:8001`.
- `.chainlit/config.toml` disables spontaneous file uploads and restricts `allow_origins` by default.
- Point `AGENT_UI_API_KEY` at an admin or agent API key (`AGENT_ALLOW_PUBLIC=false` in production).
- See [SECURITY_REVIEW.md](SECURITY_REVIEW.md) for the full checklist.

## UI Enhancements

The demo uses native Chainlit UI features:

- Chat profiles:
  - `Farmer Chat` for Taglish farmer-facing questions.
  - `Data Explorer` for PRiSM yield, OpenSTAT prices, and source-backed data checks.
  - `Tasklist Planner` for implementation and cleanup checklists.
- Farmer-friendly starter cards use example-question labels such as `Nanilaw ang palay ko`, `Magkano ang palay ngayon?`, and `Bagong balita sa palay`.
- Project-specific welcome copy in `chainlit.md`.
- Custom styling in `public/agent.css`, enabled through `.chainlit/config.toml`.
- Theme-level primary color override in `public/theme.json` so Chainlit primary buttons use green instead of the default pink.
- Chainlit `Step` loading indicator while `/v1/agent/chat` is running.
- Simulated Markdown streaming via `cl.Message.stream_token()` after the API returns.
- Custom logo and assistant avatar from `public/AgriAgent.svg`.
- Custom send button and composer styling through Chainlit IDs `#chat-submit`, `#chat-input`, and `#message-composer`.
- Cleaner response rendering with answer, confidence, tasklist, sources, tool trace, warnings, and timing.

## Environment

The UI reads these optional variables:

```env
AGENT_UI_API_URL=http://127.0.0.1:8000/v1/agent/chat
AGENT_UI_API_KEY=
AGENT_UI_TIMEOUT_SECONDS=90
```

In Docker (`--profile ui`), compose sets `AGENT_UI_API_URL=http://api:8000/v1/agent/chat` unless you override it.

Set `AGENT_UI_API_KEY` when the API has public auth enabled. It is sent as `X-API-Key`.

The API still needs the normal agent environment from `.env.agent.example`, such as `AGENT_PROVIDER`, `AGENT_API_KEY`, and `AGENT_MODEL`.

## UI Commands

- `/tasklist <message>` sends the message with `mode="tasklist"`.
- `/chat <message>` sends the message with `mode="chat"`.
- `/mode chat` or `/mode tasklist` changes the default mode for later messages.
- `/sources irri,philrice_news` scopes later corpus/news queries.
- `/sources clear` clears source scope.

For PRiSM yield and OpenSTAT price questions, clear `source_ids` or omit `/sources`; source ids are only for corpus/news tools.

Starter cards can set a source scope and send a query in one message:

```text
/sources philrice_news,irri
May bagong balita ba tungkol sa palay?
```

The first line sets `source_ids`; the remaining lines are sent as the actual question.

## Demo Prompts

Yield:

```text
Ano ang average yield ng palay sa Laguna 2 years ago?
```

Price:

```text
Ano ang average farmgate price ng palay sa Nueva Ecija 3 years ago?
```

Latest news:

```text
/sources irri
Ano ang latest news sa IRRI tungkol sa rice farming?
```

Farmer advisory:

```text
/sources pinoyrice
Ano ang dapat gawin kapag naninilaw ang dahon ng palay?
```

Tasklist:

```text
/tasklist Gawan mo ako ng checklist para linisin ang PhilRice News corpus
```

## Response Rendering

The UI renders:

- `answer`
- `tasklist`
- `sources`
- `tool_calls`
- `warnings`
- `confidence`
- `took_ms`

Conversation history is kept in Chainlit session state and trimmed before being sent to the API.

## Tests

The testable logic lives in `src/agent/ui_helpers.py`, which has no Chainlit imports.

Run:

```bash
uv run python -m unittest tests.test_agent_ui_helpers tests.test_agent_orchestrator tests.test_api_agent -v
```

## Scope Boundaries

- No React/Vite build system.
- No server-side conversation persistence.
- No agent response contract changes.
- No scraping, indexing, exporting, deleting, or Qdrant writes from the UI.
- Chainlit is demo/user-facing only; production integrations can still call `/v1/agent/chat` directly.
