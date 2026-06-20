"""Backfill runner for Phase 20.5 and Phase 20.6.

Runs in the ssa_backend container:
  docker exec ssa_backend python /app/scripts/run_backfills.py

What it does:
  1. PostTradeIntelligenceService.enrich_unattributed(limit=500)
     — Attributes failure/success reasons, quality scores, model failure
       class, and operator explanations for all completed unattributed signals.
  2. TradeReplayService.backfill_unreplayed(limit=500)
     — Builds lifecycle event timelines for accepted signals with no replay events.

Nothing here writes to production config, changes thresholds, or touches
live signal generation. Analytics columns only.
"""

import asyncio
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
_log = logging.getLogger("backfill")

# Ensure /app/src is on the path (matches container PYTHONPATH)
sys.path.insert(0, "/app/src")


async def main() -> None:
    from core.infrastructure.database.connection import build_session_factory, build_write_engine
    from core.infrastructure.config.database_config import DatabaseConfig

    db_cfg = DatabaseConfig()
    _log.info("Connecting to: %s", db_cfg.database_write_url.split("@")[-1])

    engine  = build_write_engine(
        db_cfg.database_write_url,
        pool_size=db_cfg.database_pool_size,
        max_overflow=db_cfg.database_max_overflow,
        pool_timeout=db_cfg.database_pool_timeout,
    )
    sf      = build_session_factory(engine)

    # ── Phase 20.5: Attribution backfill ──────────────────────────────────────
    _log.info("=" * 60)
    _log.info("PHASE 20.5 — Post-Trade Attribution Backfill")
    _log.info("=" * 60)
    try:
        from core.application.services.post_trade_intelligence_service import (
            PostTradeIntelligenceService,
        )
        pti_svc = PostTradeIntelligenceService(sf)
        result  = await pti_svc.enrich_unattributed(limit=500)
        _log.info(
            "Attribution complete: processed=%d  succeeded=%d  failed=%d",
            result.get("processed", 0),
            result.get("succeeded", 0),
            result.get("failed", 0),
        )
        if result.get("errors"):
            for e in result["errors"][:5]:
                _log.warning("  error: %s", e)
    except Exception as exc:
        _log.error("Attribution backfill failed: %s", exc, exc_info=True)

    # ── Phase 20.6: Replay events backfill ────────────────────────────────────
    _log.info("=" * 60)
    _log.info("PHASE 20.6 — Trade Replay Events Backfill")
    _log.info("=" * 60)
    try:
        from core.application.services.trade_replay_service import TradeReplayService

        replay_svc = TradeReplayService(sf)
        result     = await replay_svc.backfill_unreplayed(limit=500)
        _log.info(
            "Replay backfill complete: processed=%d  succeeded=%d  failed=%d  events_created=%d",
            result.get("processed", 0),
            result.get("succeeded", 0),
            result.get("failed", 0),
            result.get("events_created", 0),
        )
        if result.get("errors"):
            for e in result["errors"][:5]:
                _log.warning("  error: %s", e)

        # Print coverage summary
        coverage = await replay_svc.get_replay_coverage()
        _log.info(
            "Replay coverage: %d/%d accepted signals have timelines (%.1f%%)",
            coverage.get("signals_with_replay", 0),
            coverage.get("total_accepted", 0),
            coverage.get("coverage_pct", 0.0),
        )
    except Exception as exc:
        _log.error("Replay backfill failed: %s", exc, exc_info=True)

    await engine.dispose()
    _log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
