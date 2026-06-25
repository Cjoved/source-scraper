# CPT corpus JSONL — data format spec

All scrape+process pipelines in this repo emit **JSON Lines** (one JSON object per line) for continued pre-training (CPT) and downstream RAG indexing (see P3.8).

Validator: `uv run python -m src.scripts.validate_corpus`

---

## Canonical record shape

Built by `make_cpt_record()` in `src/utils/cpt.py`. Every line MUST be a JSON object with:

| Field | Type | Required | Rules |
|-------|------|----------|--------|
| `text` | string | yes | Non-empty after strip |
| `input` | string | yes | Must equal `text` exactly |
| `content` | string | no | If present, must equal `text` |
| `source` | string | yes | Non-empty slug (e.g. `philrice`, `openstat`) |
| `doc_id` | string | yes | Non-empty, unique within a file (see quality checks) |
| `url` | string | no | |
| `title` | string | no | |
| `filename` | string | no | |
| `page` | integer | no | PDF page number when applicable |

**Source-specific fields** (optional, allowed extra keys):

- **openstat:** `geolocation`, `commodity`, `commodity_type`, `year`, `month`, `price`
- Other pipelines may add metadata; validators only enforce the canonical core.

---

## Registered corpus files

Paths are relative to `data/`:

| Source ID | Path | Notes |
|-----------|------|--------|
| `philrice` | `philrice_processed/philrice_corpus.jsonl` | PDF pipeline |
| `philrice_news` | `philrice_news_processed/philrice_news_corpus.jsonl` | News .txt |
| `pinoyrice` | `pinoyrice_processed/pinoyrice_corpus.jsonl` | Portal text |
| `pinoyrice_chunked` | `pinoyrice_processed/pinoyrice_corpus_chunked.jsonl` | Chunked variant |
| `pinoyrice_pdfs` | `pinoyrice_processed/pinoyrice_pdfs_corpus.jsonl` | PDF branch |
| `irri` | `irri_processed/irri_corpus.jsonl` | IRRI Philippines |
| `openstat_lines` | `openstat_processed/openstat_corpus.jsonl` | PSA farmgate CPT only (`OPENSTAT_WRITE_LINE_CORPUS=true`; not RAG-indexed) |

**Structured tabular (not JSONL):** `openstat_processed/openstat_table.csv` — indexed into Qdrant via `openstat_index` (`openstat_price_records`, `openstat_price_knowledge`); queried via `GET /v1/prices/*`.
| `prism` | `prism_processed/prism_corpus.jsonl` | Raw browser corpus |
| `prism_browser` | `prism_processed/prism_corpus_chunked.jsonl` | Chunked for training/RAG (indexed as `prism_browser`) |

Yield export **`prism_yield_export.csv`** is not JSONL — validated separately (tabular / API indexer).

---

## File-level rules

- UTF-8 encoding
- One JSON object per non-empty line
- Blank lines are ignored but counted for empty-line ratio (quality check)
- File may be missing before first run — use `validate_corpus --strict` to fail on missing paths

---

## Quality checks (optional, `--quality`)

Aligned with Phase 3 task P3.5:

- **Min text length:** default 100 characters (override: `VALIDATE_MIN_TEXT_CHARS`); per-source overrides in `validate_corpus.py`: PhilRice PDF **80**, OpenSTAT **80**
- **Max empty-line ratio:** default 5% of physical lines (`VALIDATE_MAX_EMPTY_LINE_PCT`)
- **Duplicate `doc_id`:** any duplicate IDs within the same file fail validation

Orchestrator runs enable quality checks by default (`ORCHESTRATOR_VALIDATE_QUALITY=true`). Set to `false` for format-only validation after scrape jobs.

Format checks always run; quality checks only with `--quality` (CLI) or when orchestrator quality toggle is on.
