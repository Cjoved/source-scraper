---
name: prism-env-doctor
description: Diagnoses and fixes .env configuration for PRiSM jobs in this repository. Use when outputs are wrong, mode selection is confusing, or env variables conflict.
disable-model-invocation: true
---

# PRiSM Env Doctor

## Use this skill when
- User asks "ano ba env ko?" or similar setup questions.
- Job behavior does not match expectation.
- There are mixed settings from HTTP export and browser scrape.

## Diagnosis Steps
1. Read `.env`.
2. Detect selected mode from `PRISM_JOB`.
3. Check required keys for that mode.
4. Flag conflicting keys and propose a minimal corrected block.

## Mode Rules
- `PRISM_JOB=export_yield_csv` (or `export_yield`)
  - Required: none beyond job key.
  - Optional tuning keys: `PRISM_EXPORT_*`.
  - `PRISM_URL` is not required.
- `PRISM_JOB=browser_csv` (or default browser path)
  - Required: `PRISM_URL` or `PRISM_URLS`.
  - Optional:
    - `PRISM_SCRAPLING_MODE`
    - `PRISM_JS_SETTLE_SECONDS`
    - `PRISM_BROWSER_SAVE_CORPUS`
    - `PRISM_BROWSER_TABLES_CSV`

## Conflict Patterns
- Browser-only keys without `PRISM_URL` -> browser fails early.
- `PRISM_EXPORT_*` present but no `PRISM_JOB=export_yield_csv` -> app may enter browser mode unexpectedly.
- `PRISM_JOB=browser_csv` with only export keys -> wrong behavior expectation.

## Output Format
- Return:
  - active mode
  - detected issues (short bullets)
  - exact replacement `.env` block for the user intent (yield vs browser)

## Safe Presets
### Yield preset
```env
PRISM_JOB=export_yield_csv
PRISM_EXPORT_DELAY=1.0
PRISM_EXPORT_JITTER=0.55
PRISM_EXPORT_YEAR_MIN=2018
PRISM_EXPORT_YEAR_MAX=2026
PRISM_EXPORT_RETRIES=5
PRISM_EXPORT_TIMEOUT=90
PRISM_EXPORT_COOLDOWN_EVERY=75
PRISM_EXPORT_COOLDOWN_SECONDS=12
```

### Browser tables preset
```env
PRISM_JOB=browser_csv
PRISM_URL=https://prism.philrice.gov.ph/dataproducts/
PRISM_SCRAPLING_MODE=stealth
PRISM_JS_SETTLE_SECONDS=8
PRISM_BROWSER_SAVE_CORPUS=false
```
