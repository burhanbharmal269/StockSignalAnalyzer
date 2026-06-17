"""UserRole — role enum for application users."""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    VIEWER = "VIEWER"
