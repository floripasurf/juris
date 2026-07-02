"""Tests for juris.repertory.vector_store."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from juris.repertory.chunking import DocumentChunk
from juris.repertory.corpus.models import TipoFonte
from juris.repertory.vector_store import LocalFTSStore, QdrantVectorStore

_QDRANT_PUBLIC_TENANT = "__juris_public__"


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


def _filter_dump(value: Any) -> dict[str, Any]:
    return value.model_dump(mode="json", exclude_none=True)


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
        points = mock_client.upsert.call_args.kwargs["points"]
        assert points[0].payload["tenant_id"] == _QDRANT_PUBLIC_TENANT

    @patch("juris.repertory.vector_store.QdrantVectorStore._get_client")
    def test_upsert_tags_private_tenant(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        store = QdrantVectorStore()
        chunk = _make_chunk("c1", "s1", "Test")

        store.upsert([chunk], [[0.1, 0.2, 0.3]], tenant_id="escritorio-a")

        points = mock_client.upsert.call_args.kwargs["points"]
        assert points[0].payload["tenant_id"] == "escritorio-a"

    @patch("juris.repertory.vector_store.QdrantVectorStore._get_client")
    def test_search(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_hit = MagicMock()
        mock_hit.payload = {
            "chunk_id": "c1",
            "source_id": "s1",
            "tenant_id": _QDRANT_PUBLIC_TENANT,
            "text": "Found",
        }
        mock_hit.score = 0.95
        mock_client.query_points.return_value = SimpleNamespace(points=[mock_hit])
        mock_get_client.return_value = mock_client

        store = QdrantVectorStore()
        results = store.search([0.1, 0.2, 0.3], top_k=5)
        assert len(results) == 1
        assert results[0].score == 0.95
        assert results[0].text == "Found"
        assert "tenant_id" not in results[0].metadata

        kwargs = mock_client.query_points.call_args.kwargs
        assert kwargs["query"] == [0.1, 0.2, 0.3]
        assert kwargs["limit"] == 5
        assert _filter_dump(kwargs["query_filter"]) == {
            "must": [{"key": "tenant_id", "match": {"value": _QDRANT_PUBLIC_TENANT}}]
        }

    @patch("juris.repertory.vector_store.QdrantVectorStore._get_client")
    def test_search_tenant_filter_includes_public_and_private_only(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.query_points.return_value = SimpleNamespace(points=[])
        mock_get_client.return_value = mock_client

        store = QdrantVectorStore()
        store.search([0.1, 0.2, 0.3], top_k=5, tenant_id="escritorio-a")

        query_filter = mock_client.query_points.call_args.kwargs["query_filter"]
        assert _filter_dump(query_filter) == {
            "should": [
                {"key": "tenant_id", "match": {"value": _QDRANT_PUBLIC_TENANT}},
                {"key": "tenant_id", "match": {"value": "escritorio-a"}},
            ]
        }

    @patch("juris.repertory.vector_store.QdrantVectorStore._get_client")
    def test_delete(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.delete.return_value = None
        mock_get_client.return_value = mock_client

        store = QdrantVectorStore()
        store.delete("s1")
        mock_client.delete.assert_called_once()
        points_selector = mock_client.delete.call_args.kwargs["points_selector"]
        assert _filter_dump(points_selector) == {
            "must": [
                {"key": "source_id", "match": {"value": "s1"}},
                {"key": "tenant_id", "match": {"value": _QDRANT_PUBLIC_TENANT}},
            ]
        }

    @patch("juris.repertory.vector_store.QdrantVectorStore._get_client")
    def test_delete_private_tenant_does_not_delete_public_or_other_tenants(self, mock_get_client: MagicMock) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        store = QdrantVectorStore()
        store.delete("s1", tenant_id="escritorio-b")

        points_selector = mock_client.delete.call_args.kwargs["points_selector"]
        assert _filter_dump(points_selector) == {
            "must": [
                {"key": "source_id", "match": {"value": "s1"}},
                {"key": "tenant_id", "match": {"value": "escritorio-b"}},
            ]
        }
