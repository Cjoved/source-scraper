"""In-memory metadata cache for OpenSTAT price filter dropdowns."""

from __future__ import annotations

from dataclasses import dataclass, field
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


def build_price_snapshot_from_rows(rows: list[dict[str, object]]) -> PriceMetadataSnapshot:
    """Compute a metadata snapshot from normalized OpenSTAT price rows."""
    years: set[int] = set()
    months: set[str] = set()
    geolocations: set[str] = set()
    commodity_types: set[str] = set()
    commodities_by_type: dict[str, set[str]] = {}

    for row in rows:
        year_val = row.get("year")
        try:
            if year_val is not None:
                years.add(int(year_val))
        except (TypeError, ValueError):
            pass

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

    return PriceMetadataSnapshot(
        years=tuple(sorted(years)),
        months=tuple(sorted(months)),
        geolocations=tuple(sorted(geolocations)),
        commodity_types=tuple(sorted(commodity_types)),
        commodities_by_type={
            ctype: tuple(sorted(items)) for ctype, items in sorted(commodities_by_type.items())
        },
    )
