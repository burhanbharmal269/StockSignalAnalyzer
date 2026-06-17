"""Broker connection configuration loaded from environment variables.

All values are loaded from .env / environment — never hardcoded.
The broker adapter reads this config; the domain never does.

Reference: docs/04_BROKER_ABSTRACTION.md, docs/09_CLAUDE_EXECUTION_RULES.md
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BrokerConfig(BaseSettings):
    """Broker connection configuration.

    ``trading_mode`` selects which broker adapter to use:
        - "live"   — KiteBroker (Zerodha Kite Connect)
        - "angel"  — Angel One SmartAPI

    Whether orders are actually placed is controlled separately by ExecutionLockService
    (MANUAL = no orders, AUTOMATIC = orders routed to broker). Market data, signals,
    and analytics always run regardless of this setting.

    ``kite_api_key`` and ``kite_api_secret`` are required for live market data and orders.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    trading_mode: str = Field(
        default="live",
        description="Broker adapter: 'live' (Kite) or 'angel' (Angel One).",
    )

    kite_api_key: str = Field(
        default="",
        description="Kite Connect API key. Required in live mode.",
    )

    kite_api_secret: str = Field(
        default="",
        description="Kite Connect API secret. Required in live mode.",
    )

    kite_session_expiry_hour_ist: int = Field(
        default=6,
        ge=0,
        le=23,
        description="Hour (IST) at which the Kite access token expires.",
    )

    broker_token_key_secret_name: str = Field(
        default="BROKER_TOKEN_ENCRYPTION_KEY",
        description="Name of the secret (in ISecretsClient) holding the AES-256 key.",
    )

    @property
    def is_live_mode(self) -> bool:
        return self.trading_mode.lower() == "live"

    # Angel One credentials (used when trading_mode == "angel")
    angel_api_key: str = Field(default="", description="Angel One SmartAPI API key.")
    angel_client_code: str = Field(default="", description="Angel One client code (login ID).")
    angel_mpin: str = Field(default="", description="Angel One MPIN.")
    angel_totp_secret: str = Field(default="", description="Angel One TOTP secret (base32).")

    @property
    def is_angel_mode(self) -> bool:
        return self.trading_mode.lower() == "angel"


# Alias for type hints in Angel adapter
AngelBrokerConfig = BrokerConfig
