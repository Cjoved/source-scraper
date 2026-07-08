from __future__ import annotations

import unittest

from src.utils.url_policy import UrlPolicyError, validate_http_url


class TestUrlPolicy(unittest.TestCase):
    def test_allows_known_psa_host(self) -> None:
        url = validate_http_url("https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/")
        self.assertTrue(url.startswith("https://openstat.psa.gov.ph"))

    def test_blocks_localhost(self) -> None:
        with self.assertRaises(UrlPolicyError):
            validate_http_url("http://localhost:6333/collections")

    def test_blocks_private_ip_literal(self) -> None:
        with self.assertRaises(UrlPolicyError):
            validate_http_url("http://192.168.1.10/internal")

    def test_blocks_unknown_host(self) -> None:
        with self.assertRaises(UrlPolicyError):
            validate_http_url("https://evil.example.com/")


if __name__ == "__main__":
    unittest.main()
