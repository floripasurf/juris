"""Vetores-zero → NULL: detecção, reparo de legados e guarda de contrato no Qdrant.

Bug original: sem embedder, `SeedLoader.ingest` e `ingest_source`/`_run_class_ingester`
gravavam um vetor zero (``[0.0, ...]``) como placeholder para "sem embedding". Mas
`LocalFTSStore.missing_embedding_count()` só enxerga ``embedding IS NULL`` — um vetor
zero real não é NULL — então esses chunks nunca eram contados como pendentes e o
backfill nunca os reparava. A busca semântica (`LocalFTSStore.search`, que filtra por
``embedding IS NOT NULL``) ficava silenciosamente morta no seed, sem nenhum sinal de
erro. Correção: o placeholder vira NULL (mesmo contrato que a escavação já usa via
``upsert([], ...)`` — `_embedding_to_blob` converte lista vazia em NULL) e ganhamos
reparo explícito para os vetores-zero já gravados por versões antigas do código.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from juris.cli.main import app
from juris.repertory.chunking import DocumentChunk
from juris.repertory.corpus.models import TipoFonte
from juris.repertory.ingestion.base import CorpusIngester
from juris.repertory.ingestion.registry import _run_class_ingester
from juris.repertory.ingestion.seed_loader import SeedLoader
from juris.repertory.vector_store import LocalFTSStore, QdrantVectorStore

runner = CliRunner()


def _chunk(chunk_id: str, source_id: str, text: str = "texto de teste") -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        source_id=source_id,
        source_type=TipoFonte.SUMULA_VINCULANTE,
        text=text,
    )


class TestZeroEmbeddingDetectionAndRepair:
    """`LocalFTSStore.count_zero_embeddings` (leitura) e `null_out_zero_embeddings` (mutador)."""

    def test_vetor_zero_legado_e_contado_mas_nao_e_missing(self) -> None:
        """Reproduz o bug: um vetor-zero gravado direto não é NULL."""
        store = LocalFTSStore()
        store.upsert([_chunk("c1", "s1")], [[0.0] * 8])

        assert store.count_zero_embeddings() == 1
        assert store.missing_embedding_count() == 0  # o bug

    def test_count_zero_embeddings_nao_muta_o_banco(self) -> None:
        store = LocalFTSStore()
        store.upsert([_chunk("c1", "s1")], [[0.0] * 8])

        store.count_zero_embeddings()

        assert store.missing_embedding_count() == 0  # ainda não reparado
        assert store.count_zero_embeddings() == 1  # idempotente, nada mudou

    def test_null_out_zero_embeddings_repara_e_atualiza_missing_count(self) -> None:
        store = LocalFTSStore()
        store.upsert([_chunk("c1", "s1")], [[0.0] * 8])

        repaired = store.null_out_zero_embeddings()

        assert repaired == 1
        assert store.missing_embedding_count() == 1
        assert store.count_zero_embeddings() == 0

    def test_embedding_real_nao_e_afetado(self) -> None:
        store = LocalFTSStore()
        store.upsert([_chunk("c1", "s1")], [[0.3, 0.1, 0.0]])

        assert store.count_zero_embeddings() == 0
        assert store.null_out_zero_embeddings() == 0
        assert store.missing_embedding_count() == 0

    def test_chunk_ja_null_nao_e_contado_como_zero(self) -> None:
        store = LocalFTSStore()
        store.upsert([_chunk("c1", "s1")], [[]])

        assert store.count_zero_embeddings() == 0
        assert store.missing_embedding_count() == 1


class TestSeedLoaderNullPlaceholder:
    """Sem embedder, o seed loader grava NULL — não um vetor zero."""

    def _corpus_dir(self, tmp_path: Any) -> Any:
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "sumulas_vinculantes.json").write_text(
            '[{"numero": "1", "texto": "Texto de teste da súmula vinculante."}]',
            encoding="utf-8",
        )
        return corpus_dir

    def test_ingest_sem_embedder_grava_null(self, tmp_path: Any) -> None:
        store = LocalFTSStore()
        loader = SeedLoader(corpus_dir=self._corpus_dir(tmp_path))

        result = loader.ingest(store)

        assert result.total_chunks >= 1
        assert store.missing_embedding_count() == result.total_chunks
        assert store.count_zero_embeddings() == 0

    def test_ingest_com_embedder_indisponivel_grava_null(self, tmp_path: Any) -> None:
        """`embed_texts` retornando None (modelo indisponível, não obrigatório) também vira NULL."""
        store = LocalFTSStore()
        loader = SeedLoader(corpus_dir=self._corpus_dir(tmp_path))
        fake_embedder = MagicMock()
        fake_embedder.embed_texts.return_value = None
        fake_embedder.dimension = 1024

        result = loader.ingest(store, embedder=fake_embedder)

        assert result.total_chunks >= 1
        assert store.missing_embedding_count() == result.total_chunks
        assert store.count_zero_embeddings() == 0


class _FakeClassIngester(CorpusIngester):
    """Ingester mínimo para exercitar `_run_class_ingester` sem tocar disco/rede."""

    def __init__(self, chunks: list[DocumentChunk]) -> None:
        self._chunks = chunks

    def fetch(self) -> list[Any]:
        return [object()]

    def parse(self, raw: Any) -> list[DocumentChunk]:
        return self._chunks


class TestRunClassIngesterNullPlaceholder:
    """Mesmo contrato NULL no braço de ingesters baseados em classe (registry.py)."""

    def test_sem_embedder_grava_null(self) -> None:
        store = LocalFTSStore()
        ingester = _FakeClassIngester([_chunk("c1", "s1")])

        result = _run_class_ingester(ingester, store, embedder=None)

        assert result.total_chunks == 1
        row = store._conn.execute("SELECT embedding FROM chunks WHERE chunk_id = 'c1'").fetchone()
        assert row[0] is None

    def test_embedder_indisponivel_grava_null(self) -> None:
        store = LocalFTSStore()
        ingester = _FakeClassIngester([_chunk("c1", "s1")])
        fake_embedder = MagicMock()
        fake_embedder.embed_texts.return_value = None
        fake_embedder.dimension = 1024

        result = _run_class_ingester(ingester, store, embedder=fake_embedder)

        assert result.total_chunks == 1
        row = store._conn.execute("SELECT embedding FROM chunks WHERE chunk_id = 'c1'").fetchone()
        assert row[0] is None


class TestQdrantZeroEmbeddingGuard:
    """`QdrantVectorStore.upsert` não tem conceito de NULL — falha explícito em vez de zero-vector silencioso."""

    @patch("juris.repertory.vector_store.QdrantVectorStore._get_client")
    def test_upsert_rejeita_embedding_vazio(self, mock_get_client: MagicMock) -> None:
        mock_get_client.return_value = MagicMock()
        store = QdrantVectorStore()

        with pytest.raises(ValueError, match="ingestão sem embedder não é suportada no Qdrant"):
            store.upsert([_chunk("c1", "s1")], [[]])

    @patch("juris.repertory.vector_store.QdrantVectorStore._get_client")
    def test_upsert_rejeita_vetor_zerado(self, mock_get_client: MagicMock) -> None:
        mock_get_client.return_value = MagicMock()
        store = QdrantVectorStore()

        with pytest.raises(ValueError, match="ingestão sem embedder não é suportada no Qdrant"):
            store.upsert([_chunk("c1", "s1")], [[0.0, 0.0, 0.0]])

    @patch("juris.repertory.vector_store.QdrantVectorStore._get_client")
    def test_upsert_aceita_embedding_real(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        store = QdrantVectorStore()

        count = store.upsert([_chunk("c1", "s1")], [[0.1, 0.0, 0.2]])

        assert count == 1
        mock_client.upsert.assert_called_once()


class TestCliIngestEmbedFlag:
    """`repertory ingest --embed` — explícito, default False, sem mágica por ENVIRONMENT."""

    def _corpus_dir(self, tmp_path: Any) -> Any:
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "sumulas_vinculantes.json").write_text(
            '[{"numero": "1", "texto": "Texto de teste da súmula vinculante."}]',
            encoding="utf-8",
        )
        return corpus_dir

    def test_ingest_sem_embed_grava_null_e_avisa(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURIS_REPERTORY_PATH", str(tmp_path / "repertory.db"))
        corpus_dir = self._corpus_dir(tmp_path)

        result = runner.invoke(app, ["repertory", "ingest", "--corpus-dir", str(corpus_dir)])

        assert result.exit_code == 0, result.output
        assert "backfill-embeddings" in result.output

        store = LocalFTSStore(tmp_path / "repertory.db")
        try:
            assert store.missing_embedding_count() >= 1
            assert store.count_zero_embeddings() == 0
        finally:
            store.close()

    def test_ingest_com_embed_instancia_embedder_explicitamente(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JURIS_REPERTORY_PATH", str(tmp_path / "repertory.db"))
        corpus_dir = self._corpus_dir(tmp_path)

        fake_embedder = MagicMock()
        fake_embedder.embed_texts.side_effect = lambda texts: [[0.1, 0.2, 0.3] for _ in texts]
        fake_embedder.dimension = 3

        with patch("juris.repertory.embeddings.LegalEmbedder", return_value=fake_embedder) as embedder_cls:
            result = runner.invoke(app, ["repertory", "ingest", "--corpus-dir", str(corpus_dir), "--embed"])

        assert result.exit_code == 0, result.output
        embedder_cls.assert_called_once_with()
        fake_embedder.embed_texts.assert_called()
        assert "backfill-embeddings" not in result.output

        store = LocalFTSStore(tmp_path / "repertory.db")
        try:
            assert store.missing_embedding_count() == 0
            assert store.count_zero_embeddings() == 0
        finally:
            store.close()


class TestCliBackfillEmbeddingsZeroRepair:
    """`repertory backfill-embeddings` — dry-run só informa; run real repara antes de contar."""

    def _seed_zero_vector_db(self, tmp_path: Any) -> Any:
        db_path = tmp_path / "repertory.db"
        store = LocalFTSStore(db_path)
        store.upsert([_chunk("c1", "s1")], [[0.0] * 8])
        store.close()
        return db_path

    def test_dry_run_reporta_vetores_zero_sem_mutar(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        db_path = self._seed_zero_vector_db(tmp_path)
        monkeypatch.setenv("JURIS_REPERTORY_PATH", str(db_path))

        result = runner.invoke(app, ["repertory", "backfill-embeddings", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "vetores-zero" in result.output.lower()

        store = LocalFTSStore(db_path)
        try:
            assert store.count_zero_embeddings() == 1  # não reparado
            assert store.missing_embedding_count() == 0  # inalterado
        finally:
            store.close()

    def test_run_real_repara_vetores_zero_antes_de_contar(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = self._seed_zero_vector_db(tmp_path)
        monkeypatch.setenv("JURIS_REPERTORY_PATH", str(db_path))

        fake_embedder = MagicMock()
        fake_embedder.embed_texts.side_effect = lambda texts: [[0.4, 0.5, 0.6] for _ in texts]

        with patch("juris.repertory.embeddings.LegalEmbedder", return_value=fake_embedder):
            result = runner.invoke(app, ["repertory", "backfill-embeddings"])

        assert result.exit_code == 0, result.output
        fake_embedder.embed_texts.assert_called()

        store = LocalFTSStore(db_path)
        try:
            assert store.count_zero_embeddings() == 0
            assert store.missing_embedding_count() == 0
        finally:
            store.close()
