"""ResourceMonitorService — Phase 22 §13.

Measures and reports system resource usage:
  - CPU and memory (psutil)
  - Redis memory and connection count (Redis INFO)
  - Database connection pool stats (SQLAlchemy engine)
  - API throughput counters (in-process)

Snapshots are cached in Redis (resource:snapshot) with a 60-second TTL
and served via the scanner intelligence API dashboard.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

_log = logging.getLogger(__name__)

_CACHE_KEY = "resource:snapshot"
_CACHE_TTL = 60    # seconds

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncEngine


class ResourceMonitorService:
    """Collects CPU, memory, Redis, and DB resource metrics."""

    def __init__(
        self,
        redis_client: "Redis | None" = None,
        db_engine: "AsyncEngine | None" = None,
    ) -> None:
        self._redis = redis_client
        self._engine = db_engine
        self._request_count: int = 0
        self._request_errors: int = 0

    # ── Public API ────────────────────────────────────────────────────────────

    async def collect(self) -> dict[str, Any]:
        """Collect all resource metrics and cache to Redis."""
        snapshot: dict[str, Any] = {
            "collected_at": datetime.now(UTC).isoformat(),
            "cpu": _collect_cpu(),
            "memory": _collect_memory(),
            "redis": await self._collect_redis(),
            "database": self._collect_db(),
            "api": {
                "request_count":  self._request_count,
                "request_errors": self._request_errors,
            },
        }
        await self._cache(snapshot)
        return snapshot

    async def get_cached(self) -> dict[str, Any] | None:
        """Return the most recent snapshot from Redis cache."""
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(_CACHE_KEY)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    def record_request(self, *, error: bool = False) -> None:
        """Increment throughput counters (called from middleware)."""
        self._request_count += 1
        if error:
            self._request_errors += 1

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _collect_redis(self) -> dict[str, Any]:
        if self._redis is None:
            return {"available": False}
        try:
            t0 = time.monotonic()
            info = await self._redis.info("memory")
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            return {
                "available": True,
                "used_memory_mb": round(int(info.get("used_memory", 0)) / 1024 / 1024, 2),
                "used_memory_peak_mb": round(int(info.get("used_memory_peak", 0)) / 1024 / 1024, 2),
                "ping_ms": latency_ms,
            }
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def _collect_db(self) -> dict[str, Any]:
        if self._engine is None:
            return {"available": False}
        try:
            pool = self._engine.pool
            return {
                "available": True,
                "pool_size": pool.size(),
                "checked_in": pool.checkedin(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow(),
            }
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    async def _cache(self, snapshot: dict) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.setex(_CACHE_KEY, _CACHE_TTL, json.dumps(snapshot, default=str))
        except Exception:
            pass


# ── Platform metrics (psutil optional) ───────────────────────────────────────

def _collect_cpu() -> dict[str, Any]:
    try:
        import psutil
        return {
            "percent": psutil.cpu_percent(interval=0.1),
            "count_logical": psutil.cpu_count(logical=True),
            "count_physical": psutil.cpu_count(logical=False),
        }
    except ImportError:
        return {"available": False, "note": "psutil not installed"}
    except Exception as exc:
        return {"error": str(exc)}


def _collect_memory() -> dict[str, Any]:
    try:
        import psutil
        vm = psutil.virtual_memory()
        return {
            "total_mb": round(vm.total / 1024 / 1024),
            "available_mb": round(vm.available / 1024 / 1024),
            "used_mb": round(vm.used / 1024 / 1024),
            "percent": vm.percent,
        }
    except ImportError:
        return {"available": False, "note": "psutil not installed"}
    except Exception as exc:
        return {"error": str(exc)}
