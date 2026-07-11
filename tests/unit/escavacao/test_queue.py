"""Tests for the directed-scraping queue (escavação — SCHEMA §4/§5)."""

from __future__ import annotations

from types import SimpleNamespace

from juris.escavacao.queue import AlvoEscavacao, construir_fila


def _esp(id_: str, hierarquia: int, cnjs: list[str]) -> SimpleNamespace:
    return SimpleNamespace(id=id_, hierarquia=hierarquia, precedentes_processos=cnjs)


_CNJ_MG = "5082351-40.2017.8.13.0024"
_CNJ_SP = "0001234-56.2024.8.26.0001"


def test_builds_deduped_queue_with_derived_tribunal() -> None:
    precs = [
        _esp("STJ-1", 1, [_CNJ_MG, _CNJ_SP]),
        _esp("TJ-1", 5, [_CNJ_MG]),  # same CNJ, lower authority
    ]
    fila = construir_fila(precs)

    cnjs = [a.numero_cnj for a in fila]
    assert len(cnjs) == len(set(cnjs))  # deduped
    alvo = next(a for a in fila if a.numero_cnj == _CNJ_MG)
    assert alvo.origem_tema == "STJ-1"  # keeps the higher-authority origin
    assert alvo.tribunal == "tjmg"  # derived from the CNJ
    assert isinstance(alvo, AlvoEscavacao)


def test_prioritises_higher_authority_first() -> None:
    precs = [_esp("baixa", 5, [_CNJ_SP]), _esp("alta", 1, [_CNJ_MG])]
    fila = construir_fila(precs)
    assert fila[0].origem_tema == "alta"


def test_respects_max_alvos() -> None:
    precs = [_esp("a", 1, [f"000000{i}-00.2024.8.26.0001" for i in range(5)])]
    fila = construir_fila(precs, max_alvos=2)
    assert len(fila) == 2


def test_empty() -> None:
    assert construir_fila([]) == []
