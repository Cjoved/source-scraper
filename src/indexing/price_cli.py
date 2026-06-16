"""CLI entry point for indexing OpenSTAT price CSV into Qdrant.

Examples:

    uv run python -m src.indexing.price_cli --collections all
    uv run python -m src.indexing.price_cli --collections structured
    uv run python -m src.indexing.price_cli --source path/to/openstat_table.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from src.indexing.price_run import default_openstat_csv_path, run_price_index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Index OpenSTAT price CSV into Qdrant.")
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Path to openstat_table.csv (defaults to data/openstat_processed/openstat_table.csv).",
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
    csv_path = args.source or default_openstat_csv_path()

    if not csv_path.is_file():
        console.print(f"[red]CSV not found:[/red] {csv_path}")
        return 1

    console.rule("[bold cyan]OpenSTAT price indexer[/bold cyan]")

    stats = run_price_index(
        csv_path=csv_path,
        collections=args.collections,
        batch_size=args.batch_size,
        console=console,
    )

    console.print(
        f"[green]Done.[/green] rows={stats.rows_seen}, "
        f"records={stats.records_upserted}, knowledge={stats.knowledge_upserted}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
