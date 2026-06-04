"""Per-job scrape+process entrypoints."""

from .openstat_jobs import (
    run_irri,
    run_openstat,
    run_philrice,
    run_philrice_news,
    run_pinoyrice,
)
from .prism_jobs import run_prism_scrape, run_prism_yield

__all__ = [
    "run_philrice",
    "run_philrice_news",
    "run_pinoyrice",
    "run_irri",
    "run_openstat",
    "run_prism_scrape",
    "run_prism_yield",
]
