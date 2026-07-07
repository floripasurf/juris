"""search_jurisprudencia exclui estilo; find_style_exemplar é tenant-only — L2/L4."""

from __future__ import annotations

from pathlib import Path

from juris.repertory.chunking import DocumentChunk
from juris.repertory.corpus.models import TipoFonte
from juris.repertory.retrieval.hybrid import HybridRetriever
from juris.repertory.retrieval.reranker import CrossEncoderReranker
from juris.repertory.retrieval.service import RepertoryService
from juris.repertory.vector_store import LocalFTSStore, SearchResult


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


class _StubCrossEncoderModel:
    """Stub do modelo interno — evita carregar sentence-transformers no teste."""

    def predict(self, pairs: list[list[str]]) -> list[float]:
        return [1.0 for _ in pairs]


def test_reranker_rerank_preserva_source_type_e_uso() -> None:
    """Regressão [M da T5] (follow-up review T6): CrossEncoderReranker.rerank é
    o terceiro ponto de reconstrução de SearchResult — caminho de produção
    (demo_service.py) — e precisa preservar source_type/uso, não só a fusão/boost."""
    reranker = CrossEncoderReranker()
    # Pula o carregamento real do modelo (_load_model faz import pesado de
    # sentence_transformers): injeta o stub diretamente nos atributos internos.
    reranker._loaded = True
    reranker._model = _StubCrossEncoderModel()

    candidates = [
        SearchResult(
            chunk_id="p1",
            source_id="src-peca",
            score=0.5,
            text="peca do escritorio sobre honorarios",
            source_type="peca_escritorio",
            uso="estilo",
        ),
    ]

    reranked = reranker.rerank("honorarios", candidates, top_k=5)

    assert len(reranked) == 1
    assert reranked[0].source_type == "peca_escritorio"
    assert reranked[0].uso == "estilo"


def test_reranker_preserva_source_type_e_uso() -> None:
    """Follow-up review T6 [M-1]: o rerank real (não mock) propaga tipo/uso.

    Caminho ativo em produção (demo_service constrói HybridRetriever com
    CrossEncoderReranker); o modelo é stubado para não carregar
    sentence-transformers.
    """
    from juris.repertory.retrieval.reranker import CrossEncoderReranker
    from juris.repertory.vector_store import SearchResult

    class _StubModel:
        def predict(self, pairs):  # noqa: ANN001, ANN201 - stub de teste
            return [0.9 for _ in pairs]

    reranker = CrossEncoderReranker()
    reranker._loaded = True
    reranker._model = _StubModel()

    candidates = [
        SearchResult(
            chunk_id="c1", source_id="src-peca", score=0.5,
            text="peça do escritório", metadata={},
            source_type="peca_escritorio", uso="estilo",
        ),
        SearchResult(
            chunk_id="c2", source_id="src-acordao", score=0.4,
            text="acórdão publicado", metadata={},
            source_type="acordao_publicado", uso="fundamento",
        ),
    ]
    reranked = reranker.rerank("consulta", candidates, top_k=5)
    by_id = {r.source_id: r for r in reranked}
    assert by_id["src-peca"].source_type == "peca_escritorio"
    assert by_id["src-peca"].uso == "estilo"
    assert by_id["src-acordao"].uso == "fundamento"
