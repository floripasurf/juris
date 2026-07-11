"""Small helpers to narrow untyped JSON (``json.load`` → ``Any``) safely.

Manifests/receipts are read from disk as ``Any``; calling ``.get()`` on a value that
might be ``None``/non-dict is a latent crash. These coerce to a known shape so callers
type-check and never blow up on a malformed file.
"""

from __future__ import annotations

from typing import Any


def ensure_dict(value: object) -> dict[str, Any]:
    """Return ``value`` if it is a dict, else an empty dict."""
    return value if isinstance(value, dict) else {}


def ensure_list(value: object) -> list[Any]:
    """Return ``value`` if it is a list, else an empty list."""
    return value if isinstance(value, list) else []
