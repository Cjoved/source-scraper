# OpenStat Data and Fixture Parity

Defines minimum inputs and acceptable variance for parity checks.

## Minimum Input Requirements

- Stable internet access for live crawler targets.
- `.env` values for exactly one OpenStat workflow toggle per run.
- For OpenSTAT workflow:
  - `URLS` must include at least one valid OpenSTAT endpoint.
  - Optional MySQL settings only if DB insert validation is required.
- For PRISM compatibility workflow:
  - `PRISM_URL` or `PRISM_URLS` set for browser path.
  - `PRISM_JOB=export_yield_csv` for yield export path.

## Fixture Strategy

- Use lightweight smoke runs first (1 target URL / small page scope).
- Keep generated outputs under existing `data/` folders; do not commit runtime artifacts.
- Preserve checkpoint files only as runtime state, not source-controlled fixtures.

## Acceptable Output Variance

Allowed variance due to live web data changes:

- Row/article counts may differ from historical runs.
- Ordering may differ when source site content updates.
- Timestamp fields are expected to differ.

Not allowed:

- Missing required output file for a successful workflow.
- Schema break (expected keys/columns missing).
- Fatal runtime exceptions in normal connectivity conditions.

