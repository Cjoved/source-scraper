---
name: prism-runbook
description: Runs and debugs PRiSM scraper workflows in this repository. Use when the user asks how to run, troubleshoot, or validate yield export or Scrapling browser jobs.
disable-model-invocation: true
---

# PRiSM Runbook

## Use this skill when
- User asks how to run scraper jobs.
- User reports runtime failures (env, missing deps, wrong job mode, no output).
- User needs a safe step-by-step verification before long runs.

## Quick Workflow
1. Confirm mode intent:
   - Yield API export (`PRISM_JOB=export_yield_csv`)
   - Browser table extraction (`PRISM_JOB=browser_csv`)
2. Validate install commands:
   - Core: `uv sync`
   - Browser: `uv sync --extra browser` and `uv run scrapling install`
3. Validate minimum env for chosen mode.
4. Run:
   - `uv run python main.py`
5. Verify expected output file(s) and checkpoint updates.

## Required Env Checks
- Yield mode:
  - `PRISM_JOB=export_yield_csv`
- Browser mode:
  - `PRISM_JOB=browser_csv` (or unset for default browser path)
  - `PRISM_URL` or `PRISM_URLS`

## Common Failure Fixes
- Error: `No valid PRISM_URL / PRISM_URLS`
  - Cause: browser mode without URL.
  - Fix: set `PRISM_URL=...` or switch to yield job.
- Error: `unrecognized subcommand 'scrapling'` under `uv scrapling install`
  - Fix command: `uv run scrapling install`
- Browser path runs but no tables CSV:
  - Enable `PRISM_BROWSER_TABLES_CSV=true` or use `PRISM_JOB=browser_csv`
  - Increase `PRISM_JS_SETTLE_SECONDS`
  - Set `PRISM_CONTENT_SELECTOR` if DOM changed.

## Done Criteria
- Chosen job runs without immediate config/dependency errors.
- Expected output exists in `data/prism_processed/`.
- Checkpoint updated in `data/checkpoints/`.
