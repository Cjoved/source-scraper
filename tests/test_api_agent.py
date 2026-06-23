from __future__ import annotations

import unittest
from dataclasses import dataclass
from unittest.mock import patch

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
        self.assertEqual(body["warnings"], [])

    def test_agent_chat_validation(self) -> None:
        client, _fake = make_client()
        resp = client.post("/v1/agent/chat", json={"message": "", "mode": "tasklist"})

        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["error"]["code"], "VALIDATION_ERROR")


if __name__ == "__main__":
    unittest.main()
