"""Tests for common local-state path helpers."""

from __future__ import annotations

import stat
from pathlib import Path

from juris.core.paths import ensure_private_dir


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_ensure_private_dir_does_not_chmod_existing_explicit_parent(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o755)

    ensure_private_dir(shared)

    assert _mode(shared) == 0o755


def test_ensure_private_dir_restricts_created_dir(tmp_path: Path) -> None:
    created = tmp_path / "created"

    ensure_private_dir(created)

    assert _mode(created) == 0o700


def test_ensure_private_dir_can_restrict_existing_juris_controlled_root(tmp_path: Path) -> None:
    root = tmp_path / "juris-home"
    root.mkdir()
    root.chmod(0o755)

    ensure_private_dir(root, restrict_existing=True)

    assert _mode(root) == 0o700
