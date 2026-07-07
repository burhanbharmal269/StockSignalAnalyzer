"""FalsePositiveAnalyzerService — FP/FN rate by component and score bucket.

For each scoring component, signals are bucketed by score range (0-60, 60-70,
70-80, 80-90, 90-100). False positive = high component score but LOSS.
False negative = low component score but WIN. Read-only on signal_analytics.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

_COMPONENT_COLS = {
    "oi_buildup": "oi_score",
    "trend": "trend_score",
    "option_chain": "option_chain_score",
    "volume": "volume_score",
    "vwap": "vwap_score",
    "sentiment": "sentiment_score",
    "iv_analysis": "iv_score",
}

# Max score per component — used to normalise raw score to 0-100 range
_MAX_SCORES = {
    "oi_buildup": 25, "trend": 20, "option_chain": 20,
    "volume": 15, "vwap": 10, "sentiment": 5, "iv_analysis": 5,
}

_BUCKETS = [
    ("0-60",  0.0,  60.0),
    ("60-70", 60.0, 70.0),
    ("70-80", 70.0, 80.0),
    ("80-90", 80.0, 90.0),
    ("90-100", 90.0, 101.0),
]


class FalsePositiveAnalyzerService:
    """Computes and persists false positive / negative rates."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def compute_analysis(self, lookback_days: int = 90) -> None:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT oi_score, trend_score, option_chain_score,
                               volume_score, vwap_score, sentiment_score, iv_score,
                               outcome
                        FROM signal_analytics
                        WHERE created_at > NOW() - :days * INTERVAL '1 day'
                          AND outcome IN ('WIN', 'LOSS')
                    """),
                    {"days": lookback_days},
                )
                rows = r.fetchall()

            if not rows:
                return

            col_list = list(_COMPONENT_COLS.values())
            comp_list = list(_COMPONENT_COLS.keys())

            async with self._sf() as db:
                for c_idx, comp in enumerate(comp_list):
                    max_score = _MAX_SCORES[comp]
                    for bucket_label, low, high in _BUCKETS:
                        # Normalise raw component score to 0-100 scale for bucketing
                        in_bucket_wins = 0
                        in_bucket_losses = 0
                        out_bucket_wins = 0

                        for row in rows:
                            raw = float(row[c_idx] or 0.0)
                            normalised = (raw / max_score * 100) if max_score > 0 else 0.0
                            is_win = row[7] == "WIN"
                            in_b = low <= normalised < high

                            if in_b and not is_win:
                                in_bucket_losses += 1
                            if in_b and is_win:
                                in_bucket_wins += 1
                            if not in_b and is_win:
                                out_bucket_wins += 1

                        total_in = in_bucket_wins + in_bucket_losses
                        # FP rate: of signals in this bucket, what fraction are LOSS?
                        fp_rate = (in_bucket_losses / total_in) if total_in > 0 else None
                        # FN rate: for high buckets, irrelevant; show signal-level
                        # out-of-bucket WINs as proportion of all wins
                        total_wins = sum(1 for r in rows if r[7] == "WIN")
                        fn_rate = (out_bucket_wins / total_wins) if total_wins > 0 and low >= 60 else None

                        await db.execute(
                            text("""
                                INSERT INTO research_false_positive_analysis
                                    (component, score_bucket, false_positive_rate,
                                     false_negative_rate, sample_size,
                                     lookback_days, computed_at)
                                VALUES (:comp, :bucket, :fp, :fn, :cnt, :days, NOW())
                            """),
                            {
                                "comp": comp, "bucket": bucket_label,
                                "fp": round(fp_rate, 4) if fp_rate is not None else None,
                                "fn": round(fn_rate, 4) if fn_rate is not None else None,
                                "cnt": total_in, "days": lookback_days,
                            },
                        )
                await db.commit()
            _log.info("false_positive_analyzer_service.computed")
        except Exception as exc:
            _log.warning("false_positive_analyzer_service.compute_failed: %s", exc)

    async def get_analysis(self, lookback_days: int = 90) -> list[dict]:
        try:
            async with self._sf() as db:
                r = await db.execute(
                    text("""
                        SELECT component, score_bucket, false_positive_rate,
                               false_negative_rate, sample_size, computed_at
                        FROM research_false_positive_analysis
                        WHERE lookback_days = :days
                        ORDER BY computed_at DESC, component, score_bucket
                        LIMIT 500
                    """),
                    {"days": lookback_days},
                )
                return [dict(row) for row in r.mappings().fetchall()]
        except Exception as exc:
            _log.warning("false_positive_analyzer_service.get_failed: %s", exc)
            return []
