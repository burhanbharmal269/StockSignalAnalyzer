"""Health check response schemas.

Pydantic models for the /api/v1/health endpoint response.
Presentation-layer only — no domain imports.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Response body for GET /api/v1/health."""

    status: str = Field(description="Overall system status: 'ok' or 'degraded'")
    environment: str = Field(description="Active deployment environment")
    version: str = Field(description="Application version string")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "ok",
                "environment": "development",
                "version": "0.1.0",
            }
        }
    }
