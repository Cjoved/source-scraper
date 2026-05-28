# OpenStat Feature Inventory

Status tracker for parity-first migration into `source-scraper`.

## Workflow Inventory

| Workflow | Source Module | Priority | Status | Notes |
| --- | --- | --- | --- | --- |
| PhilRice PDF scrape + process | `src/openstat/scrapers/philrice.py`, `src/openstat/services/philrice.py` | must-keep | migrated | Driven by `PHILRICE=true` in OpenStat runner |
| PhilRice News scrape + process | `src/openstat/scrapers/philrice_news.py`, `src/openstat/services/philrice_news.py` | must-keep | migrated | Driven by `PHILRICE_NEWS=true` |
| PinoyRice scrape + process | `src/openstat/scrapers/pinoyrice.py`, `src/openstat/services/pinoyrice.py` | must-keep | migrated | Driven by `PINOYRICE=true` |
| OpenSTAT scrape + Excel process | `src/openstat/scrapers/openstat.py`, `src/openstat/services/openstat.py` | must-keep | migrated | Driven by `OPENSTAT=true` |
| IRRI scrape + process | `src/openstat/scrapers/irri.py`, `src/openstat/services/irri.py` | must-keep | migrated | Driven by `IRRI=true` |
| OpenStat PRISM scrape path | `src/openstat/scrapers/prism.py`, `src/openstat/services/prism.py` | optional | migrated | Canonical PRISM remains in `src/scraper/*` |
| OpenStat PRISM yield export path | `src/openstat/scrapers/prism_yield_export.py` | optional | migrated | Existing canonical flow in `src/scraper/spiders/prism_yield_runner.py` |
| Inspector scripts | `src/openstat/scripts/*.py` | optional | migrated | For manual validation and diagnostics |

## Ownership Rules

- Canonical PRISM modules remain under `src/scraper/*`.
- OpenStat parity modules live under `src/openstat/*` and are run via `python main.py openstat`.
- Any overlapping PRISM behavior in `src/openstat` is kept for compatibility only.

