"""Programmatic entry for indexing yield CSV into Qdrant (orchestrator + CLI)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from rich.console import Console

from src.api.settings import get_settings
from src.indexing.yield_indexer import IndexStats, run_indexer
from src.services.config import data_path
from src.storage.qdrant_store import QdrantStore

CollectionsChoice = Literal["all", "structured", "knowledge"]


def default_yield_csv_path() -> Path:
    settings = get_settings()
    return data_path(*settings.csv_source_relpath.split("/"))


def run_yield_index(
    *,
    csv_path: Path | None = None,
    collections: CollectionsChoice = "all",
    batch_size: int = 256,
    console: Console | None = None,
) -> IndexStats:
    """Index the yield CSV into Qdrant. Raises if CSV missing or indexing fails."""
    out = console or Console()
    settings = get_settings()
    path = csv_path or default_yield_csv_path()

    if not path.is_file():
        raise FileNotFoundError(f"Yield CSV not found: {path}")

    target_records = collections in ("all", "structured")
    target_knowledge = collections in ("all", "knowledge")

    out.print(f"[dim]CSV:[/dim] {path}")
    out.print(f"[dim]Qdrant URL:[/dim] {settings.qdrant_url}")
    out.print(
        f"[dim]Targets:[/dim] records={target_records}, knowledge={target_knowledge}"
    )

    store = QdrantStore(settings)
    return run_indexer(
        csv_path=path,
        store=store,
        settings=settings,
        target_records=target_records,
        target_knowledge=target_knowledge,
        batch_size=batch_size,
    )
