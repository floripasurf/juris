"""Shared utility functions for the unified multi-court search system."""

from __future__ import annotations

import re
from datetime import date, datetime

from juris.core.types import CNJ_NUMERO_PATTERN

# CNJ raw digits: NNNNNNN DD AAAA J TR OOOO = 7+2+4+1+2+4 = 20 digits
_CNJ_DIGITS_PATTERN = re.compile(r"^\d{20}$")

# Brazilian state abbreviations for OAB parsing
_BR_STATES = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}

# Common boilerplate header patterns to strip from ementas
_BOILERPLATE_PATTERNS = [
    re.compile(r"TRIBUNAL\s+(REGIONAL\s+FEDERAL|DE\s+JUSTIÇA|SUPERIOR)[^\n]*\n?", re.IGNORECASE),
    re.compile(r"TRF\s*\d+[ª°]?\s*REGIÃO[^\n]*\n?", re.IGNORECASE),
    re.compile(r"STF\s*[-–]\s*[^\n]*\n?", re.IGNORECASE),
    re.compile(r"STJ\s*[-–]\s*[^\n]*\n?", re.IGNORECASE),
    re.compile(r"PODER\s+JUDICIÁRIO[^\n]*\n?", re.IGNORECASE),
    re.compile(r"DIÁRIO\s+DA\s+JUSTIÇA[^\n]*\n?", re.IGNORECASE),
]

# Date extraction patterns
_DATE_DD_MM_YYYY = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_DATE_YYYY_MM_DD = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _insert_cnj_formatting(digits: str) -> str:
    """Format a 20-digit string into CNJ number format NNNNNNN-DD.AAAA.J.TR.OOOO."""
    # NNNNNNN-DD.AAAA.J.TR.OOOO
    # positions: 0-6 (7), 7-8 (2), 9-12 (4), 13 (1), 14-15 (2), 16-19 (4)
    return f"{digits[0:7]}-{digits[7:9]}.{digits[9:13]}.{digits[13]}.{digits[14:16]}.{digits[16:20]}"


def normalize_cnj(raw: str | None) -> str | None:
    """Normalize a CNJ process number to canonical format NNNNNNN-DD.AAAA.J.TR.OOOO.

    Args:
        raw: Raw CNJ number string, possibly with or without formatting, or None.

    Returns:
        Formatted CNJ string if valid, None otherwise.
    """
    if raw is None:
        return None

    stripped = raw.strip()

    # Already formatted — validate and return
    if CNJ_NUMERO_PATTERN.match(stripped):
        return stripped

    # Try as 20 raw digits — insert formatting then validate
    digits_only = re.sub(r"[^\d]", "", stripped)
    if len(digits_only) == 20:
        formatted = _insert_cnj_formatting(digits_only)
        if CNJ_NUMERO_PATTERN.match(formatted):
            return formatted

    return None


def parse_br_date(raw: str | None) -> date | None:
    """Parse a Brazilian date string into a date object.

    Supports dd/mm/yyyy, yyyy-mm-dd, and embedded patterns like
    "Publicado em DJe de 15/06/2024".

    Args:
        raw: Raw date string or None.

    Returns:
        Parsed date, or None if parsing fails.
    """
    if raw is None:
        return None

    # Try yyyy-mm-dd first (ISO format, unambiguous)
    m = _DATE_YYYY_MM_DD.search(raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # Try dd/mm/yyyy (Brazilian format)
    m = _DATE_DD_MM_YYYY.search(raw)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    return None


def clean_ementa(text: str) -> str:
    """Clean and normalize an ementa (legal case summary) string.

    Strips HTML tags, collapses whitespace, and removes common boilerplate
    tribunal headers.

    Args:
        text: Raw ementa text, possibly containing HTML or boilerplate.

    Returns:
        Cleaned ementa string.
    """
    # Strip HTML tags
    result = re.sub(r"<[^>]+>", "", text)

    # Strip boilerplate headers
    for pattern in _BOILERPLATE_PATTERNS:
        result = pattern.sub("", result)

    # Collapse whitespace (spaces, tabs, newlines) into single space
    result = re.sub(r"\s+", " ", result)

    return result.strip()


def normalize_oab(raw: str) -> tuple[str | None, str]:
    """Parse an OAB registration number into (state, number) tuple.

    Handles formats:
    - "SP123456"   -> ("SP", "123456")
    - "123456/SP"  -> ("SP", "123456")
    - "123456"     -> (None, "123456")

    Args:
        raw: Raw OAB string.

    Returns:
        Tuple of (state_abbreviation_or_None, number_string).
    """
    stripped = raw.strip()

    # Format: NUMBER/STATE  e.g. "123456/SP"
    m = re.match(r"^(\d+)\s*/\s*([A-Za-z]{2})$", stripped)
    if m:
        state = m.group(2).upper()
        if state in _BR_STATES:
            return (state, m.group(1))

    # Format: STATE + NUMBER  e.g. "SP123456"
    m = re.match(r"^([A-Za-z]{2})(\d+)$", stripped)
    if m:
        state = m.group(1).upper()
        if state in _BR_STATES:
            return (state, m.group(2))

    # Bare number
    m = re.match(r"^(\d+)$", stripped)
    if m:
        return (None, m.group(1))

    # Fallback: return as-is with no state
    return (None, stripped)
