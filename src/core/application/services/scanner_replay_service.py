"""ScannerReplayService — Phase 22 §12.

Persists complete scan snapshots to the `scanner_replay_snapshots` table,
enabling post-hoc debugging and strategy validation.

Answers queries like:
  - Why was RELIANCE rejected in the 11:30 scan?
  - What did the option chain look like when NIFTY was accepted?
  - What was the market regime and which gates fired?
  - What indicators were present at signal time?
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# Keep at most this many replay rows before pruning (FIFO)
_MAX_ROWS = 500


class ScannerReplayService:
    """Stores and retrieves full scan state snapshots."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ── Write ─────────────────────────────────────────────────────────────────

    async def record(
        self,
        *,
        scan_duration_seconds: float,
        total_candidates: int,
        accepted: int,
        rejected: int,
        gated: int,
        symbol_results: list[dict[str, Any]],
        gate_summary: dict[str, int],
        market_context: dict[str, Any] | None = None,
        regime_snapshot: dict[str, Any] | None = None,
        stage_timings: dict[str, float] | None = None,
    ) -> int | None:
        """Persist one scan cycle's full state. Returns inserted row ID or None."""
        try:
            top_scores = _extract_top_scores(symbol_results)
            now = datetime.now(UTC)
            async with self._sf() as db:
                r = await db.execute(text("""
                    INSERT INTO scanner_replay_snapshots
                        (scanned_at, scan_duration_seconds, total_candidates,
                         accepted, rejected, gated,
                         market_context, symbol_results, top_scores,
                         gate_summary, regime_snapshot, stage_timings)
                    VALUES
                        (:at, :dur, :tc, :acc, :rej, :gat,
                         :mc::jsonb, :sr::jsonb, :ts_::jsonb,
                         :gs::jsonb, :rs::jsonb, :stg::jsonb)
                    RETURNING id
                """), {
                    "at":  now,
                    "dur": round(scan_duration_seconds, 2),
                    "tc":  total_candidates,
                    "acc": accepted,
                    "rej": rejected,
                    "gat": gated,
                    "mc":  json.dumps(market_context or {}, default=str),
                    "sr":  json.dumps(symbol_results, default=str),
                    "ts_": json.dumps(top_scores, default=str),
                    "gs":  json.dumps(gate_summary, default=str),
                    "rs":  json.dumps(regime_snapshot or {}, default=str),
                    "stg": json.dumps(stage_timings or {}, default=str),
                })
                row_id = r.scalar()
                await db.commit()

            # Prune old rows asynchronously (best-effort)
            await self._prune()
            return row_id
        except Exception as exc:
            _log.warning("scanner_replay.record_failed: %s", exc)
            return None

    # ── Read ──────────────────────────────────────────────────────────────────

    async def list_snapshots(self, limit: int = 50) -> list[dict[str, Any]]:
        """List recent scan snapshots (summary, no symbol_results)."""
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT id, scanned_at, scan_duration_seconds,
                       total_candidates, accepted, rejected, gated,
                       top_scores, gate_summary, regime_snapshot
                FROM scanner_replay_snapshots
                ORDER BY scanned_at DESC LIMIT :lim
            """), {"lim": limit})
            rows = r.fetchall()
        return [_replay_row_summary(row) for row in rows]

    async def get_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        """Return full snapshot including symbol_results."""
        async with self._sf() as db:
            r = await db.execute(text("""
                SELECT id, scanned_at, scan_duration_seconds,
                       total_candidates, accepted, rejected, gated,
                       market_context, symbol_results, top_scores,
                       gate_summary, regime_snapshot, stage_timings
                FROM scanner_replay_snapshots WHERE id = :id
            """), {"id": snapshot_id})
            row = r.fetchone()
        if row is None:
            return None
        return _replay_row_full(row)

    async def get_symbol_result(
        self, snapshot_id: int, symbol: str
    ) -> dict[str, Any] | None:
        """Return the result for one symbol within a snapshot."""
        snap = await self.get_snapshot(snapshot_id)
        if not snap:
            return None
        for sr in (snap.get("symbol_results") or []):
            if isinstance(sr, dict) and sr.get("symbol") == symbol:
                return sr
        return None

    # ── Pruning ───────────────────────────────────────────────────────────────

    async def _prune(self) -> None:
        try:
            async with self._sf() as db:
                await db.execute(text(f"""
                    DELETE FROM scanner_replay_snapshots
                    WHERE id NOT IN (
                        SELECT id FROM scanner_replay_snapshots
                        ORDER BY scanned_at DESC LIMIT {_MAX_ROWS}
                    )
                """))
                await db.commit()
        except Exception:
            pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_top_scores(results: list[dict]) -> list[dict]:
    scored = [r for r in results if r.get("adjusted_score") is not None]
    scored.sort(key=lambda x: x.get("adjusted_score", 0), reverse=True)
    return [
        {
            "symbol": r.get("symbol"),
            "adjusted_score": r.get("adjusted_score"),
            "confidence": r.get("confidence"),
            "outcome": r.get("outcome"),
            "direction": r.get("direction"),
        }
        for r in scored[:10]
    ]


def _parse_json_field(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return val


def _replay_row_summary(row: Any) -> dict[str, Any]:
    (id_, at, dur, tc, acc, rej, gat, top_scores, gate_summary, regime_snapshot) = row
    return {
        "id": id_,
        "scanned_at": at.isoformat() if at else None,
        "scan_duration_seconds": float(dur) if dur else None,
        "total_candidates": tc,
        "accepted": acc,
        "rejected": rej,
        "gated": gat,
        "top_scores": _parse_json_field(top_scores),
        "gate_summary": _parse_json_field(gate_summary),
        "regime_snapshot": _parse_json_field(regime_snapshot),
    }


def _replay_row_full(row: Any) -> dict[str, Any]:
    (id_, at, dur, tc, acc, rej, gat,
     market_context, symbol_results, top_scores,
     gate_summary, regime_snapshot, stage_timings) = row
    return {
        "id": id_,
        "scanned_at": at.isoformat() if at else None,
        "scan_duration_seconds": float(dur) if dur else None,
        "total_candidates": tc,
        "accepted": acc,
        "rejected": rej,
        "gated": gat,
        "market_context": _parse_json_field(market_context),
        "symbol_results": _parse_json_field(symbol_results),
        "top_scores": _parse_json_field(top_scores),
        "gate_summary": _parse_json_field(gate_summary),
        "regime_snapshot": _parse_json_field(regime_snapshot),
        "stage_timings": _parse_json_field(stage_timings),
    }
