"""Tests for universal corpus JSONL validation (P3.1)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.scripts.validate_corpus import (
    SOURCE_BY_ID,
    validate_jsonl_file,
    run_validation,
)


class ValidateJsonlFileTests(unittest.TestCase):
    def _write(self, path: Path, records: list[dict]) -> None:
        lines = [json.dumps(r, ensure_ascii=False) for r in records]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_valid_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ok.jsonl"
            self._write(
                p,
                [
                    {
                        "text": "Hello world " * 10,
                        "input": "Hello world " * 10,
                        "content": "Hello world " * 10,
                        "source": "philrice",
                        "doc_id": "doc1",
                    }
                ],
            )
            rep = validate_jsonl_file(p, source_id="test", check_quality=True, min_text_chars=10)
            self.assertEqual(rep.status, "ok")
            self.assertEqual(rep.records, 1)

    def test_missing_doc_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.jsonl"
            self._write(
                p,
                [{"text": "x", "input": "x", "source": "philrice"}],
            )
            rep = validate_jsonl_file(p, source_id="test")
            self.assertEqual(rep.status, "failed")
            self.assertTrue(any("doc_id" in e for e in rep.errors))

    def test_text_input_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.jsonl"
            self._write(
                p,
                [{"text": "a", "input": "b", "source": "x", "doc_id": "1"}],
            )
            rep = validate_jsonl_file(p, source_id="test")
            self.assertEqual(rep.status, "failed")

    def test_duplicate_doc_id_with_quality(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "dup.jsonl"
            rec = {
                "text": "same text " * 20,
                "input": "same text " * 20,
                "source": "irri",
                "doc_id": "dup_id",
            }
            self._write(p, [rec, rec])
            rep = validate_jsonl_file(p, source_id="test", check_quality=True, min_text_chars=10)
            self.assertEqual(rep.status, "failed")
            self.assertIn("dup_id", rep.duplicate_doc_ids)

    def test_missing_file_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "missing.jsonl"
            rep = validate_jsonl_file(p, source_id="test")
            self.assertEqual(rep.status, "skipped")

    def test_split_physical_lines_still_validate(self) -> None:
        """Records split across physical lines (sync/wrap artifacts) should still parse."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "wrapped.jsonl"
            text = "Hello " * 400
            record = {
                "text": text,
                "input": text,
                "source": "philrice",
                "doc_id": "wrapped_doc",
            }
            line = json.dumps(record, ensure_ascii=False)
            # Simulate a mid-record line break (like OneDrive/sync wrapping one JSONL line).
            mid = len(line) // 2
            p.write_text(line[:mid] + "\n" + line[mid:] + "\n", encoding="utf-8")
            rep = validate_jsonl_file(p, source_id="test", min_text_chars=10, check_quality=True)
            self.assertEqual(rep.status, "ok")
            self.assertEqual(rep.records, 1)
            self.assertTrue(any("spans physical lines" in w for w in rep.warnings))


class RunValidationTests(unittest.TestCase):
    def test_single_source_filter(self) -> None:
        reports, code = run_validation(source_filter="philrice", strict=False)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].source_id, "philrice")
        # missing file on fresh clone => skip, exit 0
        if reports[0].status == "skipped":
            self.assertEqual(code, 0)

    def test_openstat_lines_min_text_chars_spec(self) -> None:
        spec = SOURCE_BY_ID["openstat_lines"]
        self.assertEqual(spec.min_text_chars, 80)
        # Typical OpenSTAT CPT lines are ~90–110 chars; global default 100 was too strict.
        borderline = "x" * 95
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "openstat.jsonl"
            rec = {
                "text": borderline,
                "input": borderline,
                "content": borderline,
                "source": "openstat",
                "doc_id": "openstat_test_1",
            }
            p.write_text(json.dumps(rec) + "\n", encoding="utf-8")
            rep = validate_jsonl_file(
                p, source_id="openstat_lines", check_quality=True, min_text_chars=80
            )
            self.assertEqual(rep.status, "ok")

    def test_unknown_source_raises(self) -> None:
        with self.assertRaises(ValueError):
            run_validation(source_filter="not_a_source")


if __name__ == "__main__":
    unittest.main()
