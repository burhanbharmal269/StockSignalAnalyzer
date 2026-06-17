"""AIClient — thin async wrapper around OpenAI / Anthropic APIs.

Used ONLY for advisory outputs (insights, summaries, strategy selection).
NEVER injected into OMS, RiskEngine, or order execution paths.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.infrastructure.config.ai_config import AIConfig

_log = logging.getLogger(__name__)


class AIClient:
    def __init__(self, config: AIConfig) -> None:
        self._config = config
        self._openai_client = None
        self._anthropic_client = None

    async def complete(self, system: str, user: str) -> str | None:
        """Send a prompt to the configured AI provider.

        Returns the response text or None if AI is disabled/unavailable.
        """
        if not self._config.is_enabled:
            return None

        try:
            if self._config.ai_provider == "openai":
                return await self._openai(system, user)
            if self._config.ai_provider == "anthropic":
                return await self._anthropic(system, user)
            if self._config.ai_provider == "azure_openai":
                return await self._azure_openai(system, user)
        except Exception as exc:
            _log.warning("ai_client.error provider=%s err=%s", self._config.ai_provider, exc)
        return None

    async def _openai(self, system: str, user: str) -> str | None:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            _log.warning("openai package not installed; AI calls disabled")
            return None

        if self._openai_client is None:
            key = self._config.openai_api_key.get_secret_value()
            if not key:
                return None
            self._openai_client = AsyncOpenAI(api_key=key, timeout=self._config.ai_timeout_seconds)

        response = await self._openai_client.chat.completions.create(
            model=self._config.ai_model,
            max_tokens=self._config.ai_max_tokens_per_call,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content

    async def _azure_openai(self, system: str, user: str) -> str | None:
        try:
            from openai import AsyncAzureOpenAI
        except ImportError:
            _log.warning("openai package not installed; Azure OpenAI calls disabled")
            return None

        if self._openai_client is None:
            key = self._config.azure_openai_api_key.get_secret_value()
            if not key or not self._config.azure_openai_endpoint:
                return None
            self._openai_client = AsyncAzureOpenAI(
                api_key=key,
                azure_endpoint=self._config.azure_openai_endpoint,
                api_version=self._config.azure_openai_api_version,
                timeout=self._config.ai_timeout_seconds,
            )

        response = await self._openai_client.chat.completions.create(
            model=self._config.azure_openai_deployment,
            max_tokens=self._config.ai_max_tokens_per_call,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content

    async def _anthropic(self, system: str, user: str) -> str | None:
        try:
            import anthropic
        except ImportError:
            _log.warning("anthropic package not installed; AI calls disabled")
            return None

        if self._anthropic_client is None:
            key = self._config.anthropic_api_key.get_secret_value()
            if not key:
                return None
            self._anthropic_client = anthropic.AsyncAnthropic(api_key=key)

        message = await self._anthropic_client.messages.create(
            model=self._config.ai_model,
            max_tokens=self._config.ai_max_tokens_per_call,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return message.content[0].text
