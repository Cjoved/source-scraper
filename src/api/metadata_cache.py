"""In-memory metadata cache for dropdown values used by the API.

The cache holds the distinct sets of years, semesters, regions, provinces,
and a `region -> provinces` map. It is built from the structured Qdrant
collection at startup and rebuilt on demand by the admin refresh route.

Reads are lock-free; refresh atomically replaces the held snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from src.api.schemas import SemesterCode, SemesterMetadata
from src.scraper.prism_constants import SEMESTERS


@dataclass(frozen=True)
class MetadataSnapshot:
    years: tuple[int, ...] = ()
    semesters: tuple[SemesterMetadata, ...] = ()
    regions: tuple[str, ...] = ()
    provinces_by_region: dict[str, tuple[str, ...]] = field(default_factory=dict)
    municipalities: tuple[str, ...] = ()

    @property
    def regions_count(self) -> int:
        return len(self.regions)

    @property
    def provinces_count(self) -> int:
        return sum(len(provs) for provs in self.provinces_by_region.values())

    @property
    def municipalities_count(self) -> int:
        return len(self.municipalities)

    @property
    def years_count(self) -> int:
        return len(self.years)


def _default_semesters() -> tuple[SemesterMetadata, ...]:
    return tuple(
        SemesterMetadata(code=SemesterCode(int(code)), label=label)
        for code, label in SEMESTERS
    )


class MetadataCache:
    """Lock-free snapshot holder; refresh swaps the snapshot atomically."""

    def __init__(self) -> None:
        self._snapshot = MetadataSnapshot(semesters=_default_semesters())
        self._lock = Lock()

    def get(self) -> MetadataSnapshot:
        return self._snapshot

    def set(self, snapshot: MetadataSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot


def build_snapshot_from_rows(rows: list[dict[str, object]]) -> MetadataSnapshot:
    """Compute a metadata snapshot from a list of normalized yield rows."""
    years: set[int] = set()
    regions: set[str] = set()
    municipalities: set[str] = set()
    provinces_by_region: dict[str, set[str]] = {}

    for row in rows:
        year_val = row.get("year")
        if isinstance(year_val, int):
            years.add(year_val)

        region = str(row.get("region") or "").strip()
        province = str(row.get("province") or "").strip()
        municipality = str(row.get("municipality") or "").strip()

        if region:
            regions.add(region)
            if province:
                provinces_by_region.setdefault(region, set()).add(province)
        if municipality:
            municipalities.add(municipality)

    return MetadataSnapshot(
        years=tuple(sorted(years)),
        semesters=_default_semesters(),
        regions=tuple(sorted(regions)),
        provinces_by_region={r: tuple(sorted(p)) for r, p in sorted(provinces_by_region.items())},
        municipalities=tuple(sorted(municipalities)),
    )
