"""PRiSM map API — constants aligned with OpenStatv2."""

from __future__ import annotations

BASE_SITE = "https://prism.philrice.gov.ph"
PRISM_MAP_BASE = f"{BASE_SITE}/wp-dynamicreports/map"
REFERER_PAGE = f"{BASE_SITE}/wp-dynamicreports"

# CAR first, BARMM last — region IDs from loadprovince / getregionnum
REGION_ORDER: list[tuple[int, str]] = [
    (14, "CAR"),
    (1, "Region I"),
    (2, "Region II"),
    (3, "Region III"),
    (4, "CALABARZON"),
    (17, "MIMAROPA"),
    (5, "Region V"),
    (6, "Region VI"),
    (7, "Region VII"),
    (8, "Region VIII"),
    (9, "Region IX"),
    (10, "Region X"),
    (11, "Region XI"),
    (12, "Region XII"),
    (16, "Region XIII"),
    (15, "BARMM"),
]

SEMESTERS: list[tuple[str, str]] = [
    ("1", "1st Semester (Sept16-Mar15)"),
    ("2", "2nd Semester (Mar16-Sept15)"),
]

CSV_COLUMNS: list[str] = [
    "Year",
    "Semester",
    "Region",
    "Province",
    "Municipality",
    "Average Yield (ton/ha)",
    "Date and time of Scraping",
]
