"""Eixo uso (fundamento/estilo) — spec Biblioteca do Escritório L1."""

from __future__ import annotations

import pytest

from juris.repertory.corpus.models import (
    ESTILO_SOURCE_TYPES,
    RIGHTS_BASIS_VALUES,
    TIPO_HIERARQUIA,
    TIPO_USO_DEFAULT,
    TipoFonte,
    UsoFonte,
    resolve_uso,
)


def test_mapa_de_uso_cobre_todos_os_tipos_exaustivamente() -> None:
    # Novo membro de TipoFonte sem entrada aqui deve quebrar ESTE teste.
    assert set(TIPO_USO_DEFAULT.keys()) == set(TipoFonte)


def test_tipos_de_estilo_sao_os_esperados() -> None:
    estilo = {t for t, u in TIPO_USO_DEFAULT.items() if u is UsoFonte.ESTILO}
    assert estilo == {
        TipoFonte.MODELO_PETICAO,
        TipoFonte.NOTICIA_TRIBUNAL,
        TipoFonte.PECA_ESCRITORIO,
        TipoFonte.NOTA_INTERNA,
    }
    assert ESTILO_SOURCE_TYPES == frozenset(t.value for t in estilo)  # noqa: SIM300


def test_novos_tipos_tem_hierarquia() -> None:
    assert TIPO_HIERARQUIA[TipoFonte.PECA_ESCRITORIO] == 7
    assert TIPO_HIERARQUIA[TipoFonte.NOTA_INTERNA] == 7
    assert TIPO_HIERARQUIA[TipoFonte.DOUTRINA_PRIVADA] == 6


def test_resolve_uso_deriva_do_tipo_e_respeita_override() -> None:
    assert resolve_uso(TipoFonte.PECA_ESCRITORIO) is UsoFonte.ESTILO
    assert resolve_uso("modelo_peticao") is UsoFonte.ESTILO           # aceita string
    assert resolve_uso(TipoFonte.ACORDAO_PUBLICADO) is UsoFonte.FUNDAMENTO
    assert resolve_uso(TipoFonte.ACORDAO_PUBLICADO, "estilo") is UsoFonte.ESTILO  # override
    assert resolve_uso(None) is UsoFonte.FUNDAMENTO                   # sem tipo nem uso → fundamento
    assert resolve_uso("tipo_desconhecido_qualquer") is UsoFonte.FUNDAMENTO
    with pytest.raises(ValueError):
        resolve_uso(TipoFonte.SUMULA, "citavel")                      # override inválido


def test_rights_basis_values() -> None:
    assert RIGHTS_BASIS_VALUES == frozenset(  # noqa: SIM300
        {"dominio_publico", "obra_do_escritorio", "licenca_do_escritorio", "ato_oficial"}
    )
