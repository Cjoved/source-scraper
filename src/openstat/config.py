"""
Project paths: delegates to src.services.config (single source of truth).
OpenStat call sites expect str paths for os.path compatibility.
"""
from src.services import config as _config

PROJECT_ROOT = str(_config.PROJECT_ROOT)
DATA_DIR = str(_config.DATA_DIR)


def data_path(*parts: str) -> str:
    """Build path under data/ (e.g. data_path('philrice_processed', 'per_file'))."""
    return str(_config.data_path(*parts))
