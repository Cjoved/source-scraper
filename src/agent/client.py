"""LangChain chat model factory for the API agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import SecretStr

from src.api.settings import Settings


class AgentClientError(RuntimeError):
    """Configuration or provider error surfaced as a response warning."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AgentModelConfig:
    provider: str
    model: str
    api_key: str
    base_url: str | None
    timeout: float


def _default_model(provider: str) -> str:
    if provider == "kimi":
        return "kimi-k2.5"
    if provider == "openai_compatible":
        return "openai-compatible-model"
    return "deepseek-chat"


def resolve_model_config(settings: Settings) -> AgentModelConfig:
    provider = settings.agent_provider
    api_key = (settings.agent_api_key or "").strip()
    if not api_key:
        raise AgentClientError(
            "agent_api_key_missing",
            "Set AGENT_API_KEY before enabling LangChain model calls.",
        )

    model = settings.agent_model.strip() or _default_model(provider)
    base_url = settings.agent_base_url.strip() or None
    if provider == "openai_compatible" and not base_url:
        raise AgentClientError(
            "agent_base_url_missing",
            "Set AGENT_BASE_URL when AGENT_PROVIDER=openai_compatible.",
        )

    return AgentModelConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=settings.agent_timeout_seconds,
    )


def create_chat_model(settings: Settings) -> BaseChatModel:
    """Create a LangChain chat model for the configured provider."""
    cfg = resolve_model_config(settings)
    secret_key = SecretStr(cfg.api_key)

    try:
        if cfg.provider == "deepseek":
            from langchain_deepseek import ChatDeepSeek

            kwargs: dict[str, Any] = {
                "model": cfg.model,
                "api_key": secret_key,
                "timeout": cfg.timeout,
                "max_retries": 2,
            }
            if cfg.base_url:
                kwargs["base_url"] = cfg.base_url
            return ChatDeepSeek(**kwargs)

        if cfg.provider == "kimi":
            from langchain_moonshot import ChatMoonshot

            kwargs = {
                "model": cfg.model,
                "api_key": secret_key,
                "timeout": cfg.timeout,
                "max_retries": 2,
            }
            if cfg.base_url:
                kwargs["base_url"] = cfg.base_url
            return ChatMoonshot(**kwargs)

        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=cfg.model,
            api_key=secret_key,
            base_url=cfg.base_url,
            timeout=cfg.timeout,
            max_retries=2,
        )
    except ImportError as exc:
        raise AgentClientError(
            "agent_dependency_missing",
            "Install the agent LangChain dependencies before enabling model calls.",
        ) from exc
