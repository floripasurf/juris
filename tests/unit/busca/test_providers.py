"""Tests for the provider profile registry (ADR-0017 Source Mesh, first slice)."""

from __future__ import annotations

from juris.busca.models import FonteOrigem
from juris.busca.providers import PROVIDER_PROFILES, get_profile


def test_every_fonte_has_a_profile() -> None:
    # The registry must declare trust/posture for every known source.
    for fonte in FonteOrigem:
        assert fonte in PROVIDER_PROFILES


def test_esaj_is_a_reliable_high_priority_provider() -> None:
    p = get_profile(FonteOrigem.ESAJ)
    assert p.reliable is True
    assert p.base_confidence == 0.5
    assert p.merge_priority == 5
    assert p.fonte_publica is True


def test_datajud_is_low_trust_best_effort() -> None:
    p = get_profile(FonteOrigem.DATAJUD)
    assert p.reliable is False
    assert p.base_confidence == 0.3
    assert p.merge_priority == 1
    assert p.atras_captcha is False


def test_priorities_are_distinct_so_merge_is_deterministic() -> None:
    priorities = [get_profile(f).merge_priority for f in FonteOrigem]
    assert len(set(priorities)) == len(priorities)
