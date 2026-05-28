# OpenStat Deployment Hardening Notes

This checklist applies after parity gate passes.

## Environment Standardization

- Install dependencies with `uv`:
  - `uv sync --extra openstat`
  - `uv run playwright install`
- Keep one workflow toggle true at a time for OpenStat runner:
  - `PHILRICE`, `PHILRICE_NEWS`, `PINOYRICE`, `OPENSTAT`, `IRRI`, `PRISM`
- Keep canonical PRISM workflow in `src/scraper/*`; OpenStat PRISM route calls canonical implementation.

## Build and Runtime Commands

```bash
uv run python main.py openstat
uv run python main.py scrape
uv run python main.py api --port 8000
```

## Operational Checks

- Validate output artifacts land under `data/`.
- Verify checkpoints are updated for long-running jobs.
- Validate no runtime artifacts are committed to git.
- Keep workflow-specific env presets in deployment docs/runbooks.

