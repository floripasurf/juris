"""Filtro determinístico de uso nas stores FTS e Qdrant — L2 (aplicado ANTES do corte)."""

from __future__ import annotations

from pathlib import Path

import pytest

from juris.repertory.chunking import DocumentChunk
from juris.repertory.corpus.models import TipoFonte
from juris.repertory.vector_store import LocalFTSStore


def _chunk(cid: str, tipo: TipoFonte, text: str, uso: str = "") -> DocumentChunk:
    return DocumentChunk(
        chunk_id=cid, source_id=f"src-{cid}", source_type=tipo, text=text, uso=uso
    )


def _store(tmp_path: Path) -> LocalFTSStore:
    store = LocalFTSStore(tmp_path / "repertory.db")
    store.upsert(
        [
            _chunk("a1", TipoFonte.ACORDAO_PUBLICADO, "honorarios sucumbenciais fazenda publica"),
            _chunk("m1", TipoFonte.MODELO_PETICAO, "honorarios sucumbenciais modelo de contestacao"),
            _chunk("p1", TipoFonte.PECA_ESCRITORIO, "honorarios sucumbenciais peca do escritorio", uso="estilo"),
        ],
        [[], [], []],
        tenant_id="escritorio-a",
    )
    return store


def test_busca_default_exclui_estilo(tmp_path: Path) -> None:
    results = _store(tmp_path).search_text("honorarios", top_k=10, tenant_id="escritorio-a")
    ids = {r.source_id for r in results}
    assert "src-a1" in ids
    assert "src-m1" not in ids  # legado sem uso: derivado do source_type
    assert "src-p1" not in ids  # uso explícito


def test_include_estilo_devolve_tudo_com_uso_preenchido(tmp_path: Path) -> None:
    results = _store(tmp_path).search_text(
        "honorarios", top_k=10, tenant_id="escritorio-a", include_estilo=True
    )
    by_id = {r.source_id: r for r in results}
    assert set(by_id) == {"src-a1", "src-m1", "src-p1"}
    assert by_id["src-a1"].uso == "fundamento"
    assert by_id["src-m1"].uso == "estilo"       # derivado
    assert by_id["src-m1"].source_type == "modelo_peticao"


def test_tenant_only_exclui_seed_publico(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(
        [_chunk("pub1", TipoFonte.MODELO_PETICAO, "honorarios modelo publico do seed")],
        [[]],
        tenant_id=None,  # seed público
    )
    results = store.search_text(
        "honorarios", top_k=10, tenant_id="escritorio-a", include_estilo=True, tenant_only=True
    )
    ids = {r.source_id for r in results}
    assert "src-pub1" not in ids and "src-p1" in ids


def test_chunk_legado_sem_coluna_uso_migra(tmp_path: Path) -> None:
    # Simula db criado antes da coluna: cria store, dropa a coluna via recriação crua.
    import sqlite3

    db = tmp_path / "repertory.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE chunks (chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
            source_type TEXT, text TEXT NOT NULL, metadata TEXT,
            position INTEGER DEFAULT 0, tenant_id TEXT);
        CREATE VIRTUAL TABLE chunks_fts USING fts5(text);
        """
    )
    conn.execute(
        "INSERT INTO chunks VALUES ('l1','src-l1','modelo_peticao','honorarios modelo antigo','{}',0,NULL)"
    )
    conn.execute("INSERT INTO chunks_fts (rowid, text) SELECT rowid, text FROM chunks")
    conn.commit()
    conn.close()

    store = LocalFTSStore(db)  # _init_tables deve adicionar a coluna sem quebrar
    results = store.search_text("honorarios", top_k=10)
    assert all(r.source_id != "src-l1" for r in results)  # legado estilo continua excluído


def test_qdrant_filter_exclui_estilo_por_default() -> None:
    pytest.importorskip("qdrant_client")
    from juris.repertory.vector_store import QdrantVectorStore

    flt = QdrantVectorStore._search_filter("escritorio-a", include_estilo=False, tenant_only=False)
    rendered = str(flt)
    assert "uso" in rendered and "estilo" in rendered  # must_not uso=estilo presente
    flt_all = QdrantVectorStore._search_filter("escritorio-a", include_estilo=True, tenant_only=False)
    assert "estilo" not in str(flt_all)


def test_qdrant_filter_tenant_only_nao_inclui_seed_publico() -> None:
    pytest.importorskip("qdrant_client")
    from juris.repertory.vector_store import _QDRANT_PUBLIC_TENANT, QdrantVectorStore

    flt = QdrantVectorStore._search_filter("escritorio-a", include_estilo=True, tenant_only=True)
    rendered = str(flt)
    assert _QDRANT_PUBLIC_TENANT not in rendered
    assert "escritorio-a" in rendered

    flt_visible = QdrantVectorStore._search_filter("escritorio-a", include_estilo=True, tenant_only=False)
    assert _QDRANT_PUBLIC_TENANT in str(flt_visible)
