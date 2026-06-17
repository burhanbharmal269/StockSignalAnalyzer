"""SignalStrength — strength tier of a generated signal.

Maps directly to the score bucket used in the signal fingerprint.
"""

from __future__ import annotations

from enum import StrEnum


class SignalStrength(StrEnum):
    STRONG = "STRONG"       # adjusted_score >= 85
    STANDARD = "STANDARD"   # 70 <= adjusted_score < 85
