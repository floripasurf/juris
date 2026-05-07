"""CNJ number → court auto-detection per Resolução CNJ 65/2008."""

from __future__ import annotations

import re

_CNJ_RE = re.compile(r"^(\d{7})-(\d{2})\.(\d{4})\.(\d)\.(\d{2})\.(\d{4})$")

# J=8 state code → TJ identifier
_TJ_MAP: dict[str, str] = {
    "01": "tjac",
    "02": "tjal",
    "03": "tjap",
    "04": "tjam",
    "05": "tjba",
    "06": "tjce",
    "07": "tjdft",
    "08": "tjes",
    "09": "tjgo",
    "10": "tjma",
    "11": "tjmt",
    "12": "tjms",
    "13": "tjmg",
    "14": "tjpa",
    "15": "tjpb",
    "16": "tjpr",
    "17": "tjpe",
    "18": "tjpi",
    "19": "tjrj",
    "20": "tjrn",
    "21": "tjrs",
    "22": "tjro",
    "23": "tjrr",
    "24": "tjsc",
    "25": "tjse",
    "26": "tjsp",
    "27": "tjto",
}


def cnj_to_court(cnj: str) -> str | None:
    """Map a CNJ number to its court identifier.

    Implements Resolução CNJ 65/2008 segment mapping.

    Args:
        cnj: CNJ process number string (NNNNNNN-DD.AAAA.J.TR.OOOO).

    Returns:
        Court identifier string (e.g. "stf", "trf1", "tjsp"), or None if
        the input is invalid or the segment combination is not searchable.
    """
    m = _CNJ_RE.match(cnj.strip())
    if not m:
        return None
    j = m.group(4)  # Justiça segment
    tr = m.group(5)  # Tribunal segment

    if j == "1":
        return "stf"
    if j == "2":
        return None  # CNJ itself — not searchable
    if j == "3":
        return "stj"
    if j == "4":
        return f"trf{int(tr)}"
    if j == "5":
        return "tst" if tr == "00" else f"trt{int(tr)}"
    if j == "6":
        return "tse" if tr == "00" else f"tre{int(tr)}"
    if j == "7":
        return "stm" if tr == "00" else None
    if j == "8":
        return _TJ_MAP.get(tr)
    if j == "9":
        return None  # Justiça Militar Estadual (rare)
    return None
