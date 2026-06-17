"""AIConfig — pydantic-settings model for AI provider configuration.

The AI provider is ADVISORY ONLY. It is injected into SentimentAnalyzer
and SummarizationService only. It is FORBIDDEN from being injected into:
OMS, RiskEngine, PositionSizer, KillSwitchService.

Reference: docs/09_CLAUDE_EXECUTION_RULES.md (AI Guardrails)
           docs/22_AI_INTEGRATION.md
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AIConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    # Provider
    ai_provider: str = Field(
        default="openai",
        description="AI backend: openai | anthropic | disabled",
    )
    ai_model: str = Field(default="gpt-4o-mini")

    # Credentials — fetched via ISecretsClient in production;
    # env-var fallback is used in development only.
    openai_api_key: SecretStr = Field(default=SecretStr(""))
    anthropic_api_key: SecretStr = Field(default=SecretStr(""))

    # Azure OpenAI credentials
    azure_openai_api_key: SecretStr = Field(default=SecretStr(""))
    azure_openai_endpoint: str = Field(default="")
    azure_openai_deployment: str = Field(default="")
    azure_openai_api_version: str = Field(default="2024-02-01")

    # Cost guardrails
    ai_daily_budget_usd: float = Field(default=5.00, ge=0.0, le=1000.0)
    ai_max_tokens_per_call: int = Field(default=1000, ge=1, le=128000)
    ai_timeout_seconds: int = Field(default=10, ge=1, le=60)

    # Feature flag — set to "disabled" to run without any AI calls
    @field_validator("ai_provider", mode="before")
    @classmethod
    def provider_must_be_valid(cls, value: object) -> str:
        allowed = {"openai", "anthropic", "azure_openai", "disabled"}
        v = str(value).lower()
        if v not in allowed:
            msg = f"AI_PROVIDER must be one of {allowed}, got {value!r}"
            raise ValueError(msg)
        return v

    @property
    def is_enabled(self) -> bool:
        return self.ai_provider != "disabled"


@lru_cache(maxsize=1)
def get_ai_config() -> AIConfig:
    return AIConfig()
