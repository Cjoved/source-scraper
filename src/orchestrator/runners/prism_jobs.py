"""PRiSM workflow runners."""

from __future__ import annotations

from rich.console import Console

console = Console()


def run_prism_scrape() -> None:
    from src.scraper.prism_browser_config import load_prism_browser_config
    from src.scraper.spiders.prism_browser_runner import run_browser_scrape
    from src.services.prism import run as run_prism_process

    console.rule("[bold cyan]PRiSM – Browser Scrape[/bold cyan]")
    run_browser_scrape(load_prism_browser_config())
    console.rule("[bold cyan]PRiSM – Process[/bold cyan]")
    run_prism_process()


def run_prism_yield() -> None:
    from src.scraper.prism import run_yield_export_job

    console.rule("[bold cyan]PRiSM – Yield CSV Export[/bold cyan]")
    run_yield_export_job(console)


def run_prism_index() -> None:
    from src.indexing.run import run_yield_index

    console.rule("[bold cyan]PRiSM – Qdrant Index[/bold cyan]")
    stats = run_yield_index(console=console)
    console.print(
        f"[green]Indexed.[/green] rows={stats.rows_seen}, "
        f"records={stats.records_upserted}, knowledge={stats.knowledge_upserted}"
    )
