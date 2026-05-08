"""Orchestrate full PRiSM yield CSV export (HTTP only)."""

from __future__ import annotations

import csv
import json
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.progress import Progress

from src.formatter.prism_yield_export import yield_checkpoint_key, yield_csv_row
from src.scraper.clients.prism_yield_http import PrismYieldHttpClient, YieldMapPoster
from src.scraper.parsers.prism_yield_html import parse_provinces, parse_yield_rows
from src.scraper.prism_constants import CSV_COLUMNS, REGION_ORDER, SEMESTERS


def load_yield_done_set(checkpoint_path: Path) -> set[str]:
    from src.services.checkpoint import load_json

    data = load_json(checkpoint_path, default={})
    return set(data.get("done") or [])


def save_yield_checkpoint(checkpoint_path: Path, done: set[str]) -> None:
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(json.dumps({"done": sorted(done)}, indent=2), encoding="utf-8")


def run_yield_export(
    *,
    csv_path: Path,
    checkpoint_path: Path,
    client: YieldMapPoster,
    year_min: int,
    year_max: int,
    cooldown_every: int,
    cooldown_seconds: float,
    console: Console | None = None,
) -> None:
    """Fetch provinces once per region, then all pending year×sem×province detail rows."""
    _console = console or Console()
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    done = load_yield_done_set(checkpoint_path)
    csv_exists = csv_path.is_file() and csv_path.stat().st_size > 0

    years = [str(y) for y in range(year_min, year_max + 1)]
    scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    region_provinces: dict[int, list[tuple[int, str]]] = {}
    for region_id, region_name in REGION_ORDER:
        html = client.post("loadprovince", {"regionid": region_id})
        client.polite_sleep()
        plist = parse_provinces(html or "")
        region_provinces[region_id] = plist
        if not plist:
            _console.print(f"[yellow]No provinces: region={region_name} (id={region_id})[/yellow]")

    pending: list[tuple[str, str, int, str, int, str]] = []
    for year in years:
        for sem_val, _sem_label in SEMESTERS:
            for region_id, region_name in REGION_ORDER:
                for prov_id, prov_name in region_provinces.get(region_id, []):
                    k = yield_checkpoint_key(year, sem_val, region_id, prov_id)
                    if k not in done:
                        pending.append((year, sem_val, region_id, region_name, prov_id, prov_name))

    _console.print(f"[dim]CSV: {csv_path}[/dim]")
    _console.print(f"[dim]Pending combinations: {len(pending)}[/dim]")
    if not pending:
        _console.print("[green]Nothing pending per checkpoint.[/green]")
        return

    mode = "a" if csv_exists else "w"
    with csv_path.open(mode, newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=CSV_COLUMNS)
        if not csv_exists:
            writer.writeheader()

        with Progress(console=_console) as progress:
            task = progress.add_task("Yield export", total=max(len(pending), 1))
            detail_requests = 0
            for year, sem_val, region_id, region_name, prov_id, prov_name in pending:
                if cooldown_every > 0 and detail_requests > 0 and detail_requests % cooldown_every == 0:
                    _console.print(
                        f"[dim]Cooldown {cooldown_seconds}s after {detail_requests} yield requests…[/dim]"
                    )
                    time.sleep(cooldown_seconds)

                detail = client.post(
                    "yield_province_details",
                    {"year": year, "sem": sem_val, "region": str(region_id), "province": str(prov_id)},
                )
                detail_requests += 1
                client.polite_sleep()
                rows = parse_yield_rows(detail or "")

                if not rows:
                    writer.writerow(
                        yield_csv_row(
                            year=year,
                            semester_label=next(l for v, l in SEMESTERS if v == sem_val),
                            region_name=region_name,
                            province_name=prov_name,
                            municipality="",
                            avg_yield="0",
                            scraped_at=scraped_at,
                        )
                    )
                else:
                    sem_label = next(l for v, l in SEMESTERS if v == sem_val)
                    for mun, avg in rows:
                        writer.writerow(
                            yield_csv_row(
                                year=year,
                                semester_label=sem_label,
                                region_name=region_name,
                                province_name=prov_name,
                                municipality=mun,
                                avg_yield=str(avg),
                                scraped_at=scraped_at,
                            )
                        )

                done.add(yield_checkpoint_key(year, sem_val, region_id, prov_id))
                save_yield_checkpoint(checkpoint_path, done)
                progress.advance(task)

    _console.print(f"[green]Done. CSV:[/green] {csv_path}")
