"""CSV row shaping for PRiSM yield export."""

from __future__ import annotations

def yield_checkpoint_key(year: str, sem: str, region_id: int, prov_id: int) -> str:
    return f"{year}|{sem}|{region_id}|{prov_id}"


def yield_csv_row(
    *,
    year: str,
    semester_label: str,
    region_name: str,
    province_name: str,
    municipality: str,
    avg_yield: str,
    scraped_at: str,
) -> dict[str, str]:
    return {
        "Year": year,
        "Semester": semester_label,
        "Region": region_name,
        "Province": province_name,
        "Municipality": municipality,
        "Average Yield (ton/ha)": avg_yield,
        "Date and time of Scraping": scraped_at,
    }


__all__ = ["yield_checkpoint_key", "yield_csv_row"]
