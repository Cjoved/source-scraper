"""CLI entry point for indexing the yield CSV into Qdrant.

Examples:

    uv run python -m src.indexing.cli --collections all
    uv run python -m src.indexing.cli --collections structured
    uv run python -m src.indexing.cli --source path/to/custom.csv --batch-size 128
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from src.api.settings import get_settings
from src.indexing.yield_indexer import run_indexer
from src.services.config import data_path
from src.storage.qdrant_store import QdrantStore


def _default_csv_path() -> Path:
    settings = get_settings()
    parts = settings.csv_source_relpath.split("/")
    return data_path(*parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Index PRiSM yield CSV into Qdrant.")
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Path to the yield CSV (defaults to data/prism_processed/prism_yield_export.csv).",
    )
    parser.add_argument(
        "--collections",
        choices=("all", "structured", "knowledge"),
        default="all",
        help="Which collections to upsert into.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=256,
        help="Rows per upsert batch.",
    )

    args = parser.parse_args(argv)
    console = Console()
    settings = get_settings()
    csv_path = args.source or _default_csv_path()

    if not csv_path.is_file():
        console.print(f"[red]CSV not found:[/red] {csv_path}")
        return 1

    store = QdrantStore(settings)
    target_records = args.collections in ("all", "structured")
    target_knowledge = args.collections in ("all", "knowledge")

    console.rule("[bold cyan]PRiSM yield indexer[/bold cyan]")
    console.print(f"[dim]CSV:[/dim] {csv_path}")
    console.print(f"[dim]Qdrant URL:[/dim] {settings.qdrant_url}")
    console.print(
        f"[dim]Targets:[/dim] records={target_records}, knowledge={target_knowledge}"
    )

    stats = run_indexer(
        csv_path=csv_path,
        store=store,
        settings=settings,
        target_records=target_records,
        target_knowledge=target_knowledge,
        batch_size=args.batch_size,
    )

    console.print(
        f"[green]Done.[/green] rows={stats.rows_seen}, "
        f"records={stats.records_upserted}, knowledge={stats.knowledge_upserted}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
