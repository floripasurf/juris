"""Sprint 5 done-when: a second run improves after a corpus gap is filled."""

from __future__ import annotations

from juris.benchmark.corpus_improvement import RetrievalCase, compare_runs, measure_grounding
from juris.repertory.chunking import DocumentChunk
from juris.repertory.corpus.models import TipoFonte
from juris.repertory.retrieval.hybrid import HybridRetriever
from juris.repertory.retrieval.service import RepertoryService
from juris.repertory.vector_store import LocalFTSStore


class _NullEmbedder:
    def embed_single(self, text: str) -> list[float] | None:
        return None


def test_second_run_improves_after_filling_a_gap(tmp_path) -> None:
    store = LocalFTSStore(tmp_path / "corpus.db")
    try:
        service = RepertoryService(
            HybridRetriever(dense_store=store, sparse_store=store, embedder=_NullEmbedder())
        )
        cases = [
            RetrievalCase(
                "honorarios",
                "honorários sucumbenciais fazenda pública",
                frozenset({"resp_honorarios"}),
            )
        ]

        before = measure_grounding(cases, service)
        assert before["grounding_rate"] == 0.0  # the gap: nothing to ground on

        # Second run after ingesting the missing inteiro-teor source.
        store.upsert(
            [
                DocumentChunk(
                    chunk_id="resp_honorarios",
                    source_id="resp_honorarios",
                    source_type=TipoFonte.ACORDAO_PUBLICADO,
                    text="honorários sucumbenciais contra a fazenda pública em execução",
                    metadata={},
                    position=0,
                )
            ],
            [[]],
        )

        after = measure_grounding(cases, service)
        comparison = compare_runs(before, after)
        assert comparison["improved"] is True
        assert comparison["after_grounding_rate"] == 1.0
        assert "honorarios" in comparison["newly_grounded"]
    finally:
        store.close()
