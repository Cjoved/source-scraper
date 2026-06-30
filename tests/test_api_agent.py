from __future__ import annotations

import os
import time
import unittest
from dataclasses import dataclass
from unittest.mock import patch

import jwt

from src.api.auth import get_current_user_optional
from src.api.settings import Settings
from tests.helpers import make_client


@dataclass
class FakeMessage:
    content: str


class FakeModel:
    def invoke(self, input: object, config: object | None = None, **kwargs: object) -> FakeMessage:
        del input, config, kwargs
        return FakeMessage(
            '{"answer": "Narito ang API tasklist.", '
            '"tasklist": [{"status": "pending", "task": "Check the agent route."}]}'
        )


class TestAgentRoute(unittest.TestCase):
    jwt_secret = "test-secret-value-that-is-at-least-32-bytes"

    def _jwt(self, *, secret: str | None = None, **claims: object) -> str:
        payload = {"sub": "user-123", "exp": int(time.time()) + 300, **claims}
        return jwt.encode(payload, secret or self.jwt_secret, algorithm="HS256")

    def test_agent_chat_tasklist(self) -> None:
        client, _fake = make_client()
        with patch("src.agent.orchestrator.create_chat_model", return_value=FakeModel()):
            resp = client.post(
                "/v1/agent/chat",
                json={"message": "Gawan mo ako ng tasklist", "mode": "tasklist"},
            )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["answer"], "Narito ang API tasklist.")
        self.assertEqual(body["tasklist"][0]["task"], "Check the agent route.")
        self.assertEqual(body["confidence"], "low")
        self.assertIn("sources", body)
        self.assertIn("tool_calls", body)
        self.assertEqual(body["warnings"], [])

    def test_agent_chat_validation(self) -> None:
        client, _fake = make_client()
        resp = client.post("/v1/agent/chat", json={"message": "", "mode": "tasklist"})

        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["error"]["code"], "VALIDATION_ERROR")

    def test_agent_chat_rejects_long_message(self) -> None:
        client, _fake = make_client()
        resp = client.post("/v1/agent/chat", json={"message": "x" * 4001, "mode": "chat"})

        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["error"]["code"], "VALIDATION_ERROR")

    def test_agent_chat_rejects_invalid_mode(self) -> None:
        client, _fake = make_client()
        resp = client.post("/v1/agent/chat", json={"message": "hello", "mode": "data"})

        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["error"]["code"], "VALIDATION_ERROR")

    def test_agent_chat_rejects_too_many_source_ids(self) -> None:
        client, _fake = make_client()
        resp = client.post(
            "/v1/agent/chat",
            json={"message": "latest news", "mode": "chat", "source_ids": [f"source_{idx}" for idx in range(11)]},
        )

        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["error"]["code"], "VALIDATION_ERROR")

    def test_agent_chat_allows_missing_jwt_when_disabled(self) -> None:
        with patch.dict(os.environ, {"JWT_AUTH_ENABLED": "false"}):
            client, _fake = make_client()
            with patch("src.agent.orchestrator.create_chat_model", return_value=FakeModel()):
                resp = client.post(
                    "/v1/agent/chat",
                    json={"message": "Gawan mo ako ng tasklist", "mode": "tasklist"},
                )

        self.assertEqual(resp.status_code, 200)

    def test_agent_chat_allows_missing_jwt_when_optional(self) -> None:
        with patch.dict(
            os.environ,
            {
                "JWT_AUTH_ENABLED": "true",
                "JWT_REQUIRED_FOR_AGENT": "false",
                "JWT_SECRET": self.jwt_secret,
            },
        ):
            client, _fake = make_client()
            with patch("src.agent.orchestrator.create_chat_model", return_value=FakeModel()):
                resp = client.post(
                    "/v1/agent/chat",
                    json={"message": "Gawan mo ako ng tasklist", "mode": "tasklist"},
                )

        self.assertEqual(resp.status_code, 200)

    def test_agent_chat_rejects_missing_jwt_when_required(self) -> None:
        with patch.dict(
            os.environ,
            {
                "JWT_AUTH_ENABLED": "true",
                "JWT_REQUIRED_FOR_AGENT": "true",
                "JWT_SECRET": self.jwt_secret,
            },
        ):
            client, _fake = make_client()
            resp = client.post(
                "/v1/agent/chat",
                json={"message": "hello", "mode": "chat"},
            )

        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "UNAUTHORIZED")

    def test_agent_chat_accepts_valid_jwt_when_required(self) -> None:
        token = self._jwt()
        with patch.dict(
            os.environ,
            {
                "JWT_AUTH_ENABLED": "true",
                "JWT_REQUIRED_FOR_AGENT": "true",
                "JWT_SECRET": self.jwt_secret,
            },
        ):
            client, _fake = make_client()
            with patch("src.agent.orchestrator.create_chat_model", return_value=FakeModel()):
                resp = client.post(
                    "/v1/agent/chat",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "message": "Gawan mo ako ng tasklist",
                        "mode": "tasklist",
                        "session_id": "demo-session",
                    },
                )

        self.assertEqual(resp.status_code, 200)

    def test_agent_chat_rejects_invalid_jwt(self) -> None:
        token = self._jwt(secret="wrong-secret-value-that-is-at-least-32-bytes")
        with patch.dict(
            os.environ,
            {
                "JWT_AUTH_ENABLED": "true",
                "JWT_REQUIRED_FOR_AGENT": "true",
                "JWT_SECRET": self.jwt_secret,
            },
        ):
            client, _fake = make_client()
            resp = client.post(
                "/v1/agent/chat",
                headers={"Authorization": f"Bearer {token}"},
                json={"message": "hello", "mode": "chat"},
            )

        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "UNAUTHORIZED")

    def test_agent_chat_rejects_expired_jwt(self) -> None:
        token = self._jwt(exp=int(time.time()) - 10)
        with patch.dict(
            os.environ,
            {
                "JWT_AUTH_ENABLED": "true",
                "JWT_REQUIRED_FOR_AGENT": "true",
                "JWT_SECRET": self.jwt_secret,
            },
        ):
            client, _fake = make_client()
            resp = client.post(
                "/v1/agent/chat",
                headers={"Authorization": f"Bearer {token}"},
                json={"message": "hello", "mode": "chat"},
            )

        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "UNAUTHORIZED")

    def test_jwt_dependency_extracts_user_context(self) -> None:
        token = self._jwt(role="farmer", tenant_id="digisaka", scope="chat read")
        user = get_current_user_optional(
            authorization=f"Bearer {token}",
            settings=Settings(jwt_auth_enabled=True, jwt_secret=self.jwt_secret),
        )

        self.assertIsNotNone(user)
        assert user is not None
        self.assertEqual(user.user_id, "user-123")
        self.assertEqual(user.role, "farmer")
        self.assertEqual(user.tenant_id, "digisaka")
        self.assertEqual(user.scopes, ("chat", "read"))

    def test_agent_chat_rejects_body_user_id_spoofing(self) -> None:
        client, _fake = make_client()
        resp = client.post(
            "/v1/agent/chat",
            json={"message": "hello", "mode": "chat", "user_id": "fake-user"},
        )

        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["error"]["code"], "VALIDATION_ERROR")

    def test_agent_chat_rejects_non_string_source_id(self) -> None:
        client, _fake = make_client()
        resp = client.post(
            "/v1/agent/chat",
            json={"message": "latest news", "mode": "chat", "source_ids": ["irri", 123]},
        )

        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["error"]["code"], "VALIDATION_ERROR")


if __name__ == "__main__":
    unittest.main()
