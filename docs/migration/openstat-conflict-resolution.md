# OpenStat Conflict Resolution Policy

## Canonical Keepers (Do Not Overwrite Blindly)

- `main.py`
- `pyproject.toml`
- `uv.lock`
- `.gitignore`
- `README.md`
- `AGENTS.md`
- `src/scraper/*` (canonical PRISM implementation)

## Merge Rules

1. Preserve `source-scraper` canonical files by default.
2. Cherry-pick OpenStat behavior only when needed for parity.
3. Keep OpenStat modules namespaced under `src/openstat/*`.
4. For PRISM overlap, route OpenStat parity runner to `src/scraper/prism.py`.
5. Delete or deprecate duplicate OpenStat PRISM modules after routing is complete.

