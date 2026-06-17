"""ProductType — order product / margin category."""

from __future__ import annotations

from enum import StrEnum


class ProductType(StrEnum):
    MIS = "MIS"    # Margin Intraday Square-off
    NRML = "NRML"  # Normal (overnight carry)
    CNC = "CNC"    # Cash and Carry (delivery equity)
