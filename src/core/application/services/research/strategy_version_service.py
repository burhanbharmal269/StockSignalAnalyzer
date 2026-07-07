"""StrategyVersionService — manages research strategy versions.

V1 is automatically seeded as an immutable snapshot of the production
scoring_weights.yaml. V2+ are mutable research variants that can be used
for grid search, walk-forward, and Monte Carlo simulation.
"""

from __future__ import annotations

import hashlib
import logging
import pathlib
import uuid
from datetime import UTC, datetime
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

_WEIGHTS_PATH = pathlib.Path(__file__).resolve().parents[5] / "config" / "scoring_weights.yaml"
_V1_NAME = "Production-V1"


class StrategyVersionService:
    """Manages research strategy versions. Fail-open on reads, strict on writes."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ── Seeding ───────────────────────────────────────────────────────────────

    async def seed_v1(self) -> dict:
        """Idempotent: create V1 from scoring_weights.yaml if it doesn't exist."""
        try:
            raw = _WEIGHTS_PATH.read_text(encoding="utf-8")
            cfg = yaml.safe_load(raw)
            sha = hashlib.sha256(raw.encode()).hexdigest()
            weights = {k: v for k, v in cfg.get("components", {}).items()}
        except Exception as exc:
            _log.warning("strategy_version_service.seed_v1.read_failed: %s", exc)
            weights, sha, raw = {}, "", ""

        async with self._sf() as db:
            existing = await db.execute(
                text("SELECT id FROM research_strategy_versions WHERE name = :name"),
                {"name": _V1_NAME},
            )
            if existing.fetchone():
                _log.debug("strategy_version_service.v1_already_exists")
                row = await db.execute(
                    text("SELECT * FROM research_strategy_versions WHERE name = :name"),
                    {"name": _V1_NAME},
                )
                return dict(row.mappings().fetchone() or {})

            version_id = str(uuid.uuid4())
            await db.execute(
                text("""
                    INSERT INTO research_strategy_versions
                        (id, name, description, weights_snapshot, params_snapshot,
                         is_immutable, base_version_id, scoring_weights_sha256,
                         created_at, updated_at)
                    VALUES
                        (:id, :name, :desc, CAST(:weights AS jsonb), CAST(:params AS jsonb),
                         true, null, :sha, NOW(), NOW())
                """),
                {
                    "id": version_id,
                    "name": _V1_NAME,
                    "desc": "Production strategy V1 — immutable snapshot of scoring_weights.yaml",
                    "weights": __import__("json").dumps(weights),
                    "params": "{}",
                    "sha": sha,
                },
            )
            await db.commit()
            _log.info("strategy_version_service.v1_seeded id=%s", version_id)
            return {"id": version_id, "name": _V1_NAME, "is_immutable": True}

    # ── CRUD ──────────────────────────────────────────────────────────────────

    async def list_versions(self) -> list[dict]:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("SELECT * FROM research_strategy_versions ORDER BY created_at")
                )
                return [dict(row) for row in r.mappings().fetchall()]
        except Exception as exc:
            _log.warning("strategy_version_service.list_failed: %s", exc)
            return []

    async def get_version(self, version_id: str) -> dict | None:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("SELECT * FROM research_strategy_versions WHERE id = :id"),
                    {"id": version_id},
                )
                row = r.mappings().fetchone()
                return dict(row) if row else None
        except Exception as exc:
            _log.warning("strategy_version_service.get_failed: %s", exc)
            return None

    async def create_variant(
        self,
        name: str,
        base_version_id: str,
        weights: dict,
        params: dict | None = None,
        description: str | None = None,
    ) -> dict:
        version_id = str(uuid.uuid4())
        import json
        async with self._sf() as db:
            await db.execute(
                text("""
                    INSERT INTO research_strategy_versions
                        (id, name, description, weights_snapshot, params_snapshot,
                         is_immutable, base_version_id, created_at, updated_at)
                    VALUES
                        (:id, :name, :desc, CAST(:weights AS jsonb), CAST(:params AS jsonb),
                         false, :base_id, NOW(), NOW())
                """),
                {
                    "id": version_id,
                    "name": name,
                    "desc": description,
                    "weights": json.dumps(weights),
                    "params": json.dumps(params or {}),
                    "base_id": base_version_id,
                },
            )
            await db.commit()
        _log.info("strategy_version_service.variant_created id=%s name=%s", version_id, name)
        return {"id": version_id, "name": name, "is_immutable": False}

    async def update_variant(
        self,
        version_id: str,
        weights: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        import json
        async with self._sf() as db:
            row = await db.execute(
                text("SELECT is_immutable FROM research_strategy_versions WHERE id = :id"),
                {"id": version_id},
            )
            rec = row.fetchone()
            if not rec:
                raise ValueError(f"Version {version_id} not found")
            if rec[0]:
                raise ValueError("Cannot modify immutable version V1")

            updates: list[str] = ["updated_at = NOW()"]
            bind: dict[str, Any] = {"id": version_id}
            if weights is not None:
                updates.append("weights_snapshot = CAST(:weights AS jsonb)")
                bind["weights"] = json.dumps(weights)
            if params is not None:
                updates.append("params_snapshot = CAST(:params AS jsonb)")
                bind["params"] = json.dumps(params)

            await db.execute(
                text(f"UPDATE research_strategy_versions SET {', '.join(updates)} WHERE id = :id"),
                bind,
            )
            await db.commit()
        return {"id": version_id, "updated": True}

    async def get_weights(self, version_id: str) -> dict:
        v = await self.get_version(version_id)
        if not v:
            raise ValueError(f"Version {version_id} not found")
        return v.get("weights_snapshot") or {}
