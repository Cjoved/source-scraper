
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class PrismBrowserConfig:
    urls_raw: str
    scrapling_mode: str
    headless: bool
    delay_page: float
    min_content_len: int
    resume_checkpoint: bool
    impersonate: str
    use_http3: bool
    solve_cloudflare: bool
    content_selector: str
    adaptive: bool
    auto_save: bool
    stealth_fetcher_adaptive: bool
    rewrite_dataproducts: bool
    js_settle_seconds: float
    # Save JSONL + mirror .txt when True.
    save_corpus: bool
    # Extract HTML tables under content selectors → CSV.
    export_tables_csv: bool
    tables_csv_path: Path
    table_max_cols: int
    jsonl_path: Path
    txt_dir: Path
    pdfs_dir: Path
    checkpoint_path: Path