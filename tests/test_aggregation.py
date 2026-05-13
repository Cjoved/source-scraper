from __future__ import annotations

import unittest

from src.api.schemas import SemesterCode, SummaryScope
from src.services.aggregation import aggregate_rows


def _row(year: int, sem: int, value: float, municipality: str = "M") -> dict[str, object]:
    return {
        "year": year,
        "semester_code": sem,
        "region": "CAR",
        "province": "Abra",
        "municipality": municipality,
        "avg_yield_ton_ha": value,
    }


class TestAggregation(unittest.TestCase):
    def test_empty_rows(self) -> None:
        scope = SummaryScope(province="Abra")
        summary = aggregate_rows([], scope=scope)
        self.assertEqual(summary.overall.row_count, 0)
        self.assertEqual(summary.overall.municipality_count, 0)
        self.assertEqual(summary.by_year, [])
        self.assertEqual(summary.by_semester, [])

    def test_overall_and_groupings(self) -> None:
        rows = [
            _row(2019, 1, 3.0, "Bangued"),
            _row(2019, 2, 5.0, "Bucay"),
            _row(2020, 1, 4.0, "Bangued"),
            _row(2020, 2, 6.0, "Bucay"),
        ]
        summary = aggregate_rows(rows, scope=SummaryScope(province="Abra"))
        self.assertEqual(summary.overall.row_count, 4)
        self.assertEqual(summary.overall.municipality_count, 2)
        self.assertAlmostEqual(summary.overall.avg_yield_ton_ha, 4.5, places=4)

        by_year = {item.year: item.avg_yield_ton_ha for item in summary.by_year}
        self.assertAlmostEqual(by_year[2019], 4.0, places=4)
        self.assertAlmostEqual(by_year[2020], 5.0, places=4)

        by_sem = {
            (item.year, int(item.semester_code)): item.avg_yield_ton_ha
            for item in summary.by_semester
        }
        self.assertAlmostEqual(by_sem[(2019, 1)], 3.0, places=4)
        self.assertAlmostEqual(by_sem[(2020, 2)], 6.0, places=4)

        self.assertIsNotNone(summary.overall.min)
        self.assertIsNotNone(summary.overall.max)
        assert summary.overall.min is not None and summary.overall.max is not None
        self.assertEqual(summary.overall.min.value, 3.0)
        self.assertEqual(summary.overall.max.value, 6.0)
        self.assertEqual(summary.overall.min.semester_code, SemesterCode.FIRST)
        self.assertEqual(summary.overall.max.semester_code, SemesterCode.SECOND)

    def test_invalid_rows_ignored(self) -> None:
        rows = [
            _row(2020, 1, 3.0),
            {"year": "bad", "semester_code": 1, "avg_yield_ton_ha": 1.0},
            {"year": 2020, "semester_code": 3, "avg_yield_ton_ha": 1.0},
        ]
        summary = aggregate_rows(rows, scope=SummaryScope())
        self.assertEqual(summary.overall.row_count, 1)


if __name__ == "__main__":
    unittest.main()
