"""In-memory metadata cache for OpenSTAT price filter dropdowns."""

from __future__ import annotations

import csv
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock


@dataclass(frozen=True)
class PriceMetadataSnapshot:
    years: tuple[int, ...] = ()
    months: tuple[str, ...] = ()
    geolocations: tuple[str, ...] = ()
    commodity_types: tuple[str, ...] = ()
    commodities_by_type: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def years_count(self) -> int:
        return len(self.years)

    @property
    def geolocations_count(self) -> int:
        return len(self.geolocations)

    @property
    def commodities_count(self) -> int:
        return sum(len(items) for items in self.commodities_by_type.values())


class PriceMetadataCache:
    """Lock-free snapshot holder; refresh swaps the snapshot atomically."""

    def __init__(self) -> None:
        self._snapshot = PriceMetadataSnapshot()
        self._lock = Lock()

    def get(self) -> PriceMetadataSnapshot:
        return self._snapshot

    def set(self, snapshot: PriceMetadataSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot


def _finalize_price_sets(
    *,
    years: set[int],
    months: set[str],
    geolocations: set[str],
    commodity_types: set[str],
    commodities_by_type: dict[str, set[str]],
) -> PriceMetadataSnapshot:
    return PriceMetadataSnapshot(
        years=tuple(sorted(years)),
        months=tuple(sorted(months)),
        geolocations=tuple(sorted(geolocations)),
        commodity_types=tuple(sorted(commodity_types)),
        commodities_by_type={
            ctype: tuple(sorted(items)) for ctype, items in sorted(commodities_by_type.items())
        },
    )


def build_price_snapshot_from_rows(rows: list[dict[str, object]]) -> PriceMetadataSnapshot:
    """Compute a metadata snapshot from normalized OpenSTAT price rows."""
    years: set[int] = set()
    months: set[str] = set()
    geolocations: set[str] = set()
    commodity_types: set[str] = set()
    commodities_by_type: dict[str, set[str]] = {}

    for row in rows:
        year_val = row.get("year")
        if isinstance(year_val, int):
            years.add(year_val)
        elif isinstance(year_val, str):
            with suppress(ValueError):
                years.add(int(year_val))

        month = str(row.get("month") or "").strip()
        if month:
            months.add(month)

        geo = str(row.get("geolocation") or "").strip()
        if geo:
            geolocations.add(geo)

        ctype = str(row.get("commodity_type") or "").strip() or "(unspecified)"
        commodity_types.add(ctype)

        commodity = str(row.get("commodity") or "").strip()
        if commodity:
            commodities_by_type.setdefault(ctype, set()).add(commodity)

    return _finalize_price_sets(
        years=years,
        months=months,
        geolocations=geolocations,
        commodity_types=commodity_types,
        commodities_by_type=commodities_by_type,
    )


def build_price_snapshot_from_csv(csv_path: Path) -> PriceMetadataSnapshot:
    """Stream ``openstat_table.csv`` and collect distinct filter values only.

    Avoids a full Qdrant scroll over millions of indexed points. Only sets of
    distinct labels are kept in memory (not every row).
    """
    years: set[int] = set()
    months: set[str] = set()
    geolocations: set[str] = set()
    commodity_types: set[str] = set()
    commodities_by_type: dict[str, set[str]] = {}

    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            year_raw = (raw.get("Year") or "").strip()
            if year_raw:
                with suppress(ValueError):
                    years.add(int(float(year_raw)))

            month = (raw.get("Month") or "").strip()
            if month and month.lower() not in {"annual", "yearly", "year", "total"}:
                months.add(month)

            geo = (raw.get("Geolocation") or "").strip()
            if geo:
                geolocations.add(geo)

            ctype = (raw.get("Commodity Type") or "").strip() or "(unspecified)"
            commodity_types.add(ctype)

            commodity = (raw.get("Commodity") or ctype or "").strip()
            if commodity:
                commodities_by_type.setdefault(ctype, set()).add(commodity)

    return _finalize_price_sets(
        years=years,
        months=months,
        geolocations=geolocations,
        commodity_types=commodity_types,
        commodities_by_type=commodities_by_type,
    )
