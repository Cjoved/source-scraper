import csv
import io
import tempfile
import unittest
from pathlib import Path

from rich.console import Console

from src.formatter.prism_yield_export import yield_checkpoint_key
from src.scraper.prism_constants import REGION_ORDER
from src.scraper.prism_urls import normalize_prism_target_url, parse_seed_urls
from src.scraper.parsers.prism_yield_html import parse_provinces, parse_yield_rows
from src.scraper.spiders.prism_yield_runner import run_yield_export


class FakeYieldClient:
    def __init__(self) -> None:
        self.post_calls: list[tuple[str, dict[str, object]]] = []

    def polite_sleep(self) -> None:
        pass

    def post(self, path: str, data: dict[str, object]) -> str | None:
        self.post_calls.append((path, dict(data)))
        if path == "loadprovince":
            rid = int(data["regionid"])
            if rid == 14:
                return '<div id="prov-101" value="TestProv"></div>'
            return ""
        if path == "yield_province_details":
            return (
                "<table><tbody>"
                '<tr><th scope="row">Town A</th><td>3.5</td></tr>'
                "</tbody></table>"
            )
        return None


class TestPrismUrls(unittest.TestCase):
    def test_parse_seed_urls_splits_commas(self) -> None:
        raw = "https://a.example/x, https://b.example/y"
        self.assertEqual(parse_seed_urls(raw), ["https://a.example/x", "https://b.example/y"])

    def test_normalize_dataproducts(self) -> None:
        u = "https://prism.philrice.gov.ph/dataproducts/"
        out = normalize_prism_target_url(u, rewrite_dataproducts=True)
        self.assertEqual(out, "https://prism.philrice.gov.ph/wp-dynamicreports")


class TestPrismYieldHtml(unittest.TestCase):
    def test_parse_provinces(self) -> None:
        html = '<div id="prov-12" value="Abra"></div><script>ignore()</script>'
        self.assertEqual(parse_provinces(html), [(12, "Abra")])

    def test_parse_yield_rows(self) -> None:
        html = '<tr><th scope="row">Sample Mun</th><td> 2.25 </td></tr>'
        rows = parse_yield_rows(html)
        self.assertEqual(rows, [("Sample Mun", 2.25)])

    def test_parse_yield_rows_nbsp(self) -> None:
        html = '<tr><th scope="row">Town&nbsp;A</th><td>1.0</td></tr>'
        self.assertEqual(parse_yield_rows(html), [("Town A", 1.0)])


class TestYieldExportRunner(unittest.TestCase):
    def test_writes_csv_and_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            csv_path = tmp / "y.csv"
            ck_path = tmp / "ck.json"

            fake = FakeYieldClient()
            console = Console(file=io.StringIO(), force_terminal=False, width=120)
            run_yield_export(
                csv_path=csv_path,
                checkpoint_path=ck_path,
                client=fake,
                year_min=2024,
                year_max=2024,
                cooldown_every=0,
                cooldown_seconds=0.0,
                console=console,
            )

            self.assertEqual(len(fake.post_calls), len(REGION_ORDER) + 2)

            text = csv_path.read_text(encoding="utf-8")
            reader = list(csv.DictReader(text.splitlines()))
            self.assertGreaterEqual(len(reader), 2)
            self.assertTrue(any(r["Municipality"] == "Town A" for r in reader))

            ck = ck_path.read_text(encoding="utf-8")
            self.assertIn(yield_checkpoint_key("2024", "1", 14, 101), ck)
            self.assertIn(yield_checkpoint_key("2024", "2", 14, 101), ck)

            fake2 = FakeYieldClient()
            run_yield_export(
                csv_path=csv_path,
                checkpoint_path=ck_path,
                client=fake2,
                year_min=2024,
                year_max=2024,
                cooldown_every=0,
                cooldown_seconds=0.0,
                console=console,
            )
            self.assertEqual(len(fake2.post_calls), len(REGION_ORDER))


if __name__ == "__main__":
    unittest.main()
