"""OpenStat workflow runners (scrape then process)."""

from __future__ import annotations

from rich.console import Console

console = Console()


def run_philrice() -> None:
    from src.openstat.scrapers import philrice as scraper_philrice
    from src.openstat.services import philrice as processing_philrice

    console.rule("[bold cyan]PhilRice – PDF Scrape[/bold cyan]")
    scraper_philrice.run()
    console.rule("[bold cyan]PhilRice – PDF Process[/bold cyan]")
    processing_philrice.run()


def run_philrice_news() -> None:
    from src.openstat.scrapers import philrice_news as scraper_philrice_news
    from src.openstat.services import philrice_news as processing_philrice_news

    console.rule("[bold cyan]PhilRice News – Scrape[/bold cyan]")
    scraper_philrice_news.run()
    console.rule("[bold cyan]PhilRice News – Process[/bold cyan]")
    processing_philrice_news.run()


def run_pinoyrice() -> None:
    from src.openstat.scrapers import pinoyrice as scraper_pinoyrice
    from src.openstat.services import pinoyrice as processing_pinoyrice

    console.rule("[bold cyan]PinoyRice – Scrape[/bold cyan]")
    scraper_pinoyrice.run()
    console.rule("[bold cyan]PinoyRice – Process[/bold cyan]")
    processing_pinoyrice.run()


def run_irri() -> None:
    from src.openstat.scrapers import irri as irri_scraper
    from src.openstat.services import irri as processing_irri

    console.rule("[bold cyan]IRRI – Scrape[/bold cyan]")
    irri_scraper.run()
    console.rule("[bold cyan]IRRI – Process[/bold cyan]")
    processing_irri.run()


def run_openstat() -> None:
    from src.openstat.scrapers import openstat as openstat_scraper
    from src.openstat.services import openstat as processing_openstat

    console.rule("[bold cyan]OpenSTAT – Scrape[/bold cyan]")
    openstat_scraper.scrape_all()
    console.rule("[bold cyan]OpenSTAT – Process[/bold cyan]")
    processing_openstat.run()
