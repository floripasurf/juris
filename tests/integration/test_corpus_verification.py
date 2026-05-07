"""Integration test: diagnostic verification of corpus quality after ingestion.

Run with: uv run pytest tests/integration/test_corpus_verification.py -v -m integration
"""

from __future__ import annotations

from pathlib import Path

import pytest

from juris.repertory.ingestion.registry import count_source_entries
from juris.repertory.ingestion.seed_loader import SeedLoader
from juris.repertory.vector_store import LocalFTSStore

CORPUS_DIR = Path(__file__).resolve().parents[2] / "data" / "corpus"

# Per-source expected ranges (catches over-aggressive filtering)
SOURCE_EXPECTED_RANGES: dict[str, tuple[int, int]] = {
    "stf-sv": (50, 60),
    "stf-rg": (180, 210),
    "stj-repetitivos": (200, 220),
    "stf-sumulas": (150, 200),
    "stj-sumulas": (150, 170),
    "tst-sumulas": (55, 70),
    "tst-ojs": (45, 60),
}

# Inactive situacoes that must never appear in ingested chunks
_INACTIVE_SITUACOES = frozenset({"cancelada", "superada", "pendente_julgamento"})


@pytest.fixture(scope="module")
def ingested_store() -> LocalFTSStore:
    """Ingest all corpus data into an in-memory FTS store."""
    store = LocalFTSStore()
    loader = SeedLoader(corpus_dir=CORPUS_DIR)
    result = loader.ingest(store)
    assert result.total_chunks > 0, "Ingestion produced zero chunks"
    return store


VERIFICATION_QUERIES: list[tuple[str, int, set[str] | None]] = [
    ("prescrição quinquenal", 3, {"sumula", "resp_repetitivo"}),
    ("desconsideração personalidade jurídica", 2, None),
    ("responsabilidade objetiva Estado", 3, {"re_stf"}),
    ("FGTS correção", 1, {"sumula"}),
    ("aviso prévio proporcional", 1, {"sumula", "jurisprudencia_uniforme"}),
    ("consumidor banco", 2, {"sumula_vinculante"}),
    ("repercussão geral tese", 2, {"re_stf"}),
]


@pytest.mark.integration
class TestCorpusVerification:
    @pytest.mark.parametrize(
        "query,min_results,required_types",
        VERIFICATION_QUERIES,
        ids=[q[0] for q in VERIFICATION_QUERIES],
    )
    def test_query_meets_minimum_with_source_coverage(
        self,
        ingested_store: LocalFTSStore,
        query: str,
        min_results: int,
        required_types: set[str] | None,
    ) -> None:
        results = ingested_store.search_text(query, top_k=20)
        assert len(results) >= min_results, (
            f"Query '{query}' returned {len(results)} results, expected >= {min_results}"
        )
        if required_types:
            found_types = {r.metadata.get("tipo", "") for r in results}
            for req in required_types:
                assert any(req in t for t in found_types), (
                    f"Query '{query}': expected source type containing '{req}' "
                    f"but found only {found_types}"
                )

    def test_per_source_counts_in_range(self) -> None:
        """Each source should produce entries within expected range."""
        counts = count_source_entries(CORPUS_DIR)
        for key, (lo, hi) in SOURCE_EXPECTED_RANGES.items():
            count = counts.get(key, 0)
            assert lo <= count <= hi, (
                f"Source '{key}': {count} entries, expected [{lo}, {hi}]"
            )

    def test_no_inactive_situacoes_in_results(
        self, ingested_store: LocalFTSStore,
    ) -> None:
        """All ingested chunks must have active situacao."""
        # Broad search to pull a sample of chunks
        for word in ["direito", "prazo", "recurso", "contrato"]:
            results = ingested_store.search_text(word, top_k=50)
            for r in results:
                situacao = r.metadata.get("situacao", "")
                assert situacao not in _INACTIVE_SITUACOES, (
                    f"Chunk {r.chunk_id} has inactive situacao '{situacao}'"
                )

    def test_total_active_entries_above_threshold(self) -> None:
        """Total active entries across all sources must be >= 800."""
        counts = count_source_entries(CORPUS_DIR)
        total = sum(counts.values())
        assert total >= 800, f"Total active entries: {total}, expected >= 800"
