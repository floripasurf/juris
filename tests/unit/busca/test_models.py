"""Tests for juris.busca.models."""

from __future__ import annotations

import pytest

from juris.busca.models import (
    BuscaRequest,
    FonteOrigem,
    RelatoriosBusca,
    ResultadoBusca,
    ResultadoConsolidado,
)


class TestFonteOrigem:
    def test_enum_values(self) -> None:
        assert FonteOrigem.ESAJ.value == "esaj"
        assert FonteOrigem.EPROC.value == "eproc"
        assert FonteOrigem.EJEF.value == "ejef"
        assert FonteOrigem.DATAJUD.value == "datajud"
        assert FonteOrigem.PROJUDI.value == "projudi"

    def test_is_str_enum(self) -> None:
        assert isinstance(FonteOrigem.ESAJ, str)
        assert FonteOrigem.ESAJ == "esaj"


class TestBuscaRequest:
    def test_valid_nome(self) -> None:
        req = BuscaRequest(nome="FULANO")
        assert req.nome == "FULANO"
        assert req.cpf is None

    def test_valid_cpf(self) -> None:
        req = BuscaRequest(cpf="123.456.789-00")
        assert req.cpf == "123.456.789-00"

    def test_valid_oab(self) -> None:
        req = BuscaRequest(oab="SP123456")
        assert req.oab == "SP123456"

    def test_requires_at_least_one_field(self) -> None:
        with pytest.raises(ValueError, match="At least one"):
            BuscaRequest()

    def test_frozen_immutability(self) -> None:
        req = BuscaRequest(nome="FULANO")
        with pytest.raises(AttributeError):
            req.nome = "CICLANO"  # type: ignore[misc]

    def test_defaults(self) -> None:
        req = BuscaRequest(nome="X")
        assert req.tribunais is None
        assert req.max_per_tribunal == 20


class TestResultadoBusca:
    def test_creation(self) -> None:
        r = ResultadoBusca(
            numero_cnj="0000001-00.2024.8.26.0100",
            tribunal="TJSP",
            fonte=FonteOrigem.ESAJ,
            classe="Procedimento Comum",
            assunto="Direito Civil",
            orgao_julgador="1ª Vara Cível",
            data_ajuizamento="01/01/2024",
            grau="1",
            ultima_atualizacao="",
        )
        assert r.numero_cnj == "0000001-00.2024.8.26.0100"
        assert r.fonte == FonteOrigem.ESAJ
        assert r.polo_ativo == []
        assert r.polo_passivo == []

    def test_frozen(self) -> None:
        r = ResultadoBusca(
            numero_cnj="X", tribunal="T", fonte=FonteOrigem.ESAJ,
            classe="", assunto="", orgao_julgador="",
            data_ajuizamento="", grau="1", ultima_atualizacao="",
        )
        with pytest.raises(AttributeError):
            r.tribunal = "Y"  # type: ignore[misc]


class TestResultadoConsolidado:
    def test_defaults(self) -> None:
        r = ResultadoConsolidado(
            numero_cnj="X", tribunal="T", classe="", assunto="",
            orgao_julgador="", data_ajuizamento="", grau="1",
            ultima_atualizacao="",
        )
        assert r.fontes == []
        assert r.confianca == 0.0
        assert r.enriquecido is False
        assert r.dados_datajud is None
        assert r.valor_causa is None


class TestRelatoriosBusca:
    def test_creation(self) -> None:
        req = BuscaRequest(nome="TEST")
        rel = RelatoriosBusca(
            request=req,
            resultados=[],
            total_encontrado=0,
            tribunais_consultados=5,
            tribunais_com_erro=[],
            canais_usados=[FonteOrigem.ESAJ],
            duracao_segundos=1.23,
        )
        assert rel.total_encontrado == 0
        assert rel.do_cache is False
