"""Regex parsers for PRiSM yield map HTML responses."""

from __future__ import annotations

import html as html_module
import re


def parse_provinces(html: str) -> list[tuple[int, str]]:
    if not html:
        return []
    chunk = html.split("<script>", 1)[0]
    out: list[tuple[int, str]] = []
    for m in re.finditer(r'id="prov-(\d+)"[^>]*value="([^"]*)"', chunk):
        out.append((int(m.group(1)), m.group(2).strip()))
    return out


def parse_yield_rows(html: str) -> list[tuple[str, float]]:
    if not html:
        return []
    rows: list[tuple[str, float]] = []
    for m in re.finditer(
        r'<th\s+scope="row"[^>]*>([^<]+)</th>\s*<td[^>]*>\s*([\d.]+)',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        mun = html_module.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
        mun = mun.replace("\u00a0", " ").strip()
        mun = re.sub(r" +", " ", mun).strip()
        try:
            val = float(m.group(2))
        except ValueError:
            val = 0.0
        rows.append((mun, val))
    return rows
