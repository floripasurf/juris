"""Tracked-processo list — the lawyer's "my processes" set + seed parsing.

Shared by the CLI (track/avisos/connect commands) and the web layer so neither
reaches into the other. Single-user (Phase 1) persists via the credential store
(Keychain) as ``tracked_processos`` JSON; pass a per-tenant ``db`` and the list
lives in that tenant's store instead (multi-tenant isolation).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from juris.persistence.local_db import LocalDB


def get_tracked(db: LocalDB | None = None) -> list[dict[str, str]]:
    """Load the tracked-processo list (``[{"numero_cnj", "tribunal"}, ...]``).

    From the tenant's ``db`` when given; otherwise the single-user Keychain.
    """
    if db is not None:
        return db.get_tracked_list()

    from juris.core.credentials import get_credential

    raw = get_credential("tracked_processos")
    if not raw:
        return []
    try:
        return cast("list[dict[str, str]]", json.loads(raw))
    except json.JSONDecodeError:
        return []


def set_tracked(entries: list[dict[str, str]], db: LocalDB | None = None) -> None:
    """Persist the tracked-processo list (to the tenant's ``db`` or the Keychain)."""
    if db is not None:
        db.set_tracked_list(entries)
        return

    from juris.core.credentials import store_credential

    store_credential("tracked_processos", json.dumps(entries))


def merge_tracked(tracked: list[dict[str, str]], entries: list[dict[str, str]]) -> tuple[list[dict[str, str]], int]:
    """Add ``entries`` to a tracked list, deduping by (tribunal, cnj).

    The input list is not mutated.

    Returns:
        Tuple ``(merged, added_count)``.
    """
    merged = list(tracked)
    existing = {f"{p['tribunal']}:{p['numero_cnj']}" for p in merged}
    added = 0
    for entry in entries:
        key = f"{entry['tribunal']}:{entry['numero_cnj']}"
        if key in existing:
            continue
        existing.add(key)
        merged.append(entry)
        added += 1
    return merged, added


def parse_cnj_seed(text: str, default_tribunal: str) -> tuple[list[dict[str, str]], list[str]]:
    """Parse a seed list of CNJs (one per line) into tracked-processo entries.

    Blank lines and ``#`` comments are skipped. The tribunal is derived from each
    CNJ via :func:`cnj_to_court` when possible, falling back to
    ``default_tribunal``. Invalid CNJs are collected as error strings rather than
    raising, so one bad line never aborts the whole import.

    Returns:
        Tuple ``(entries, errors)`` — entries are ``{"numero_cnj", "tribunal"}``.
    """
    from juris.core.types import NumeroCNJ
    from juris.search.cnj_router import cnj_to_court

    entries: list[dict[str, str]] = []
    errors: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            NumeroCNJ(line)
        except ValueError:
            errors.append(f"CNJ inválido: {line}")
            continue
        entries.append({"numero_cnj": line, "tribunal": cnj_to_court(line) or default_tribunal})
    return entries, errors
