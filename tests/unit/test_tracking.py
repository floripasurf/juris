"""Tests for tracked-list routing — Keychain (single-user) vs per-tenant DB."""

from __future__ import annotations

from juris.jobs.tracking import get_tracked, set_tracked


class _FakeDB:
    def __init__(self, initial: list[dict[str, str]] | None = None) -> None:
        self.saved: list[dict[str, str]] = list(initial or [])

    def get_tracked_list(self) -> list[dict[str, str]]:
        return self.saved

    def set_tracked_list(self, entries: list[dict[str, str]]) -> None:
        self.saved = entries


def test_get_tracked_reads_from_db_when_given() -> None:
    db = _FakeDB([{"numero_cnj": "A", "tribunal": "tjmg"}])
    assert get_tracked(db=db) == [{"numero_cnj": "A", "tribunal": "tjmg"}]


def test_set_tracked_writes_to_db_when_given() -> None:
    db = _FakeDB()
    set_tracked([{"numero_cnj": "B", "tribunal": "tjsp"}], db=db)
    assert db.saved == [{"numero_cnj": "B", "tribunal": "tjsp"}]
