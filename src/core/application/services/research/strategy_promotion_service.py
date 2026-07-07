"""StrategyPromotionService — version promotion workflow with statistical gate.

Gates a research version for promotion. Requirements:
  - OOS Sharpe > 0.8
  - Walk-forward windows completed >= 3
  - Statistical significance p < 0.05
  - Manual human approval

Statuses: PENDING → APPROVED / REJECTED
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

_OOS_SHARPE_MIN = 0.8
_MIN_WALK_FORWARD_WINDOWS = 3
_P_VALUE_MAX = 0.05


class StrategyPromotionService:
    """Manages strategy version promotion lifecycle."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def request_promotion(
        self,
        version_id: str,
        requested_by: str | None = None,
        notes: str | None = None,
    ) -> str:
        req_id = str(uuid.uuid4())
        async with self._sf() as db:
            await db.execute(
                text("""
                    INSERT INTO research_promotion_requests
                        (id, version_id, requested_by, status, promotion_notes, created_at)
                    VALUES
                        (:id, :vid, :by, 'PENDING', :notes, NOW())
                """),
                {"id": req_id, "vid": version_id, "by": requested_by, "notes": notes},
            )
            await db.commit()
        _log.info("strategy_promotion_service.request_created id=%s version=%s", req_id, version_id)
        # Auto-evaluate immediately
        await self.auto_evaluate(req_id)
        return req_id

    async def auto_evaluate(self, promotion_request_id: str) -> dict:
        """Run statistical gates and update promotion request status."""
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("SELECT version_id FROM research_promotion_requests WHERE id = :id"),
                    {"id": promotion_request_id},
                )
                row = r.fetchone()
                if not row:
                    return {"error": "Promotion request not found"}
                version_id = row[0]

            # Fetch OOS stats from walk-forward windows for this version
            oos_sharpe, oos_win_rate, window_count, p_value = await self._gather_oos_stats(version_id)

            # Gate evaluation
            gates = {
                "oos_sharpe": oos_sharpe is not None and oos_sharpe > _OOS_SHARPE_MIN,
                "walk_forward_windows": window_count >= _MIN_WALK_FORWARD_WINDOWS,
                "p_value": p_value is not None and p_value < _P_VALUE_MAX,
            }
            stat_passed = all(gates.values())

            async with self._sf() as db:
                await db.execute(
                    text("""
                        UPDATE research_promotion_requests
                        SET stat_test_passed = :passed,
                            oos_sharpe = :oos_sh,
                            oos_win_rate = :oos_wr,
                            walk_forward_windows = :wf
                        WHERE id = :id
                    """),
                    {
                        "passed": stat_passed,
                        "oos_sh": oos_sharpe, "oos_wr": oos_win_rate,
                        "wf": window_count, "id": promotion_request_id,
                    },
                )
                await db.commit()

            return {
                "id": promotion_request_id,
                "stat_test_passed": stat_passed,
                "gates": gates,
                "oos_sharpe": oos_sharpe,
                "oos_win_rate": oos_win_rate,
                "walk_forward_windows": window_count,
                "p_value": p_value,
            }
        except Exception as exc:
            _log.warning("strategy_promotion_service.auto_evaluate_failed: %s", exc)
            return {"error": str(exc)}

    async def approve(
        self, promotion_request_id: str, reviewer: str | None = None
    ) -> None:
        async with self._sf() as db:
            await db.execute(
                text("""
                    UPDATE research_promotion_requests
                    SET status = 'APPROVED', reviewed_by = :rev, reviewed_at = NOW()
                    WHERE id = :id AND status = 'PENDING'
                """),
                {"rev": reviewer, "id": promotion_request_id},
            )
            await db.commit()
        _log.info("strategy_promotion_service.approved id=%s by=%s", promotion_request_id, reviewer)

    async def reject(
        self,
        promotion_request_id: str,
        reviewer: str | None = None,
        reason: str | None = None,
    ) -> None:
        async with self._sf() as db:
            await db.execute(
                text("""
                    UPDATE research_promotion_requests
                    SET status = 'REJECTED', reviewed_by = :rev,
                        reviewed_at = NOW(), rejection_reason = :reason
                    WHERE id = :id AND status = 'PENDING'
                """),
                {"rev": reviewer, "id": promotion_request_id, "reason": reason},
            )
            await db.commit()
        _log.info("strategy_promotion_service.rejected id=%s by=%s", promotion_request_id, reviewer)

    async def get_queue(self) -> list[dict]:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT pr.*, rsv.name AS version_name
                        FROM research_promotion_requests pr
                        LEFT JOIN research_strategy_versions rsv ON rsv.id = pr.version_id
                        ORDER BY pr.created_at DESC
                        LIMIT 100
                    """)
                )
                return [dict(row) for row in r.mappings().fetchall()]
        except Exception as exc:
            _log.warning("strategy_promotion_service.get_queue_failed: %s", exc)
            return []

    # ── Private ───────────────────────────────────────────────────────────────

    async def _gather_oos_stats(
        self, version_id: str
    ) -> tuple[float | None, float | None, int, float | None]:
        """Return (oos_sharpe_mean, oos_win_rate_mean, window_count, p_value)."""
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT wfw.oos_sharpe, wfw.oos_win_rate
                        FROM research_walk_forward_windows wfw
                        JOIN research_runs rr ON rr.id = wfw.run_id
                        WHERE rr.version_id = :vid
                          AND wfw.oos_sharpe IS NOT NULL
                        ORDER BY wfw.created_at DESC
                        LIMIT 20
                    """),
                    {"vid": version_id},
                )
                rows = r.fetchall()

            if not rows:
                return None, None, 0, None

            sharpes = [float(r[0]) for r in rows if r[0] is not None]
            win_rates = [float(r[1]) for r in rows if r[1] is not None]
            n = len(sharpes)
            if n == 0:
                return None, None, 0, None

            mean_sh = sum(sharpes) / n
            mean_wr = sum(win_rates) / len(win_rates) if win_rates else None

            # One-sample t-test (H0: mean Sharpe ≤ 0)
            p_value = None
            if n >= 2:
                var = sum((s - mean_sh) ** 2 for s in sharpes) / (n - 1)
                std = math.sqrt(var)
                if std > 0:
                    t = mean_sh / (std / math.sqrt(n))
                    p_value = round(1 - math.erf(abs(t) / math.sqrt(2)), 6)

            return round(mean_sh, 4), round(mean_wr, 2) if mean_wr else None, n, p_value
        except Exception as exc:
            _log.warning("strategy_promotion_service.gather_oos_failed: %s", exc)
            return None, None, 0, None
