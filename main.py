"""CLI entry — loads .env and runs Prism scrapers."""

from dotenv import load_dotenv

from src.scraper.prism import run


def main() -> None:
    load_dotenv()
    run()


if __name__ == "__main__":
    main()
