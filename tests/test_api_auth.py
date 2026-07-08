from __future__ import annotations

import os
import unittest
from unittest import mock
from unittest.mock import patch

from src.api.settings import Settings, get_settings
from tests.helpers import make_client


class TestApiAuth(unittest.TestCase):
    def setUp(self) -> None:
        get_settings.cache_clear()

    def tearDown(self) -> None:
        os.environ["APP_ENV"] = "test"
        os.environ["API_AUTH_DISABLED"] = "true"
        os.environ["AGENT_ALLOW_PUBLIC"] = "false"
        get_settings.cache_clear()

    def test_auth_disabled_blocked_in_production_profile(self) -> None:
        with self.assertRaises(ValueError):
            Settings(
                app_env="production",
                api_auth_disabled=True,
                api_keys_public="pub",
                api_keys_admin="adm",
            )

    def test_auth_enabled_requires_keys(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "APP_ENV": "test",
                "API_AUTH_DISABLED": "false",
                "API_KEYS_PUBLIC": "",
                "API_KEYS_ADMIN": "",
            },
            clear=False,
        ):
            with self.assertRaises(ValueError):
                Settings()

    def test_missing_api_key_returns_401(self) -> None:
        os.environ["APP_ENV"] = "test"
        os.environ["API_AUTH_DISABLED"] = "false"
        os.environ["API_KEYS_PUBLIC"] = "pub-test-key"
        os.environ["API_KEYS_ADMIN"] = "adm-test-key"
        get_settings.cache_clear()
        client, _fake = make_client()
        resp = client.get("/v1/yield/metadata")
        self.assertEqual(resp.status_code, 401)

    def test_public_key_allows_read_not_admin(self) -> None:
        os.environ["APP_ENV"] = "test"
        os.environ["API_AUTH_DISABLED"] = "false"
        os.environ["AGENT_ALLOW_PUBLIC"] = "false"
        get_settings.cache_clear()
        client, _fake = make_client()
        headers = {"X-API-Key": "pub-test-key"}

        ok = client.get("/v1/yield/metadata", headers=headers)
        self.assertEqual(ok.status_code, 200)

        denied = client.get("/v1/index/status", headers=headers)
        self.assertEqual(denied.status_code, 403)

    def test_agent_requires_admin_or_agent_key_by_default(self) -> None:
        os.environ["APP_ENV"] = "test"
        os.environ["API_AUTH_DISABLED"] = "false"
        os.environ["AGENT_ALLOW_PUBLIC"] = "false"
        get_settings.cache_clear()
        client, _fake = make_client()

        with patch("src.agent.orchestrator.create_chat_model") as mock_model:
            from tests.test_api_agent import FakeModel

            mock_model.return_value = FakeModel()
            denied = client.post(
                "/v1/agent/chat",
                headers={"X-API-Key": "pub-test-key"},
                json={"message": "hello", "mode": "chat"},
            )
            self.assertEqual(denied.status_code, 403)

            allowed = client.post(
                "/v1/agent/chat",
                headers={"X-API-Key": "adm-test-key"},
                json={"message": "hello", "mode": "chat"},
            )
            self.assertEqual(allowed.status_code, 200)


if __name__ == "__main__":
    unittest.main()
