"""Local web UI for the Juris pilot workflow."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from juris.web.app import app as app

__all__ = ["app"]


def __getattr__(name: str) -> object:
    if name == "app":
        from juris.web.app import app

        return app
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
