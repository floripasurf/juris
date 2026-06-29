"""Tests for juris.repertory.vector_store."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from juris.repertory.chunking import DocumentChunk
from juris.repertory.corpus.models import TipoFonte
from juris.repertory.vector_store import LocalFTSStore, QdrantVectorStore


def _make_chunk(
    chunk_id: str = "c1",
    source_id: str = "s1",
    text: str = "Test text",
    **kwargs,
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        source_id=source_id,
        source_type=TipoFonte.SUMULA_VINCULANTE,
        text=text,
        metadata=kwargs.get("metadata", {"tribunal": "STF", "hierarquia": 1}),
        position=kwargs.get("position", 0),
    )


class TestLocalFTSStore:
    def test_create_in_memory(self) -> None:
        store = LocalFTSStore()
        assert store is not None

    def test_upsert_and_count(self) -> None:
        store = LocalFTSStore()
        chunks = [_make_chunk("c1", "s1", "Direito constitucional"), _make_chunk("c2", "s1", "Processo civil")]
        embeddings = [[0.0] * 10, [0.0] * 10]
        count = store.upsert(chunks, embeddings)
        assert count == 2

    def test_search_text(self) -> None:
        store = LocalFTSStore()
        chunks = [
            _make_chunk("c1", "s1", "Súmula vinculante sobre direito constitucional"),
            _make_chunk("c2", "s2", "Processo civil e recurso especial"),
        ]
        store.upsert(chunks, [[0.0] * 10] * 2)
        results = store.search_text("constitucional")
        assert len(results) >= 1
        assert "constitucional" in results[0].text.lower()

    def test_search_text_empty_query(self) -> None:
        store = LocalFTSStore()
        results = store.search_text("")
        assert results == []

    def test_search_embedding_returns_empty(self) -> None:
        store = LocalFTSStore()
        results = store.search([0.0] * 10)
        assert results == []

    def test_delete(self) -> None:
        store = LocalFTSStore()
        chunks = [_make_chunk("c1", "s1", "Test text")]
        store.upsert(chunks, [[0.0] * 10])
        deleted = store.delete("s1")
        assert deleted == 1
        results = store.search_text("Test")
        assert len(results) == 0

    def test_upsert_dedup(self) -> None:
        store = LocalFTSStore()
        chunk = _make_chunk("c1", "s1", "Original text")
        store.upsert([chunk], [[0.0] * 10])
        chunk2 = _make_chunk("c1", "s1", "Updated text")
        store.upsert([chunk2], [[0.0] * 10])
        results = store.search_text("Updated")
        assert len(results) == 1

    def test_metadata_preserved(self) -> None:
        store = LocalFTSStore()
        chunk = _make_chunk("c1", "s1", "Test", metadata={"tribunal": "STJ", "hierarquia": 4})
        store.upsert([chunk], [[0.0] * 10])
        results = store.search_text("Test")
        assert results[0].metadata["tribunal"] == "STJ"


class TestQdrantVectorStore:
    @patch("juris.repertory.vector_store.QdrantVectorStore._get_client")
    def test_upsert(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        store = QdrantVectorStore()
        chunks = [_make_chunk("c1", "s1", "Test")]
        embeddings = [[0.1, 0.2, 0.3]]

        count = store.upsert(chunks, embeddings)
        assert count == 1
        mock_client.upsert.assert_called_once()

    @patch("juris.repertory.vector_store.QdrantVectorStore._get_client")
    def test_search(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_hit = MagicMock()
        mock_hit.payload = {"chunk_id": "c1", "source_id": "s1", "text": "Found"}
        mock_hit.score = 0.95
        mock_client.search.return_value = [mock_hit]
        mock_get_client.return_value = mock_client

        store = QdrantVectorStore()
        results = store.search([0.1, 0.2, 0.3], top_k=5)
        assert len(results) == 1
        assert results[0].score == 0.95
        assert results[0].text == "Found"

    @patch("juris.repertory.vector_store.QdrantVectorStore._get_client")
    def test_delete(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.delete.return_value = None
        mock_get_client.return_value = mock_client

        store = QdrantVectorStore()
        store.delete("s1")
        mock_client.delete.assert_called_once()
