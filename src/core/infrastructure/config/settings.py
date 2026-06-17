"""Application settings loaded from environment variables and .env file.

All configuration values come from the environment — never hardcoded.
Reference: docs/09_CLAUDE_EXECUTION_RULES.md (Configuration Rules)
           docs/23_SECURITY_BASELINE.md (Secrets Management)
"""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogFormat(StrEnum):
    CONSOLE = "console"
    JSON = "json"


class AppSettings(BaseSettings):
    """All application settings resolved from environment variables.

    Required variables must be present at startup — the application will
    refuse to start with a ValidationError if any are missing.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application identity -----------------------------------------------
    app_name: str = Field(default="StockSignalAnalyzer")
    app_version: str = Field(default="0.1.0")
    environment: Environment = Field(default=Environment.DEVELOPMENT)
    debug: bool = Field(default=False)

    # --- API server ----------------------------------------------------------
    api_host: str = Field(default="0.0.0.0")  # noqa: S104
    api_port: int = Field(default=8000, ge=1024, le=65535)

    # --- Logging -------------------------------------------------------------
    log_level: LogLevel = Field(default=LogLevel.INFO)
    log_format: LogFormat = Field(default=LogFormat.CONSOLE)

    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------

    @field_validator("log_format", mode="before")
    @classmethod
    def production_must_use_json_logging(cls, value: str, info: object) -> str:
        """Enforce JSON logging in production — console logs are not parseable
        by log aggregators (Datadog, CloudWatch, Loki).
        """
        # info.data is populated before this field is validated
        data = getattr(info, "data", {})
        env = data.get("environment", Environment.DEVELOPMENT)
        if env == Environment.PRODUCTION and value == LogFormat.CONSOLE:
            raise ValueError(
                "LOG_FORMAT must be 'json' in production. "
                "Console format cannot be parsed by log aggregators."
            )
        return value

    @field_validator("debug", mode="before")
    @classmethod
    def debug_must_be_false_in_production(cls, value: object, info: object) -> object:
        """Prevent accidental DEBUG=true deployments to production.

        mode="before" receives the raw env-var string before Pydantic coerces
        it to bool, so we must handle both str and bool representations.
        """
        data = getattr(info, "data", {})
        env = data.get("environment", Environment.DEVELOPMENT)
        is_debug = value is True or str(value).lower() in ("true", "1", "yes")
        if env == Environment.PRODUCTION and is_debug:
            raise ValueError("DEBUG must be False in production.")
        return value

    # -------------------------------------------------------------------------
    # Derived helpers (not stored, computed on access)
    # -------------------------------------------------------------------------

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @property
    def is_development(self) -> bool:
        return self.environment == Environment.DEVELOPMENT

    @property
    def is_debug(self) -> bool:
        return self.debug


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return the singleton settings instance.

    Cached after first call so environment is read only once.
    Use ``get_settings.cache_clear()`` in tests to reset.
    """
    return AppSettings()
