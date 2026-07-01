"""Tests for the escavação→corpus ingest bridge (makes the moat searchable)."""

from __future__ import annotations

from juris.escavacao.executor import InteiroTeor, ingest_inteiro_teor
from juris.repertory.vector_store import LocalFTSStore


def _inteiro(texto: str, *, parcial: bool = False) -> InteiroTeor:
    return InteiroTeor(
        numero_cnj="1000-12.2020.5.03.0001",
        texto=texto,
        fonte="tst",
        origem_tema="tema-99",
        parcial=parcial,
        metadata={"tribunal": "TST"},
    )


def test_ingest_makes_inteiro_teor_searchable(tmp_path) -> None:
    store = LocalFTSStore(tmp_path / "corpus.db")
    try:
        it = _inteiro("Acórdão sobre horas extras e adicional noturno na jornada. " * 20)
        n = ingest_inteiro_teor([it], store)
        assert n > 0  # chunks were ingested
        results = store.search_text("horas extras", top_k=5)
        assert results, "the ingested inteiro-teor must be retrievable"
    finally:
        store.close()


def test_ingest_skips_partial_trails(tmp_path) -> None:
    # DataJud procedural trails (parcial=True) are not real acórdãos — keep them out.
    store = LocalFTSStore(tmp_path / "corpus.db")
    try:
        n = ingest_inteiro_teor([_inteiro("apenas movimentos processuais", parcial=True)], store)
        assert n == 0
    finally:
        store.close()
