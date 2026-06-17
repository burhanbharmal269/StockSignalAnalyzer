"""Application entry point.

Starts the uvicorn server using settings loaded from the environment.
Never import business logic here — this module is the process boundary only.
"""

from __future__ import annotations

import uvicorn

from core.infrastructure.config.settings import get_settings


def main() -> None:
    """Start the uvicorn ASGI server."""
    settings = get_settings()
    uvicorn.run(
        "app:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.is_development,
        log_level=settings.log_level.value.lower(),
        access_log=False,
    )


if __name__ == "__main__":
    main()
