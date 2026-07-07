"""search_jurisprudencia exclui estilo; find_style_exemplar é tenant-only — L2/L4."""

from __future__ import annotations

from pathlib import Path

from juris.repertory.chunking import DocumentChunk
from juris.repertory.corpus.models import TipoFonte
from juris.repertory.retrieval.hybrid import HybridRetriever
from juris.repertory.retrieval.service import RepertoryService
from juris.repertory.vector_store import LocalFTSStore


class _NoopEmbedder:
    def embed_single(self, text: str):  # denso desligado: só o caminho FTS
        return None


def _service(tmp_path: Path) -> RepertoryService:
    store = LocalFTSStore(tmp_path / "repertory.db")
    store.upsert(
        [
            DocumentChunk(chunk_id="a1", source_id="src-acordao", source_type=TipoFonte.ACORDAO_PUBLICADO,
                          text="honorarios sucumbenciais fazenda publica equidade",
                          metadata={"hierarquia": 5, "tribunal": "tjmg"}),
            DocumentChunk(chunk_id="p1", source_id="src-peca", source_type=TipoFonte.PECA_ESCRITORIO,
                          text="honorarios sucumbenciais contestacao do escritorio",
                          metadata={"hierarquia": 7, "tipo_peticao": "contestacao"}, uso="estilo"),
        ],
        [[], []],
        tenant_id="escritorio-a",
    )
    retriever = HybridRetriever(dense_store=store, sparse_store=store, embedder=_NoopEmbedder())
    return RepertoryService(retriever=retriever)


def test_search_default_nao_traz_estilo(tmp_path: Path) -> None:
    results = _service(tmp_path).search_jurisprudencia("honorarios", tenant_id="escritorio-a")
    ids = {r.source_id for r in results}
    assert "src-acordao" in ids and "src-peca" not in ids
    hit = next(r for r in results if r.source_id == "src-acordao")
    assert hit.tipo == "acordao_publicado" and hit.uso == "fundamento"


def test_find_style_exemplar_tenant_only(tmp_path: Path) -> None:
    service = _service(tmp_path)
    exemplar = service.find_style_exemplar("contestacao", tenant_id="escritorio-a")
    assert exemplar is not None and exemplar.source_id == "src-peca"
    assert exemplar.uso == "estilo"
    # Outro tenant não vê a peça do escritório A:
    assert service.find_style_exemplar("contestacao", tenant_id="escritorio-b") is None
    # Sem tenant → nunca devolve peça privada:
    assert service.find_style_exemplar("contestacao", tenant_id=None) is None


def test_find_template_encontra_modelo_peticao_apos_fix_include_estilo(tmp_path: Path) -> None:
    """Regressão [C da T4]: find_template ficava sempre None (include_estilo nunca chegava
    à store e o filtro por tipo usava um prefixo de source_id que não corresponde a nada)."""
    store = LocalFTSStore(tmp_path / "repertory.db")
    store.upsert(
        [
            DocumentChunk(
                chunk_id="m1",
                source_id="src-modelo",
                source_type=TipoFonte.MODELO_PETICAO,
                text="modelo peticao contestacao honorarios sucumbenciais",
                metadata={"hierarquia": 7},
            ),
        ],
        [[]],
        tenant_id="escritorio-a",
    )
    retriever = HybridRetriever(dense_store=store, sparse_store=store, embedder=_NoopEmbedder())
    service = RepertoryService(retriever=retriever)

    template = service.find_template("contestacao", tenant_id="escritorio-a")

    assert template is not None
    assert template.source_id == "src-modelo"
    assert template.tipo == TipoFonte.MODELO_PETICAO.value


def test_fusao_e_boost_preservam_tipo_e_uso(tmp_path: Path) -> None:
    """Regressão [I da T4 + M da T5]: reciprocal_rank_fusion, hierarchy_boost e
    reranker.rerank reconstroem SearchResult sem repassar source_type/uso."""
    store = LocalFTSStore(tmp_path / "repertory.db")
    store.upsert(
        [
            DocumentChunk(
                chunk_id="a1",
                source_id="src-acordao",
                source_type=TipoFonte.ACORDAO_PUBLICADO,
                text="honorarios sucumbenciais fazenda publica equidade",
                metadata={"hierarquia": 5, "tribunal": "tjmg"},
            ),
        ],
        [[]],
        tenant_id="escritorio-a",
    )
    retriever = HybridRetriever(dense_store=store, sparse_store=store, embedder=_NoopEmbedder())

    results = retriever.search("honorarios", top_k=5, tenant_id="escritorio-a")

    assert results, "esperava ao menos um resultado pós fusão/boost"
    hit = next(r for r in results if r.source_id == "src-acordao")
    assert hit.source_type == "acordao_publicado"
    assert hit.uso == "fundamento"
