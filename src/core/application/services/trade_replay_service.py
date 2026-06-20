"""TradeReplayService — Phase 20.6 Section 4.

Creates and retrieves a full lifecycle event timeline for every signal.

Event types (in chronological order):
  GENERATED    — Signal created (all component scores, regime, prices)
  ENTRY        — Signal accepted / converted to trade
  MFE_PEAK     — Best price reached (populated with real-time data if available)
  MAE_TROUGH   — Worst price reached (populated with real-time data if available)
  EXIT         — Trade closed (target hit, stop hit, or expired)

For historical signals, TradeReplayService reconstructs:
  GENERATED from signal_analytics creation data
  EXIT       from outcome + timing columns

MFE_PEAK and MAE_TROUGH require intraday price tracking and are populated
only when SignalOutcomeTrackerService provides sub-event timestamps.

Replay timeline view includes at every event:
  underlying_price, option_premium, iv_percentile, vwap_distance_pct,
  oi_change_pct, volume_ratio, adx, mtf_alignment, regime

Backfill: create_replay_events() reads signal_analytics and writes to
signal_replay_events. Safe to re-run — deduplicates by signal_id.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

_EVENT_GENERATED  = "GENERATED"
_EVENT_ENTRY      = "ENTRY"
_EVENT_MFE_PEAK   = "MFE_PEAK"
_EVENT_MAE_TROUGH = "MAE_TROUGH"
_EVENT_EXIT       = "EXIT"
_EVENT_EXPIRED    = "EXPIRED"


class TradeReplayService:
    """Builds and retrieves signal lifecycle replay timelines."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ── Public API ────────────────────────────────────────────────────────────

    async def backfill_unreplayed(self, limit: int = 300) -> dict:
        """Create replay events for signals that have no replay data yet.

        Eligible: has outcome (completed) AND no existing replay events.
        Safe to re-run — checks for existing events before inserting.
        """
        cutoff = datetime.now(UTC) - timedelta(days=365)
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT sa.signal_id,
                          sa.ticker, sa.direction, sa.regime, sa.dte,
                          sa.adjusted_score, sa.confidence,
                          sa.entry_price, sa.stop_loss_price, sa.target_price,
                          sa.option_entry, sa.option_type,
                          sa.adx_at_signal, sa.volume_ratio_at_signal, sa.rsi_at_signal,
                          sa.mtf_alignment,
                          sa.mfe_pct, sa.mae_pct, sa.pnl_pct, sa.current_return_pct,
                          sa.time_to_target_minutes, sa.time_to_stop_minutes,
                          sa.outcome, sa.target_hit, sa.stop_hit,
                          sa.was_accepted, sa.created_at, sa.outcome_checked_at
                        FROM signal_analytics sa
                        WHERE sa.outcome IS NOT NULL
                          AND sa.signal_id IS NOT NULL
                          AND sa.created_at >= :cutoff
                          AND NOT EXISTS (
                            SELECT 1 FROM signal_replay_events sre
                            WHERE sre.signal_id = sa.signal_id LIMIT 1
                          )
                        ORDER BY sa.created_at DESC
                        LIMIT :lim
                    """),
                    {"cutoff": cutoff, "lim": limit},
                )
                rows = r.fetchall()
        except Exception as exc:
            _log.warning("replay.backfill_fetch_error: %s", exc)
            return {"error": str(exc)}

        created = skipped = errors = 0
        for row in rows:
            if not row.signal_id:
                skipped += 1
                continue
            try:
                events = _build_events(dict(row._mapping))
                await self._insert_events(row.signal_id, events)
                created += len(events)
            except Exception as exc:
                _log.warning("replay.backfill_insert_error signal=%s: %s", row.signal_id, exc)
                errors += 1

        _log.info("replay.backfill signals=%d events=%d errors=%d",
                  len(rows) - skipped, created, errors)
        return {
            "signals_processed": len(rows) - skipped,
            "events_created":    created,
            "skipped":           skipped,
            "errors":            errors,
        }

    async def create_replay_events(self, signal_id: str) -> list[dict]:
        """Create or refresh replay events for a single signal by ID."""
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          signal_id, ticker, direction, regime, dte,
                          adjusted_score, confidence,
                          entry_price, stop_loss_price, target_price,
                          option_entry, option_type,
                          adx_at_signal, volume_ratio_at_signal, rsi_at_signal,
                          mtf_alignment,
                          mfe_pct, mae_pct, pnl_pct, current_return_pct,
                          time_to_target_minutes, time_to_stop_minutes,
                          outcome, target_hit, stop_hit,
                          was_accepted, created_at, outcome_checked_at
                        FROM signal_analytics
                        WHERE signal_id = :sid LIMIT 1
                    """),
                    {"sid": signal_id},
                )
                row = r.fetchone()
        except Exception as exc:
            return [{"error": str(exc)}]

        if not row:
            return [{"error": f"Signal {signal_id} not found"}]
        if row.outcome is None:
            return [{"status": "PENDING", "message": "Signal not yet completed"}]

        events = _build_events(dict(row._mapping))

        # Delete existing events then re-insert (idempotent)
        try:
            async with self._sf() as db:
                await db.execute(
                    text("DELETE FROM signal_replay_events WHERE signal_id = :sid"),
                    {"sid": signal_id},
                )
                await db.commit()
        except Exception:
            pass

        await self._insert_events(signal_id, events)
        return events

    async def get_timeline(self, signal_id: str) -> dict:
        """Retrieve the full replay timeline for a signal."""
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT
                          event_type, event_sequence, event_time,
                          underlying_price, option_premium, iv_percentile,
                          vwap_distance_pct, oi_change_pct, volume_ratio,
                          adx, mtf_alignment, regime,
                          adjusted_score, confidence, pnl_pct_at_event,
                          event_data_json
                        FROM signal_replay_events
                        WHERE signal_id = :sid
                        ORDER BY event_sequence
                    """),
                    {"sid": signal_id},
                )
                rows = r.fetchall()
        except Exception as exc:
            return {"error": str(exc)}

        if not rows:
            return {"signal_id": signal_id, "status": "NO_REPLAY_DATA",
                    "note": "Run create_replay_events() to build the timeline."}

        def _f(v): return float(v) if v is not None else None

        events = []
        for row in rows:
            extra = {}
            if row[15]:
                try:
                    extra = json.loads(row[15])
                except Exception:
                    pass
            events.append({
                "event_type":        row[0],
                "sequence":          int(row[1]),
                "event_time":        row[2].isoformat() if row[2] else None,
                "underlying_price":  _f(row[3]),
                "option_premium":    _f(row[4]),
                "iv_percentile":     _f(row[5]),
                "vwap_distance_pct": _f(row[6]),
                "oi_change_pct":     _f(row[7]),
                "volume_ratio":      _f(row[8]),
                "adx":               _f(row[9]),
                "mtf_alignment":     row[10],
                "regime":            row[11],
                "adjusted_score":    _f(row[12]),
                "confidence":        _f(row[13]),
                "pnl_pct_at_event":  _f(row[14]),
                **extra,
            })

        return {
            "signal_id":   signal_id,
            "event_count": len(events),
            "events":      events,
        }

    async def get_replay_coverage(self) -> dict:
        """Return replay backfill coverage statistics."""
        try:
            async with self._sf() as db:
                r = await db.execute(text("""
                    SELECT
                      (SELECT COUNT(*) FROM signal_analytics WHERE outcome IS NOT NULL) AS total_completed,
                      (SELECT COUNT(DISTINCT signal_id) FROM signal_replay_events)      AS replayed,
                      (SELECT COUNT(*) FROM signal_replay_events)                       AS total_events
                """))
                row = r.fetchone()
        except Exception as exc:
            return {"error": str(exc)}

        total     = int(row[0] or 0)
        replayed  = int(row[1] or 0)
        events    = int(row[2] or 0)
        return {
            "total_completed_signals": total,
            "replayed_signals":        replayed,
            "coverage_pct":            round(replayed / max(total, 1) * 100, 1),
            "total_replay_events":     events,
            "avg_events_per_signal":   round(events / max(replayed, 1), 1),
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _insert_events(self, signal_id: str, events: list[dict]) -> None:
        if not events:
            return
        try:
            async with self._sf() as db:
                for ev in events:
                    await db.execute(
                        text("""
                            INSERT INTO signal_replay_events (
                              signal_id, event_type, event_sequence, event_time,
                              underlying_price, option_premium, iv_percentile,
                              vwap_distance_pct, oi_change_pct, volume_ratio,
                              adx, mtf_alignment, regime,
                              adjusted_score, confidence, pnl_pct_at_event,
                              event_data_json
                            ) VALUES (
                              :signal_id, :event_type, :seq, :event_time,
                              :underlying_price, :option_premium, :iv_percentile,
                              :vwap_distance_pct, :oi_change_pct, :volume_ratio,
                              :adx, :mtf_alignment, :regime,
                              :adjusted_score, :confidence, :pnl_at,
                              :data_json
                            )
                        """),
                        {
                            "signal_id":         signal_id,
                            "event_type":        ev["event_type"],
                            "seq":               ev["event_sequence"],
                            "event_time":        ev.get("event_time"),
                            "underlying_price":  ev.get("underlying_price"),
                            "option_premium":    ev.get("option_premium"),
                            "iv_percentile":     ev.get("iv_percentile"),
                            "vwap_distance_pct": ev.get("vwap_distance_pct"),
                            "oi_change_pct":     ev.get("oi_change_pct"),
                            "volume_ratio":      ev.get("volume_ratio"),
                            "adx":               ev.get("adx"),
                            "mtf_alignment":     ev.get("mtf_alignment"),
                            "regime":            ev.get("regime"),
                            "adjusted_score":    ev.get("adjusted_score"),
                            "confidence":        ev.get("confidence"),
                            "pnl_at":            ev.get("pnl_pct_at_event"),
                            "data_json":         ev.get("event_data_json"),
                        },
                    )
                await db.commit()
        except Exception as exc:
            _log.warning("replay.insert_error signal=%s: %s", signal_id, exc)
            raise


# ── Pure-function event builder ───────────────────────────────────────────────

def _build_events(rec: dict) -> list[dict]:
    """Build lifecycle events from a signal_analytics record.

    Returns a list ordered by event_sequence.
    Events reconstructed from available data:
      1. GENERATED — at created_at with all signal-time data
      2. ENTRY     — same time as GENERATED if was_accepted=True
      3. MFE_PEAK  — estimated from mfe_pct (time unknown without real-time tracking)
      4. MAE_TROUGH— estimated from mae_pct
      5. EXIT      — at outcome_checked_at (approximate) or created_at + time_to_*
    """
    created   = rec.get("created_at")
    outcome   = (rec.get("outcome") or "").upper()
    target_hit = rec.get("target_hit")
    stop_hit   = rec.get("stop_hit")
    was_accept = rec.get("was_accepted")

    ttt = rec.get("time_to_target_minutes")
    tts = rec.get("time_to_stop_minutes")
    mfe = rec.get("mfe_pct")
    mae = rec.get("mae_pct")
    pnl = rec.get("pnl_pct") or rec.get("current_return_pct")

    def _base(seq: int, etype: str, event_time=None, pnl_at=None, extra: dict | None = None) -> dict:
        return {
            "event_type":        etype,
            "event_sequence":    seq,
            "event_time":        event_time,
            "underlying_price":  rec.get("entry_price"),
            "option_premium":    rec.get("option_entry"),
            "iv_percentile":     None,  # not stored at signal time in current schema
            "vwap_distance_pct": None,
            "oi_change_pct":     None,
            "volume_ratio":      rec.get("volume_ratio_at_signal"),
            "adx":               rec.get("adx_at_signal"),
            "mtf_alignment":     rec.get("mtf_alignment"),
            "regime":            rec.get("regime"),
            "adjusted_score":    rec.get("adjusted_score"),
            "confidence":        rec.get("confidence"),
            "pnl_pct_at_event":  pnl_at,
            "event_data_json":   json.dumps(extra) if extra else None,
        }

    events = []
    seq = 1

    # ── 1. GENERATED ─────────────────────────────────────────────────────────
    events.append(_base(seq, _EVENT_GENERATED, event_time=created, pnl_at=0.0, extra={
        "ticker":        rec.get("ticker"),
        "direction":     rec.get("direction"),
        "dte":           rec.get("dte"),
        "entry_price":   str(rec.get("entry_price") or ""),
        "target_price":  str(rec.get("target_price") or ""),
        "stop_price":    str(rec.get("stop_loss_price") or ""),
        "option_type":   rec.get("option_type"),
    }))
    seq += 1

    # ── 2. ENTRY (if accepted) ────────────────────────────────────────────────
    if was_accept:
        events.append(_base(seq, _EVENT_ENTRY, event_time=created, pnl_at=0.0))
        seq += 1

    # ── 3. MAE_TROUGH (adverse move, happened before exit) ───────────────────
    if mae is not None and float(mae) > 0.001:
        # Time of worst adverse move: approximately tts * 0.3 for losers, or tts * 0.6 for winners
        if created and tts:
            fraction = 0.3 if stop_hit else 0.5
            mae_time = created + __import__('datetime').timedelta(minutes=float(tts) * fraction)
        elif created and ttt:
            mae_time = created + __import__('datetime').timedelta(minutes=float(ttt) * 0.2)
        else:
            mae_time = None
        events.append(_base(seq, _EVENT_MAE_TROUGH, event_time=mae_time,
                            pnl_at=-float(mae), extra={"mae_pct": float(mae)}))
        seq += 1

    # ── 4. MFE_PEAK (favorable move) ─────────────────────────────────────────
    if mfe is not None and float(mfe) > 0.001:
        if created and ttt and target_hit:
            mfe_time = created + __import__('datetime').timedelta(minutes=float(ttt) * 0.8)
        elif created and tts and not target_hit:
            mfe_time = created + __import__('datetime').timedelta(minutes=float(tts) * 0.4)
        else:
            mfe_time = None
        events.append(_base(seq, _EVENT_MFE_PEAK, event_time=mfe_time,
                            pnl_at=float(mfe), extra={"mfe_pct": float(mfe)}))
        seq += 1

    # ── 5. EXIT ───────────────────────────────────────────────────────────────
    if target_hit and ttt is not None and created:
        exit_time = created + __import__('datetime').timedelta(minutes=float(ttt))
        exit_type = _EVENT_EXIT
        exit_extra = {"outcome": "TARGET_HIT", "time_to_target_minutes": ttt}
    elif stop_hit and tts is not None and created:
        exit_time = created + __import__('datetime').timedelta(minutes=float(tts))
        exit_type = _EVENT_EXIT
        exit_extra = {"outcome": "STOP_HIT", "time_to_stop_minutes": tts}
    else:
        exit_time = rec.get("outcome_checked_at") or created
        exit_type = _EVENT_EXPIRED if outcome == "EXPIRED" else _EVENT_EXIT
        exit_extra = {"outcome": outcome}

    events.append(_base(seq, exit_type, event_time=exit_time,
                        pnl_at=float(pnl) if pnl else None, extra=exit_extra))

    return events
