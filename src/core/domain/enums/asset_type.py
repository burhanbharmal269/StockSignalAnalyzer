"""Asset class enumeration.

Used across all layers. Never hardcode the string "FNO" or "EQUITY" —
always import this enum.

Reference: docs/09_CLAUDE_EXECUTION_RULES.md (Future Scalability Rules)
"""

from enum import StrEnum


class AssetType(StrEnum):
    """Supported asset classes.

    New asset classes are added here as the platform expands (Phase 2+).
    No other module may define a competing asset type concept.
    """

    FNO = "FNO"
    EQUITY = "EQUITY"
    COMMODITY = "COMMODITY"
    CURRENCY = "CURRENCY"
