"""
Project paths: single source of truth for PROJECT_ROOT and data/ output.
All scrapers and services use DATA_DIR for inputs/outputs.
"""
import os

# Project root = source-scraper repository root.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")


def data_path(*parts: str) -> str:
    """Build path under data/ (e.g. data_path('philrice_processed', 'per_file'))."""
    return os.path.join(DATA_DIR, *parts)
