from __future__ import annotations

import unittest

from src.api.errors import ApiError, ErrorCode
from src.api.schemas import KnowledgeFilters, SemesterCode
from src.services.filters import build_yield_filter, filter_from_knowledge_filters


class TestBuildYieldFilter(unittest.TestCase):
    def test_strips_whitespace(self) -> None:
        flt = build_yield_filter(region="  CAR  ", province=" Abra ")
        self.assertEqual(flt.region, "CAR")
        self.assertEqual(flt.province, "Abra")

    def test_year_range_inverted(self) -> None:
        with self.assertRaises(ApiError) as ctx:
            build_yield_filter(year_min=2025, year_max=2020)
        self.assertEqual(ctx.exception.code, ErrorCode.INVALID_FILTER)

    def test_yield_range_inverted(self) -> None:
        with self.assertRaises(ApiError) as ctx:
            build_yield_filter(min_yield=5.0, max_yield=3.0)
        self.assertEqual(ctx.exception.code, ErrorCode.INVALID_FILTER)


class TestKnowledgeFilters(unittest.TestCase):
    def test_round_trips(self) -> None:
        kf = KnowledgeFilters(region="CAR", year_min=2018, year_max=2020, semester=SemesterCode.FIRST)
        flt = filter_from_knowledge_filters(kf)
        self.assertEqual(flt.region, "CAR")
        self.assertEqual(flt.year_min, 2018)
        self.assertEqual(flt.year_max, 2020)
        self.assertEqual(flt.semester, SemesterCode.FIRST)

    def test_none_yields_empty(self) -> None:
        flt = filter_from_knowledge_filters(None)
        self.assertIsNone(flt.region)
        self.assertIsNone(flt.semester)


if __name__ == "__main__":
    unittest.main()
