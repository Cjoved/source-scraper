"""Indexer orchestrator runners."""

from __future__ import annotations

from rich.console import Console

from src.indexing.corpus_rag_indexer import CorpusIndexStats, run_corpus_rag_index

console = Console()


def run_corpus_rag_index_job() -> CorpusIndexStats:
    console.rule("[bold cyan]Corpus RAG – Qdrant Index[/bold cyan]")
    stats = run_corpus_rag_index()
    console.print(f"[green]Indexed.[/green] total={stats.total_indexed}")
    for source_id, source_stats in stats.sources.items():
        console.print(
            f"  [dim]{source_id}:[/dim] read={source_stats.read} "
            f"indexed={source_stats.indexed} skipped={source_stats.skipped}"
        )
        for warning in source_stats.warnings:
            console.print(f"    [yellow]warn:[/yellow] {warning}")
    return stats


def run_openstat_index_job():
    from src.indexing.price_run import run_price_index

    console.rule("[bold cyan]OpenSTAT – Price Qdrant Index[/bold cyan]")
    stats = run_price_index()
    console.print(
        f"[green]Indexed.[/green] rows={stats.rows_seen} "
        f"records={stats.records_upserted} knowledge={stats.knowledge_upserted}"
    )
    return stats
