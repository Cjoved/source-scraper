"""Phase 5 release + Wasabi backup jobs (P5.1–P5.5)."""

from __future__ import annotations

from rich.console import Console

console = Console()

_PHASE5_MSG = (
    "Phase 5 not implemented yet — see AUTOMATION_TASKLIST.txt (P5.1–P5.5) "
    "and docs/SCHEDULER_SETUP.md § Production delivery."
)


def run_corpus_release() -> None:
    """Build data/releases/YYYY-MM-DD/ bundle + RELEASE_NOTES.md (P5.1, P5.2, P5.5)."""
    raise NotImplementedError(_PHASE5_MSG)


def run_corpus_backup_wasabi() -> None:
    """Upload latest release bundle to Wasabi S3-compatible storage (P5.4)."""
    raise NotImplementedError(_PHASE5_MSG)
