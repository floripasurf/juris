"""Tests for juris.repertory.ingestion.seed_loader."""

from __future__ import annotations

import json
from pathlib import Path

from juris.repertory.corpus.models import TipoFonte
from juris.repertory.ingestion.seed_loader import SeedLoader
from juris.repertory.vector_store import LocalFTSStore


def _create_seed_dir(tmp_path: Path) -> Path:
    """Create a temporary seed directory with test data."""
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()

    svs = [
        {
            "numero": "1",
            "texto": "Ofende a garantia constitucional do ato jurídico perfeito.",
            "tema": "direito adquirido",
            "base_legal": ["CF Art. 5º XXXVI"],
            "situacao": "vigente",
        },
        {
            "numero": "2",
            "texto": "É inconstitucional a lei estadual sobre consórcios.",
            "tema": "competência legislativa",
            "base_legal": ["CF Art. 22 XX"],
            "situacao": "vigente",
        },
    ]
    (corpus_dir / "sumulas_vinculantes.json").write_text(
        json.dumps(svs, ensure_ascii=False), encoding="utf-8"
    )

    stf = [
        {
            "numero": "279",
            "texto": "Para simples reexame de prova não cabe recurso extraordinário.",
            "tema": "recurso extraordinário",
            "base_legal": ["CF Art. 102 III"],
            "situacao": "vigente",
        },
    ]
    (corpus_dir / "sumulas_stf.json").write_text(
        json.dumps(stf, ensure_ascii=False), encoding="utf-8"
    )

    return corpus_dir


class TestSeedLoader:
    def test_fetch_loads_files(self, tmp_path: Path) -> None:
        corpus_dir = _create_seed_dir(tmp_path)
        loader = SeedLoader(corpus_dir=corpus_dir)
        fontes = loader.fetch()
        assert len(fontes) == 3  # 2 SVs + 1 STF sumula

    def test_fetch_creates_correct_types(self, tmp_path: Path) -> None:
        corpus_dir = _create_seed_dir(tmp_path)
        loader = SeedLoader(corpus_dir=corpus_dir)
        fontes = loader.fetch()
        sv_fontes = [f for f in fontes if f.tipo == TipoFonte.SUMULA_VINCULANTE]
        assert len(sv_fontes) == 2
        assert sv_fontes[0].hierarquia == 1

    def test_fetch_nonexistent_dir(self) -> None:
        loader = SeedLoader(corpus_dir=Path("/nonexistent/path"))
        fontes = loader.fetch()
        assert fontes == []

    def test_parse_fonte(self, tmp_path: Path) -> None:
        corpus_dir = _create_seed_dir(tmp_path)
        loader = SeedLoader(corpus_dir=corpus_dir)
        fontes = loader.fetch()
        chunks = loader.parse(fontes[0])
        assert len(chunks) >= 1
        assert chunks[0].source_id == fontes[0].id

    def test_parse_non_fonte(self) -> None:
        loader = SeedLoader()
        chunks = loader.parse("not a fonte")
        assert chunks == []

    def test_ingest_full_pipeline(self, tmp_path: Path) -> None:
        corpus_dir = _create_seed_dir(tmp_path)
        loader = SeedLoader(corpus_dir=corpus_dir)
        store = LocalFTSStore()
        result = loader.ingest(store)
        assert result.total_fetched == 3
        assert result.total_chunks >= 3
        assert result.total_embedded >= 3

    def test_ingest_searchable(self, tmp_path: Path) -> None:
        corpus_dir = _create_seed_dir(tmp_path)
        loader = SeedLoader(corpus_dir=corpus_dir)
        store = LocalFTSStore()
        loader.ingest(store)
        results = store.search_text("constitucional")
        assert len(results) >= 1

    def test_entry_to_fonte_empty_text(self) -> None:
        result = SeedLoader._entry_to_fonte(
            {"numero": "1"}, TipoFonte.SUMULA, "STF", 4,
        )
        assert result is None
