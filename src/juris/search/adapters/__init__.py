"""Adapter registry with auto-discovery.

Concrete adapter modules placed inside this package are discovered
automatically when :func:`get_all_adapters` is first called. Each module
must call :func:`register_adapter` (typically via the ``@register_adapter``
decorator) to register its class.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import TYPE_CHECKING

from juris.core.sanitize import safe_error_text

if TYPE_CHECKING:
    from juris.search.adapters.base import SearchAdapter

logger = logging.getLogger(__name__)

_ADAPTER_REGISTRY: dict[str, type[SearchAdapter]] = {}

_SKIP_MODULES = frozenset({"base"})


def register_adapter(cls: type[SearchAdapter]) -> type[SearchAdapter]:
    """Register an adapter class in the global registry.

    Intended as a class decorator on concrete :class:`SearchAdapter`
    subclasses:

    .. code-block:: python

        @register_adapter
        class TjspAdapter(SearchAdapter):
            court_code = "tjsp"
            ...

    Args:
        cls: Adapter class to register; must have a ``court_code`` class var.

    Returns:
        The class unchanged (decorator pattern).
    """
    _ADAPTER_REGISTRY[cls.court_code] = cls
    return cls


def get_all_adapters() -> dict[str, type[SearchAdapter]]:
    """Return a mapping of court code → adapter class for all discovered adapters.

    Triggers :func:`_discover_adapters` on first call so that modules inside
    this package are imported and their ``@register_adapter`` decorators run.

    Returns:
        Shallow copy of the internal registry dict.
    """
    if not _ADAPTER_REGISTRY:
        _discover_adapters()
    return dict(_ADAPTER_REGISTRY)


def _discover_adapters() -> None:
    """Import every sub-module of this package so adapters self-register.

    Modules listed in ``_SKIP_MODULES`` (e.g. ``base``) are skipped.
    Import failures are logged as warnings and do not abort discovery,
    allowing adapters with missing optional dependencies to degrade
    gracefully.
    """
    package = importlib.import_module("juris.search.adapters")
    for _, name, _ in pkgutil.iter_modules(package.__path__):
        if name in _SKIP_MODULES:
            continue
        try:
            importlib.import_module(f"juris.search.adapters.{name}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to import adapter %s: %s", name, safe_error_text(exc))
