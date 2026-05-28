# OpenStat File Map (Code-Only Migration)

Source: `C:/Users/Crich Joved/OneDrive/Desktop/OpenStatv2`
Target: `C:/Users/Crich Joved/OneDrive/Desktop/source-scraper`

## Copied to `src/openstat`

- `src/config.py` -> `src/openstat/config.py`
- `main.py` -> `src/openstat/main.py`
- `src/agri_corpus/*.py` -> `src/openstat/agri_corpus/*.py`
- `src/scrapers/*.py` -> `src/openstat/scrapers/*.py`
- `src/services/*.py` -> `src/openstat/services/*.py`
- `src/utils/*.py` -> `src/openstat/utils/*.py`
- `src/scripts/*.py` -> `src/openstat/scripts/*.py`

## Import Rewrites Applied

- `from src.config` -> `from src.openstat.config`
- `from src.utils` -> `from src.openstat.utils`
- `from src.agri_corpus` -> `from src.openstat.agri_corpus`
- `from src.scrapers` -> `from src.openstat.scrapers`
- `from src.services` -> `from src.openstat.services`

## Excluded from Migration

- `.git`, `.env`
- `venv/`, `__pycache__/`
- `data/` runtime outputs and checkpoints
- PDF corpora/downloads/screenshots and large binary artifacts

## Canonical Conflict Keepers

- `main.py`
- `pyproject.toml`
- `uv.lock`
- `.gitignore`
- `README.md`
- `AGENTS.md`
- `src/scraper/*` PRISM modules

