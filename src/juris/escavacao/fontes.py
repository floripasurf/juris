"""Source-confidence signal for the composite ranking (ADR-0017, frente C).

The deep corpus records *where* each inteiro teor came from (``InteiroTeor.fonte``).
The composite ranker uses this confidence as one of its signals — a precedent
backed by the full TST acórdão outranks the same case known only through the
DataJud movements trail. This is the **tracked contract**; the ranker itself
(engine-local) consumes :func:`fonte_confianca` plus the ``parcial`` flag.
"""

from __future__ import annotations

# Confidence per source, in [0, 1]. Full-text official sources rank highest; the
# DataJud trail (procedural movements, not the acórdão) is deliberately low.
_FONTE_CONFIANCA: dict[str, float] = {
    "tst": 1.0,
    "stf": 1.0,
    "stj": 1.0,
    "esaj": 0.9,
    "cjsg": 0.9,
    "datajud": 0.3,  # movements trail only (parcial)
}

_UNKNOWN_CONFIANCA = 0.2  # an unrecognised source is trusted little, but not zero


def fonte_confianca(fonte: str) -> float:
    """Confidence in a source, in ``[0, 1]`` — a ranking signal (higher = stronger)."""
    return _FONTE_CONFIANCA.get(fonte.lower().strip(), _UNKNOWN_CONFIANCA)
