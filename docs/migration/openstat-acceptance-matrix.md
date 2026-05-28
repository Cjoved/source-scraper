# OpenStat Acceptance Matrix

Pass/fail matrix for parity validation after migration.

## Commands and Expected Artifacts

| Workflow | Run Command | Required Env | Expected Artifacts | Pass Criteria |
| --- | --- | --- | --- | --- |
| PhilRice PDF | `uv run python main.py openstat` | `PHILRICE=true` and other toggles false | `data/philrice_pdfs/*`, `data/philrice_processed/philrice_corpus.jsonl` | Crawl completes without crash and corpus contains new records |
| PhilRice News | `uv run python main.py openstat` | `PHILRICE_NEWS=true` and higher-priority toggles false | `data/philrice_news/*.txt`, `data/philrice_news_processed/philrice_news_corpus.jsonl` | Text files written and processed corpus updated |
| PinoyRice | `uv run python main.py openstat` | `PINOYRICE=true` and higher-priority toggles false | `data/pinoyrice_txt/*`, `data/pinoyrice_pdfs/*`, `data/pinoyrice_processed/pinoyrice_corpus.jsonl` | Scrape completes and corpus row count increases or checkpoint confirms no new records |
| OpenSTAT | `uv run python main.py openstat` | `OPENSTAT=true`, `URLS`, optional MySQL creds | `data/openstat_downloads/*`, checkpoint, desktop/openstat csv export | Scrape/download completes; CSV output generated; no fatal parse errors |
| IRRI | `uv run python main.py openstat` | `IRRI=true` and higher-priority toggles false | `data/irri_processed/text/*`, `data/irri_processed/irri_corpus.jsonl`, `data/irri_pdfs/*` | Scrape+process complete with expected outputs |
| PRISM (OpenStat compat) | `uv run python main.py openstat` | `PRISM=true`, `PRISM_URL` or `PRISM_URLS` | `data/prism_processed/prism_corpus.jsonl`, `data/checkpoints/prism_checkpoint.json` | Run completes and writes corpus/checkpoint |
| PRISM export (OpenStat compat) | `uv run python main.py openstat` | `PRISM=true`, `PRISM_JOB=export_yield_csv` | `data/prism_processed/prism_yield_export.csv`, checkpoint | CSV created with header and row data |

## Evidence Capture

For each workflow validation run:

1. Save command used and env block.
2. Record terminal summary (success/failure, runtime).
3. Record artifact paths and timestamps.
4. Store known non-blocking warnings separately from blocking failures.

