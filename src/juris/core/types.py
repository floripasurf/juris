"""Shared value objects used across the project."""

from __future__ import annotations

import re
from dataclasses import dataclass

# CNJ process number format: NNNNNNN-DD.AAAA.J.TR.OOOO
CNJ_NUMERO_PATTERN = re.compile(r"^\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}$")


@dataclass(frozen=True, slots=True)
class NumeroCNJ:
    """Validated CNJ process number."""

    value: str

    def __post_init__(self) -> None:
        if not CNJ_NUMERO_PATTERN.match(self.value):
            msg = f"Invalid CNJ number format: {self.value}"
            raise ValueError(msg)

    @property
    def justica(self) -> str:
        """Extract justice branch code. Format: NNNNNNN-DD.AAAA.J.TR.OOOO"""
        # Split on dots: ['NNNNNNN-DD', 'AAAA', 'J', 'TR', 'OOOO']
        parts = self.value.split(".")
        return parts[2]

    @property
    def tribunal(self) -> str:
        """Extract tribunal code."""
        parts = self.value.split(".")
        return parts[3]

    @property
    def origem(self) -> str:
        """Extract origin code."""
        parts = self.value.split(".")
        return parts[4]

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class TenantId:
    """Tenant identifier — every multi-tenant operation requires this."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            msg = "TenantId cannot be empty"
            raise ValueError(msg)

    def __str__(self) -> str:
        return self.value
