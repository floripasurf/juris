"""Tests for juris.busca.registry."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from juris.busca.abc import SearchChannel
from juris.busca.models import FonteOrigem
from juris.busca.registry import ChannelRegistry


def _make_channel(
    name: FonteOrigem, tribunais: list[str],
) -> SearchChannel:
    """Create a mock SearchChannel."""
    ch = MagicMock(spec=SearchChannel)
    ch.channel_name = name
    ch.supported_tribunais.return_value = tribunais
    return ch


class TestChannelRegistry:
    def test_get_channels(self) -> None:
        ch1 = _make_channel(FonteOrigem.ESAJ, ["tjsp", "tjms"])
        ch2 = _make_channel(FonteOrigem.DATAJUD, ["tjsp", "tjmg"])
        registry = ChannelRegistry(channels=[ch1, ch2])

        assert len(registry.get_channels("tjsp")) == 2
        assert len(registry.get_channels("tjms")) == 1
        assert len(registry.get_channels("tjmg")) == 1
        assert len(registry.get_channels("stf")) == 0

    def test_all_tribunais(self) -> None:
        ch1 = _make_channel(FonteOrigem.ESAJ, ["tjsp", "tjms"])
        ch2 = _make_channel(FonteOrigem.EPROC, ["trf4"])
        registry = ChannelRegistry(channels=[ch1, ch2])

        all_t = registry.all_tribunais()
        assert all_t == ["tjms", "tjsp", "trf4"]

    def test_tribunais_for_channel(self) -> None:
        ch1 = _make_channel(FonteOrigem.ESAJ, ["tjsp", "tjba"])
        ch2 = _make_channel(FonteOrigem.EJEF, ["tjmg"])
        registry = ChannelRegistry(channels=[ch1, ch2])

        assert registry.tribunais_for_channel(FonteOrigem.ESAJ) == ["tjba", "tjsp"]
        assert registry.tribunais_for_channel(FonteOrigem.EJEF) == ["tjmg"]
        assert registry.tribunais_for_channel(FonteOrigem.PROJUDI) == []

    def test_empty_channels(self) -> None:
        registry = ChannelRegistry(channels=[])
        assert registry.all_tribunais() == []
        assert registry.get_channels("tjsp") == []

    def test_multi_channel_tribunal(self) -> None:
        ch1 = _make_channel(FonteOrigem.ESAJ, ["tjsp"])
        ch2 = _make_channel(FonteOrigem.DATAJUD, ["tjsp"])
        ch3 = _make_channel(FonteOrigem.EPROC, ["tjsp"])
        registry = ChannelRegistry(channels=[ch1, ch2, ch3])

        channels = registry.get_channels("tjsp")
        assert len(channels) == 3

    def test_case_insensitive_lookup(self) -> None:
        ch = _make_channel(FonteOrigem.ESAJ, ["tjsp"])
        registry = ChannelRegistry(channels=[ch])

        # get_channels lowercases the input, so "TJSP" matches "tjsp"
        assert len(registry.get_channels("TJSP")) == 1
        assert len(registry.get_channels("tjsp")) == 1

    def test_duplicate_tribunal_across_channels(self) -> None:
        ch1 = _make_channel(FonteOrigem.ESAJ, ["tjsc"])
        ch2 = _make_channel(FonteOrigem.EPROC, ["tjsc"])
        registry = ChannelRegistry(channels=[ch1, ch2])

        assert len(registry.get_channels("tjsc")) == 2
        assert registry.all_tribunais() == ["tjsc"]
