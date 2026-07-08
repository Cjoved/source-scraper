from __future__ import annotations

import unittest

from src.agent.orchestrator import _effective_user_type
from src.api.auth import AuthScope
from src.api.schemas import AgentChatRequest, AgentMode, AgentUserType


class TestSecurityAuthGuards(unittest.TestCase):
    def test_client_admin_user_type_downgraded_without_privilege(self) -> None:
        body = AgentChatRequest(message="debug api", mode=AgentMode.CHAT, user_type=AgentUserType.ADMIN)
        effective = _effective_user_type(body, api_scope=AuthScope.PUBLIC, current_user=None)
        self.assertEqual(effective, "farmer")

    def test_admin_scope_preserves_admin_user_type(self) -> None:
        body = AgentChatRequest(message="debug api", mode=AgentMode.CHAT, user_type=AgentUserType.ADMIN)
        effective = _effective_user_type(body, api_scope=AuthScope.ADMIN, current_user=None)
        self.assertEqual(effective, "admin")


if __name__ == "__main__":
    unittest.main()
