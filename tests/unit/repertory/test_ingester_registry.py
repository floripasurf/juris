"""Tests for the ingester registry."""

from __future__ import annotations

import json
from pathlib import Path

from juris.repertory.corpus.models import TipoFonte
from juris.repertory.ingestion.registry import (
    REGISTRY,
    count_source_entries,
    get_available_sources,
)


class TestRegistry:
    def test_seed_keys_present(self) -> None:
        expected_seeds = {"stf-sv", "stf-rg", "stj-repetitivos", "stf-sumulas", "stj-sumulas", "tst-sumulas", "tst-ojs"}
        assert expected_seeds.issubset(set(REGISTRY.keys()))

    def test_entries_have_correct_fields(self) -> None:
        for key, entry in REGISTRY.items():
            assert entry.key == key
            assert entry.label
            assert isinstance(entry.tipo, TipoFonte)
            assert 1 <= entry.hierarquia <= 7
            # Seed-based entries must have .json seed_file
            if not entry.source_dir and not entry.ingester_class:
                assert entry.seed_file.endswith(".json")

    def test_hierarchy_ordering(self) -> None:
        assert REGISTRY["stf-sv"].hierarquia == 1
        assert REGISTRY["stf-rg"].hierarquia == 2
        assert REGISTRY["stj-repetitivos"].hierarquia == 3
        assert REGISTRY["stf-sumulas"].hierarquia == 4
        assert REGISTRY["tst-ojs"].hierarquia == 5


class TestGetAvailableSources:
    def test_returns_sorted_by_hierarchy(self) -> None:
        sources = get_available_sources()
        hierarchies = [s.hierarquia for s in sources]
        assert hierarchies == sorted(hierarchies)

    def test_returns_all_sources(self) -> None:
        sources = get_available_sources()
        assert len(sources) >= 7


class TestCountSourceEntries:
    def test_counts_files(self, tmp_path: Path) -> None:
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        data = [
            {"numero": "1", "texto": "T1", "situacao": "vigente"},
            {"numero": "2", "texto": "T2", "situacao": "cancelada"},
        ]
        (corpus / "sumulas_vinculantes.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        counts = count_source_entries(corpus)
        assert counts["stf-sv"] == 1  # only vigente

    def test_counts_with_superseded(self, tmp_path: Path) -> None:
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        data = [
            {"numero": "1", "texto": "T1", "situacao": "vigente"},
            {"numero": "2", "texto": "T2", "situacao": "cancelada"},
        ]
        (corpus / "sumulas_vinculantes.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        counts = count_source_entries(corpus, include_superseded=True)
        assert counts["stf-sv"] == 2

    def test_missing_file_returns_zero(self, tmp_path: Path) -> None:
        corpus = tmp_path / "empty_corpus"
        corpus.mkdir()
        counts = count_source_entries(corpus)
        assert counts["stf-sv"] == 0
        assert counts["tst-ojs"] == 0
