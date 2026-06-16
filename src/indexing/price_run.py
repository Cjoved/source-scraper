"""Programmatic entry for indexing OpenSTAT price CSV into Qdrant."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from rich.console import Console

from src.api.settings import get_settings
from src.indexing.price_indexer import PriceIndexStats, run_price_indexer
from src.services.config import data_path
from src.storage.qdrant_store import QdrantStore

CollectionsChoice = Literal["all", "structured", "knowledge"]


def default_openstat_csv_path() -> Path:
    settings = get_settings()
    return data_path(*settings.openstat_csv_source_relpath.split("/"))


def run_price_index(
    *,
    csv_path: Path | None = None,
    collections: CollectionsChoice = "all",
    batch_size: int = 256,
    console: Console | None = None,
) -> PriceIndexStats:
    """Index the OpenSTAT table CSV into Qdrant. Raises if CSV missing."""
    out = console or Console()
    settings = get_settings()
    path = csv_path or default_openstat_csv_path()

    if not path.is_file():
        raise FileNotFoundError(f"OpenSTAT CSV not found: {path}")

    target_records = collections in ("all", "structured")
    target_knowledge = collections in ("all", "knowledge")

    out.print(f"[dim]CSV:[/dim] {path}")
    out.print(f"[dim]Qdrant URL:[/dim] {settings.qdrant_url}")
    out.print(
        f"[dim]Targets:[/dim] records={target_records}, knowledge={target_knowledge}"
    )

    store = QdrantStore(settings)
    return run_price_indexer(
        csv_path=path,
        store=store,
        settings=settings,
        target_records=target_records,
        target_knowledge=target_knowledge,
        batch_size=batch_size,
    )
