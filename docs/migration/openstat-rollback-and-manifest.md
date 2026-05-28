# OpenStat Migration Rollback and Manifest

## Rollback Procedure

1. Confirm current git state before starting a migration batch:
   - `git status`
   - `git diff --name-only`
2. Create a restore point commit or branch checkpoint before each subsystem batch.
3. Run batch-level validation (imports + targeted smoke checks).
4. If parity fails, revert only the current batch changes and rerun validation.

## Batch Manifest Template

Use this template per subsystem batch.

| Batch | Scope | Copied | Modified | Removed | Deferred | Validation Result |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | OpenStat namespace scaffolding | `src/openstat/*` | `main.py`, `pyproject.toml` | N/A | OpenStat UI | in-progress |

## Current Migration Entries

- Rollback checkpoint:
  - Local branch: `backup/openstat-premerge-2026-05-28`

- Batch 1:
  - Copied OpenStat code into `src/openstat/*`.
  - Added `src/openstat/__init__.py` and `src/openstat/runner.py`.
  - Updated imports in migrated modules to `src.openstat.*`.
  - Updated `main.py` with `openstat` subcommand.
  - Updated `pyproject.toml` with `openstat` optional dependency group.

