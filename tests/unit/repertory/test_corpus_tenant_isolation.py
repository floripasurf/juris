"""Corpus tier isolation: a tenant's uploaded sources never leak into another's search."""

from __future__ import annotations

from juris.repertory.chunking import DocumentChunk
from juris.repertory.corpus.models import TipoFonte
from juris.repertory.retrieval.hybrid import HybridRetriever
from juris.repertory.retrieval.service import RepertoryService
from juris.repertory.vector_store import LocalFTSStore


def _chunk(cid: str, text: str) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=cid, source_id=cid, source_type=TipoFonte.ACORDAO_PUBLICADO, text=text, metadata={}, position=0
    )


class _NullEmbedder:
    """Force the FTS (sparse) path so the test exercises tenant scoping deterministically."""

    def embed_single(self, text: str) -> list[float] | None:
        return None


def test_tenant_upload_not_visible_to_other_tenant(tmp_path) -> None:
    store = LocalFTSStore(tmp_path / "corpus.db")
    try:
        store.upsert([_chunk("pub", "súmula pública sobre honorários advocatícios")], [[]], tenant_id=None)
        store.upsert([_chunk("b", "doutrina privada do escritório B sobre honorários")], [[]], tenant_id="escritorio-b")

        # tenant A searches: sees the PUBLIC seed, never escritorio-b's private upload
        hits_a = store.search_text("honorários", top_k=10, tenant_id="escritorio-a")
        ids_a = {h.source_id for h in hits_a}
        assert "pub" in ids_a
        assert "b" not in ids_a  # NO cross-tenant leak

        # tenant B sees public + its own
        ids_b = {h.source_id for h in store.search_text("honorários", top_k=10, tenant_id="escritorio-b")}
        assert {"pub", "b"} <= ids_b
    finally:
        store.close()


def test_service_search_scopes_by_tenant(tmp_path) -> None:
    """The full RepertoryService → HybridRetriever → store path honors tenant_id.

    Guards the read-side threading: a regression that dropped ``tenant_id`` in
    service.py or hybrid.py would let tenant A ground on tenant B's private upload.
    """
    store = LocalFTSStore(tmp_path / "corpus.db")
    try:
        store.upsert([_chunk("pub", "súmula pública sobre honorários advocatícios")], [[]], tenant_id=None)
        store.upsert([_chunk("b", "doutrina privada do escritório B sobre honorários")], [[]], tenant_id="escritorio-b")

        retriever = HybridRetriever(dense_store=store, sparse_store=store, embedder=_NullEmbedder())
        service = RepertoryService(retriever)

        ids_a = {r.source_id for r in service.search_jurisprudencia("honorários", tenant_id="escritorio-a")}
        assert "pub" in ids_a
        assert "b" not in ids_a  # NO cross-tenant leak through the service layer

        ids_b = {r.source_id for r in service.search_jurisprudencia("honorários", tenant_id="escritorio-b")}
        assert {"pub", "b"} <= ids_b
    finally:
        store.close()
