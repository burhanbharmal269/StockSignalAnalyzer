"""SignalQualificationService — Phase 23 §2.

Assigns a research grade (A+/A/B/C/D) to every accepted signal.

IMPORTANT:
  This grade is PURELY a research label.
  It does NOT affect: score, confidence, acceptance, or position sizing.
  It is stored alongside the signal for post-hoc cohort analysis only.

Grade criteria (applied in order):
  A+  Institutional Grade   score ≥ 85, conf ≥ 75, grade A/B, dq ≥ 80, context NORMAL/CAUTION
  A   High Quality          score ≥ 75, conf ≥ 70, grade A/B/C
  B   Good Quality          score ≥ 65, conf ≥ 65
  C   Research Candidate    score ≥ 55, conf ≥ 60
  D   Observation Only      accepted but does not meet C criteria
"""

from __future__ import annotations

from datetime import UTC, datetime

_QUALIFICATION_VERSION = "1.0"

_HIGH_QUALITY_EXEC_GRADES = {"A", "B"}
_GOOD_EXEC_GRADES          = {"A", "B", "C"}


def _reason(grade: str, score: float, conf: float, exec_grade: str | None) -> str:
    if grade == "A+":
        return (
            f"Institutional grade: score={score:.1f}≥85, conf={conf:.1f}≥75, "
            f"exec={exec_grade}, context=NORMAL/CAUTION"
        )
    if grade == "A":
        return f"High quality: score={score:.1f}≥75, conf={conf:.1f}≥70, exec={exec_grade}"
    if grade == "B":
        return f"Good quality: score={score:.1f}≥65, conf={conf:.1f}≥65"
    if grade == "C":
        return f"Research candidate: score={score:.1f}≥55, conf={conf:.1f}≥60"
    return f"Observation only: score={score:.1f}, conf={conf:.1f} (below B criteria)"


class SignalQualificationService:
    """Pure (stateless) research grade assignment.  No DB access."""

    def qualify(
        self,
        score: float | None,
        confidence: float | None,
        execution_grade: str | None,
        data_quality_score: int | None,
        market_context: str | None,
        was_accepted: bool,
    ) -> dict | None:
        """Return qualification dict or None (for rejected signals).

        Returns:
            {
                "qualification_grade": "A+",
                "qualification_reason": "...",
                "qualification_version": "1.0",
                "qualification_timestamp": "...",
            }
        """
        if not was_accepted:
            return None

        s    = float(score or 0)
        c    = float(confidence or 0)
        dq   = int(data_quality_score or 0)
        eg   = (execution_grade or "").upper()
        ctx  = (market_context or "").upper()

        if (
            s >= 85
            and c >= 75
            and eg in _HIGH_QUALITY_EXEC_GRADES
            and (data_quality_score is None or dq >= 80)
            and ctx in ("NORMAL", "CAUTION", "")
        ):
            grade = "A+"
        elif s >= 75 and c >= 70 and eg in _GOOD_EXEC_GRADES:
            grade = "A"
        elif s >= 65 and c >= 65:
            grade = "B"
        elif s >= 55 and c >= 60:
            grade = "C"
        else:
            grade = "D"

        return {
            "qualification_grade":     grade,
            "qualification_reason":    _reason(grade, s, c, eg or None),
            "qualification_version":   _QUALIFICATION_VERSION,
            "qualification_timestamp": datetime.now(UTC),
        }
