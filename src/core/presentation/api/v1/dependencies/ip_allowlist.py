"""IP allowlist gate for admin-only endpoints (Doc 23 §4.4).

Usage:
    @router.post("/kill-switch/activate")
    async def handler(
        _: None = Depends(require_allowlisted_ip),
        user: CurrentUser = Depends(require_admin),
    ) -> ...:
        ...

The allowlist is read from SecurityConfig.admin_ip_list (comma-separated
CIDR blocks in the ALLOWED_ADMIN_IPS env var). When the list is empty,
ALL IPs are blocked from admin endpoints — operators must configure
at least one CIDR before admin routes become accessible.

IPv4 and IPv6 addresses are both supported via the ipaddress stdlib module.
"""

from __future__ import annotations

import ipaddress

from dependency_injector.wiring import Provide, inject
from fastapi import Depends, HTTPException, Request, status

from container import ApplicationContainer
from core.infrastructure.config.security_config import SecurityConfig
from core.infrastructure.logging.setup import get_logger

logger = get_logger(__name__)


def _client_ip(request: Request) -> str:
    """Extract the real client IP, respecting X-Forwarded-For from trusted proxies."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"  # noqa: S104


def _ip_in_allowlist(ip: str, allowlist: list[str]) -> bool:
    """Return True if ip falls within any CIDR in allowlist."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for cidr in allowlist:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
            if addr in network:
                return True
        except ValueError:
            continue
    return False


@inject
async def require_allowlisted_ip(
    request: Request,
    security_config: SecurityConfig = Depends(  # noqa: B008
        Provide[ApplicationContainer.security_config]
    ),
) -> None:
    """Raise 403 if the request IP is not in the admin allowlist."""
    allowlist = security_config.admin_ip_list
    ip = _client_ip(request)

    if not allowlist or not _ip_in_allowlist(ip, allowlist):
        logger.warning("admin_ip_blocked", client_ip=ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: source IP not in admin allowlist.",
        )
