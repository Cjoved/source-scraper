"""
Main entry: isa lang pwedeng tumakbo bawat run (PhilRice, PhilRice News, PinoyRice, OpenSTAT, o IRRI).
Control via .env: PHILRICE, PHILRICE_NEWS, PINOYRICE, OPENSTAT, IRRI, PRISM (true/false).
- PHILRICE=true: PhilRice PDF scrape -> process only.
- PHILRICE_NEWS=true: PhilRice News scrape -> process only (bukod sa PhilRice PDF).
- PINOYRICE=true: PinoyRice scrape (text + PDF) -> pinoyrice_corpus.jsonl.
- OPENSTAT=true: OpenSTAT scrape.
- IRRI=true: IRRI Philippines scrape (text + PDFs) -> data/irri_processed/text, data/irri_pdfs.
- PRISM=true: Prism scrape -> data/prism_processed, tapos process pipeline.
- PRISM=true + PRISM_JOB=export_yield_csv: buong PRiSM Yield table -> isang CSV (HTTP; walang process step).
"""
import os
from dotenv import load_dotenv

from src.openstat.env_flags import (
    irri_enabled,
    openstat_enabled,
    philrice_enabled,
    philrice_news_enabled,
    pinoyrice_enabled,
    prism_enabled,
)

load_dotenv()


def main():
    from rich.console import Console
    console = Console()

    console.rule("[bold]Main – PhilRice / PhilRice News / PinoyRice / OpenSTAT / IRRI / Prism (isa lang per run)[/bold]")
    philrice = philrice_enabled()
    philrice_news = philrice_news_enabled()
    pinoyrice = pinoyrice_enabled()
    openstat = openstat_enabled()
    irri = irri_enabled()
    prism = prism_enabled()
    console.print(f"[dim]PHILRICE={os.getenv('PHILRICE', 'false')}  PHILRICE_NEWS={os.getenv('PHILRICE_NEWS', 'false')}  PINOYRICE={os.getenv('PINOYRICE', 'false')}  OPENSTAT={os.getenv('OPENSTAT', 'true')}  IRRI={os.getenv('IRRI', 'false')}  PRISM={os.getenv('PRISM', 'false')}[/dim]")

    if philrice and (philrice_news or pinoyrice or openstat or irri or prism):
        console.print("[yellow]PhilRice (PDF) uuna (isa lang per run).[/yellow]")
        philrice_news = pinoyrice = openstat = irri = prism = False
    elif philrice_news and (pinoyrice or openstat or irri or prism):
        console.print("[yellow]PhilRice News uuna.[/yellow]")
        pinoyrice = openstat = irri = prism = False
    elif pinoyrice and (openstat or irri or prism):
        console.print("[yellow]PinoyRice uuna.[/yellow]")
        openstat = irri = prism = False
    elif openstat and (irri or prism):
        console.print("[yellow]OpenSTAT uuna.[/yellow]")
        irri = prism = False
    elif irri and prism:
        console.print("[yellow]IRRI uuna.[/yellow]")
        prism = False

    if philrice:
        console.rule("[bold cyan]PhilRice – PDF Scrape[/bold cyan]")
        from src.openstat.scrapers import philrice as scraper_philrice
        scraper_philrice.run()
        console.rule("[bold cyan]PhilRice – PDF Process (clean -> JSONL)[/bold cyan]")
        from src.openstat.services import philrice as processing_philrice
        processing_philrice.run()
    elif philrice_news:
        console.rule("[bold cyan]PhilRice News – Scrape[/bold cyan]")
        from src.openstat.scrapers import philrice_news as scraper_philrice_news
        from src.openstat.services import philrice_news as processing_philrice_news

        scraper_philrice_news.run()
        if processing_philrice_news.stream_process_enabled():
            console.print(
                "[dim]PHILRICE_NEWS_STREAM_PROCESS=true — corpus built during scrape.[/dim]"
            )
            console.rule("[bold cyan]PhilRice News – Process (leftovers)[/bold cyan]")
            processing_philrice_news.run(leftovers_only=True)
        else:
            console.rule("[bold cyan]PhilRice News – Process (.txt -> CPT JSON)[/bold cyan]")
            processing_philrice_news.run(leftovers_only=False)
    elif pinoyrice:
        console.rule("[bold cyan]PinoyRice – Scrape (text + PDF)[/bold cyan]")
        from src.openstat.scrapers import pinoyrice as scraper_pinoyrice
        scraper_pinoyrice.run()
        console.rule("[bold cyan]PinoyRice – Process (.txt/.pdf -> CPT JSON)[/bold cyan]")
        from src.openstat.services import pinoyrice as processing_pinoyrice
        processing_pinoyrice.run()
    elif openstat:
        console.rule("[bold cyan]OpenSTAT – Scrape[/bold cyan]")
        from src.openstat.scrapers import openstat as openstat_scraper
        openstat_scraper.scrape_all()
        console.rule("[bold cyan]OpenSTAT – Process (table + CPT)[/bold cyan]")
        from src.openstat.services import openstat as processing_openstat
        processing_openstat.run()
    elif irri:
        console.rule("[bold cyan]IRRI Philippines – Scrape (text + PDFs)[/bold cyan]")
        from src.openstat.scrapers import irri as irri_scraper
        irri_scraper.run()
        console.rule("[bold cyan]IRRI – Process (.txt → CPT JSON)[/bold cyan]")
        from src.openstat.services import irri as processing_irri
        processing_irri.run()
    elif prism:
        # Keep canonical PRiSM implementation from source-scraper.
        from src.scraper.prism import run as run_prism

        console.rule("[bold cyan]Prism – Canonical Source-Scraper Flow[/bold cyan]")
        run_prism()
    else:
        console.print("[yellow]Set PHILRICE=true, PHILRICE_NEWS=true, PINOYRICE=true, OPENSTAT=true, IRRI=true, o PRISM=true sa .env (isa lang per run).[/yellow]")

    console.rule("[bold green]Done[/bold green]")


if __name__ == "__main__":
    main()
