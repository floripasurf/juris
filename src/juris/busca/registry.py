"""Channel registry — maps tribunal IDs to their available SearchChannel instances."""

from __future__ import annotations

from collections import defaultdict

from juris.busca.abc import SearchChannel
from juris.busca.models import FonteOrigem
from juris.core.observability import get_logger
from juris.core.sanitize import safe_error_text

logger = get_logger(__name__)


def _auto_discover_channels() -> list[SearchChannel]:
    """Import and instantiate all known channel classes.

    Channels that fail to import (e.g., missing dependencies) are skipped
    with a warning so the registry degrades gracefully.
    """
    channels: list[SearchChannel] = []
    channel_specs: list[tuple[str, str]] = [
        ("juris.busca.channels.esaj", "EsajChannel"),
        ("juris.busca.channels.eproc", "EprocChannel"),
        ("juris.busca.channels.ejef", "EjefChannel"),
        ("juris.busca.channels.datajud", "DataJudChannel"),
        ("juris.busca.channels.projudi", "ProjudiChannel"),
    ]

    for module_path, class_name in channel_specs:
        try:
            import importlib

            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            channels.append(cls())
            logger.debug("channel_loaded", channel=class_name)
        except (ImportError, AttributeError) as exc:
            logger.warning(
                "channel_load_failed",
                module=module_path,
                cls=class_name,
                error=safe_error_text(exc),
            )

    return channels


class ChannelRegistry:
    """Registry mapping tribunal IDs to their SearchChannel instances.

    Args:
        channels: Explicit list of channels. If ``None``, auto-discovers
            and instantiates all known channel classes.
    """

    def __init__(self, channels: list[SearchChannel] | None = None) -> None:
        if channels is None:
            channels = _auto_discover_channels()

        self._channels = channels
        self._map: dict[str, list[SearchChannel]] = defaultdict(list)

        for ch in self._channels:
            for tid in ch.supported_tribunais():
                self._map[tid].append(ch)

        logger.info(
            "registry_initialized",
            channels=len(self._channels),
            tribunais=len(self._map),
        )

    def get_channels(self, tribunal_id: str) -> list[SearchChannel]:
        """Return channels capable of querying a tribunal.

        Args:
            tribunal_id: Tribunal identifier (e.g. ``'tjsp'``).

        Returns:
            List of channels, possibly empty.
        """
        return self._map.get(tribunal_id.lower().strip(), [])

    def all_tribunais(self) -> list[str]:
        """Return all known tribunal IDs across all channels."""
        return sorted(self._map.keys())

    def tribunais_for_channel(self, fonte: FonteOrigem) -> list[str]:
        """Return tribunal IDs served by a specific channel.

        Args:
            fonte: The ``FonteOrigem`` identifying the channel.

        Returns:
            Sorted list of tribunal IDs.
        """
        for ch in self._channels:
            if ch.channel_name == fonte:
                return sorted(ch.supported_tribunais())
        return []
