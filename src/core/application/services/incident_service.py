"""IncidentService — Phase 24 Operations.

Full incident lifecycle management: create, resolve, list, get.

12 incident types:
  KITE_AUTH_EXPIRED, SCANNER_IDLE, MARKET_DATA_STALE, REDIS_DISCONNECTED,
  DB_CONNECTION_LOST, EXECUTION_HALTED, KILL_SWITCH_TRIGGERED,
  OPTION_CHAIN_STALE, SIGNAL_GATE_FAILURE, VIX_SPIKE,
  RISK_BREACH, WEBSOCKET_DISCONNECTED

Severities: LOW, MEDIUM, HIGH, CRITICAL
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

INCIDENT_TYPES = {
    "KITE_AUTH_EXPIRED",
    "SCANNER_IDLE",
    "MARKET_DATA_STALE",
    "REDIS_DISCONNECTED",
    "DB_CONNECTION_LOST",
    "EXECUTION_HALTED",
    "KILL_SWITCH_TRIGGERED",
    "OPTION_CHAIN_STALE",
    "SIGNAL_GATE_FAILURE",
    "VIX_SPIKE",
    "RISK_BREACH",
    "WEBSOCKET_DISCONNECTED",
}

SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


class IncidentService:
    """Manages the incident log."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create(
        self,
        *,
        incident_type: str,
        severity: str,
        title: str,
        root_cause: str | None = None,
        impact: str | None = None,
        recovery_actions: str | None = None,
    ) -> dict[str, Any]:
        if incident_type not in INCIDENT_TYPES:
            raise ValueError(f"Unknown incident_type: {incident_type}")
        if severity not in SEVERITIES:
            raise ValueError(f"Unknown severity: {severity}")

        now = datetime.now(UTC)
        async with self._sf() as db:
            r = await db.execute(
                text(
                    "INSERT INTO incidents "
                    "(incident_type, severity, title, start_time, root_cause, impact, "
                    " recovery_actions, is_resolved, created_at, updated_at) "
                    "VALUES (:type, :sev, :title, :now, :rc, :impact, :ra, false, :now, :now) "
                    "RETURNING id"
                ),
                {
                    "type":  incident_type,
                    "sev":   severity,
                    "title": title,
                    "now":   now,
                    "rc":    root_cause,
                    "impact": impact,
                    "ra":    recovery_actions,
                },
            )
            row = r.fetchone()
            await db.commit()

        incident_id = row[0]
        _log.warning(
            "incident.created id=%d type=%s severity=%s title=%r",
            incident_id, incident_type, severity, title,
        )
        return await self.get(incident_id)

    async def resolve(
        self,
        incident_id: int,
        *,
        resolution: str,
        root_cause: str | None = None,
        recovery_actions: str | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        async with self._sf() as db:
            # Compute duration from start_time
            r = await db.execute(
                text("SELECT start_time FROM incidents WHERE id=:id"),
                {"id": incident_id},
            )
            row = r.fetchone()
            if not row:
                raise ValueError(f"Incident {incident_id} not found")
            start = row[0].replace(tzinfo=UTC)
            duration_min = round((now - start).total_seconds() / 60, 1)

            await db.execute(
                text(
                    "UPDATE incidents SET "
                    "  end_time=:now, duration_minutes=:dur, resolution=:res, "
                    "  root_cause=COALESCE(:rc, root_cause), "
                    "  recovery_actions=COALESCE(:ra, recovery_actions), "
                    "  is_resolved=true, updated_at=:now "
                    "WHERE id=:id"
                ),
                {
                    "now": now,
                    "dur": duration_min,
                    "res": resolution,
                    "rc":  root_cause,
                    "ra":  recovery_actions,
                    "id":  incident_id,
                },
            )
            await db.commit()

        _log.info("incident.resolved id=%d duration_min=%.1f", incident_id, duration_min)
        return await self.get(incident_id)

    async def get(self, incident_id: int) -> dict[str, Any]:
        async with self._sf() as db:
            r = await db.execute(
                text(
                    "SELECT id, incident_type, severity, title, start_time, end_time, "
                    "       duration_minutes, root_cause, resolution, impact, "
                    "       recovery_actions, is_resolved, created_at, updated_at "
                    "FROM incidents WHERE id=:id"
                ),
                {"id": incident_id},
            )
            row = r.fetchone()
        if not row:
            raise ValueError(f"Incident {incident_id} not found")
        return self._row_to_dict(row)

    async def list_incidents(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        incident_type: str | None = None,
        severity: str | None = None,
        unresolved_only: bool = False,
    ) -> dict[str, Any]:
        conditions = []
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if incident_type:
            conditions.append("incident_type=:type")
            params["type"] = incident_type
        if severity:
            conditions.append("severity=:sev")
            params["sev"] = severity
        if unresolved_only:
            conditions.append("is_resolved=false")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        async with self._sf() as db:
            r = await db.execute(
                text(
                    f"SELECT id, incident_type, severity, title, start_time, end_time, "  # noqa: S608
                    f"       duration_minutes, root_cause, resolution, impact, "
                    f"       recovery_actions, is_resolved, created_at, updated_at "
                    f"FROM incidents {where} "
                    f"ORDER BY start_time DESC "
                    f"LIMIT :limit OFFSET :offset"
                ),
                params,
            )
            rows = r.fetchall()

            count_r = await db.execute(
                text(f"SELECT COUNT(*) FROM incidents {where}"),  # noqa: S608
                {k: v for k, v in params.items() if k not in ("limit", "offset")},
            )
            total = count_r.scalar() or 0

        return {
            "total":     total,
            "limit":     limit,
            "offset":    offset,
            "incidents": [self._row_to_dict(r) for r in rows],
        }

    async def get_summary(self) -> dict[str, Any]:
        """Aggregate counts by type, severity, and resolution state."""
        async with self._sf() as db:
            r = await db.execute(text(
                "SELECT severity, COUNT(*), "
                "       COUNT(*) FILTER (WHERE is_resolved=false) AS open_count "
                "FROM incidents "
                "GROUP BY severity"
            ))
            by_severity = {
                row[0]: {"total": int(row[1]), "open": int(row[2])}
                for row in r.fetchall()
            }

            r2 = await db.execute(text(
                "SELECT incident_type, COUNT(*) "
                "FROM incidents "
                "GROUP BY incident_type ORDER BY COUNT(*) DESC"
            ))
            by_type = {row[0]: int(row[1]) for row in r2.fetchall()}

            r3 = await db.execute(text(
                "SELECT COUNT(*) FROM incidents WHERE is_resolved=false"
            ))
            open_total = int(r3.scalar() or 0)

            r4 = await db.execute(text("SELECT COUNT(*) FROM incidents"))
            total = int(r4.scalar() or 0)

            r5 = await db.execute(text(
                "SELECT AVG(duration_minutes) FROM incidents WHERE is_resolved=true"
            ))
            avg_dur = float(r5.scalar() or 0)

        return {
            "total":              total,
            "open":               open_total,
            "avg_duration_min":   round(avg_dur, 1),
            "by_severity":        by_severity,
            "by_type":            by_type,
        }

    def _row_to_dict(self, row: Any) -> dict[str, Any]:
        (
            id_, type_, sev, title, start, end, dur,
            rc, res, impact, ra, resolved, created, updated
        ) = row
        return {
            "id":               id_,
            "incident_type":    type_,
            "severity":         sev,
            "title":            title,
            "start_time":       start.isoformat() if start else None,
            "end_time":         end.isoformat()   if end   else None,
            "duration_minutes": float(dur)        if dur   else None,
            "root_cause":       rc,
            "resolution":       res,
            "impact":           impact,
            "recovery_actions": ra,
            "is_resolved":      resolved,
            "created_at":       created.isoformat() if created else None,
            "updated_at":       updated.isoformat() if updated else None,
        }
