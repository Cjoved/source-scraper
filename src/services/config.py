import os
from pathlib import Path

# Repo root: .../source-scraper (two levels up from this file: services -> src -> root)
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
DATA_DIR: Path = PROJECT_ROOT / "data"
DATA_RAW_DIR: Path = DATA_DIR / "raw"
DATA_PROCESSED_DIR: Path = DATA_DIR / "processed"


def data_path(*parts: str) -> Path:
    return DATA_DIR.joinpath(*parts)


def get_env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)
