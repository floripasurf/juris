"""Common filesystem paths for local Juris state."""

from __future__ import annotations

import os
from pathlib import Path


def juris_home() -> Path:
    """Return the root for local Juris state, overrideable via ``JURIS_HOME``."""
    return Path(os.environ.get("JURIS_HOME", str(Path.home() / ".juris"))).expanduser()


def ensure_private_dir(path: Path, *, restrict_existing: bool = False) -> None:
    """Create a directory with owner-only access.

    Existing explicit parent directories may be shared locations such as /tmp;
    callers should opt into chmoding an existing directory only when it is a
    Juris-controlled storage root.
    """
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if restrict_existing or not existed:
        os.chmod(path, 0o700)


def restrict_file(path: Path) -> None:
    """Restrict an existing file to owner read/write."""
    os.chmod(path, 0o600)
