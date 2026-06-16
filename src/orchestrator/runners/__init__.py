"""Per-job scrape+process entrypoints."""

from .openstat_jobs import (
    run_irri,
    run_openstat,
    run_philrice,
    run_philrice_news,
    run_pinoyrice,
)
from .index_jobs import run_corpus_rag_index_job, run_openstat_index_job
from .prism_jobs import run_prism_index, run_prism_scrape, run_prism_yield
from .release_jobs import run_corpus_backup_wasabi, run_corpus_release

__all__ = [
    "run_philrice",
    "run_philrice_news",
    "run_pinoyrice",
    "run_irri",
    "run_openstat",
    "run_prism_scrape",
    "run_prism_yield",
    "run_prism_index",
    "run_corpus_rag_index_job",
    "run_openstat_index_job",
    "run_corpus_release",
    "run_corpus_backup_wasabi",
]
