# Agent API

`POST /v1/agent/chat` is a read-only LangChain-backed chat and tasklist agent over the project's indexed PRiSM, OpenSTAT, and corpus data.

The agent can answer in two modes:

- `chat`: normal farmer-facing or data-backed answers.
- `tasklist`: planning/checklist output for implementation or research tasks.

There is no `data` mode yet. Numeric data questions still use `chat`; the orchestrator chooses read-only tools when needed.

## Setup

Install API and agent dependencies:

```bash
uv sync --extra api --extra agent
```

Copy the values from `.env.agent.example` into your local `.env`, then set one provider.

DeepSeek:

```env
AGENT_ENABLED=true
AGENT_PROVIDER=deepseek
AGENT_BASE_URL=
AGENT_API_KEY=replace_with_deepseek_key
AGENT_MODEL=deepseek-chat
AGENT_TIMEOUT_SECONDS=60
AGENT_MAX_TOOL_CALLS=4
AGENT_DEFAULT_MODE=chat
```

Kimi / Moonshot:

```env
AGENT_ENABLED=true
AGENT_PROVIDER=kimi
AGENT_BASE_URL=
AGENT_API_KEY=replace_with_kimi_key
AGENT_MODEL=kimi-k2.5
AGENT_TIMEOUT_SECONDS=60
AGENT_MAX_TOOL_CALLS=4
AGENT_DEFAULT_MODE=chat
```

OpenAI-compatible fallback, such as OpenRouter:

```env
AGENT_ENABLED=true
AGENT_PROVIDER=openai_compatible
AGENT_BASE_URL=https://openrouter.ai/api/v1
AGENT_API_KEY=replace_with_openrouter_key
AGENT_MODEL=moonshotai/kimi-k2.5
```

Disabled local-development config:

```env
AGENT_ENABLED=false
```

Optional JWT user identity for agent chat:

```env
JWT_AUTH_ENABLED=false
JWT_REQUIRED_FOR_AGENT=false
JWT_SECRET=change-me-for-local-demo
JWT_ALGORITHM=HS256
JWT_ISSUER=
JWT_AUDIENCE=
```

`X-API-Key` still controls service/API access. `Authorization: Bearer <jwt>` is only for end-user identity such as `sub`, `role`, and `tenant_id`. Keep JWT disabled during local development if you do not need user identity.

## Request Shape

```json
{
  "message": "Ano ang average yield ng palay sa Laguna 2 years ago?",
  "mode": "chat",
  "source_ids": null,
  "location": null,
  "crop": null,
  "language": null,
  "session_id": null,
  "max_tool_calls": null
}
```

Use `source_ids` only for corpus, news, and advisory searches. Do not pass `source_ids` for PRiSM yield summaries or OpenSTAT price summaries.

Common corpus source ids:

- `philrice_news`
- `irri`
- `philrice`
- `pinoyrice`

## Curl Examples

Tasklist:

```bash
curl -X POST "http://127.0.0.1:8000/v1/agent/chat" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{"message":"Gawan mo ako ng tasklist para linisin ang PhilRice News corpus","mode":"tasklist","source_ids":["philrice_news"]}'
```

PRiSM yield summary:

```bash
curl -X POST "http://127.0.0.1:8000/v1/agent/chat" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{"message":"Ano ang average yield ng palay sa Laguna 2 years ago?","mode":"chat"}'
```

OpenSTAT price summary:

```bash
curl -X POST "http://127.0.0.1:8000/v1/agent/chat" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{"message":"Ano ang average farmgate price ng palay sa Nueva Ecija 3 years ago?","mode":"chat"}'
```

Latest IRRI news:

```bash
curl -X POST "http://127.0.0.1:8000/v1/agent/chat" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{"message":"Ano ang latest news sa IRRI tungkol sa rice farming?","mode":"chat","source_ids":["irri"]}'
```

Farmer advisory from PinoyRice:

```bash
curl -X POST "http://127.0.0.1:8000/v1/agent/chat" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{"message":"Ano ang dapat gawin kapag naninilaw ang dahon ng palay?","mode":"chat","source_ids":["pinoyrice"],"crop":"palay"}'
```

Agent chat with JWT user identity:

```bash
curl -X POST "http://127.0.0.1:8000/v1/agent/chat" \
  -H "accept: application/json" \
  -H "X-API-Key: <public-api-key>" \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{"message":"Magkano palay ngayon sa Abra?","mode":"chat","session_id":"demo-session-1"}'
```

## Response Fields

- `answer`: final user-facing answer.
- `tasklist`: structured checklist when `mode="tasklist"`.
- `tool_calls`: read-only tools the agent used, including arguments and result count.
- `sources`: source metadata for tool-backed answers.
- `warnings`: structured warnings such as missing API key, no results, timeout, or ignored source scope.
- `confidence`: `high` for deterministic summaries, `medium` for RAG-backed answers, `low` for fallback or no-result responses.
- `took_ms`: endpoint duration.

JWT claims are not echoed back in the response. The API uses the verified JWT internally for user identity and future session/memory routing.

## Testing Without Real Model Calls

Agent unit tests patch the LangChain model with fake model classes and use `FakeQdrantStore`.

Run focused agent tests:

```bash
uv run python -m unittest tests.test_agent_orchestrator tests.test_api_agent -v
```

Run all tests:

```bash
uv run python -m unittest discover -s tests -p "test_*.py" -v
```

Some non-agent tests may require optional services or browser dependencies such as Qdrant, FlareSolverr, or Playwright.

## Operations

- Rotate keys by replacing `AGENT_API_KEY` in `.env` and restarting the API process.
- Lower `AGENT_TIMEOUT_SECONDS` if provider calls are tying up requests too long.
- Lower `AGENT_MAX_TOOL_CALLS` to cap model-driven tool loops.
- Set `AGENT_MAX_TOOL_CALLS=0` to disable tool execution while keeping model-only chat enabled.
- Set `AGENT_ENABLED=false` to disable live model calls and use fallback responses.

## Troubleshooting

- Missing API key: set `AGENT_API_KEY`, `AGENT_PROVIDER`, and `AGENT_MODEL`.
- Provider timeout: increase `AGENT_TIMEOUT_SECONDS`, switch model, or retry later.
- Qdrant unavailable: start Qdrant and ensure indexed collections exist.
- No sources returned: the query may be model-only, no matching data was found, or a deterministic summary had zero rows.
- `source_scope_ignored`: remove `source_ids` for yield or price questions; source ids are only for corpus/news tools.

## Security Notes

- Do not commit real `.env` files or API keys.
- Do not log `AGENT_API_KEY`.
- Do not trust `user_id` from request bodies; user identity must come from a verified JWT `sub` claim.
- Do not return or mint JWTs from `/v1/agent/chat`; token refresh belongs to the auth/login service.
- The current agent tools are read-only and must not trigger scraping, indexing, exports, deletes, or admin operations.
- Keep public API auth and rate limits enabled outside local development.
