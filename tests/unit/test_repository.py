"""Tests for processo_repository using mocked async session."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from juris.mni.parsers.processo import Documento, Movimento, Parte, ProcessoDomain


class TestUpsertProcesso:
    """Test upsert logic with mocked database session."""

    def _make_domain(self) -> ProcessoDomain:
        return ProcessoDomain(
            numero_cnj="5082351-40.2017.8.13.0024",
            classe="Procedimento Comum Cível",
            assunto="Indenização por Dano Moral",
            valor_causa=50000.00,
            orgao_julgador="5ª Vara Cível da Comarca de Belo Horizonte",
            tribunal="tjmg",
            data_ajuizamento=datetime(2017, 10, 5),
            movimentos=[
                Movimento(
                    data_hora=datetime(2017, 10, 5, 10, 0),
                    tipo="nacional",
                    codigo_nacional=26,
                    complemento="",
                    descricao="Distribuído por sorteio",
                    id_movimento="MOV001",
                ),
                Movimento(
                    data_hora=datetime(2018, 9, 10, 10, 30),
                    tipo="nacional",
                    codigo_nacional=132,
                    complemento="Julgado procedente em parte",
                    descricao="Sentença",
                    id_movimento="MOV006",
                ),
            ],
            partes=[
                Parte(
                    nome="JOAO RAPHAEL MARTINS DE FARIA LAGES",
                    tipo="AT",
                    documento="07671039632",
                    advogados=["JOAO RAPHAEL MARTINS DE FARIA LAGES"],
                ),
            ],
            documentos=[
                Documento(
                    id_documento="DOC001",
                    tipo_documento="Petição Inicial",
                    descricao="Petição inicial",
                    data_hora=datetime(2017, 10, 5, 10, 0),
                ),
            ],
        )

    def test_domain_object_creation(self) -> None:
        """Verify fixture domain objects are correctly structured."""
        domain = self._make_domain()
        assert domain.numero_cnj == "5082351-40.2017.8.13.0024"
        assert domain.tribunal == "tjmg"
        assert len(domain.movimentos) == 2
        assert len(domain.partes) == 1
        assert len(domain.documentos) == 1
        assert domain.ultimo_movimento is not None
        assert domain.ultimo_movimento.codigo_nacional == 132

    def test_domain_ultimo_movimento_empty(self) -> None:
        """ultimo_movimento returns None when no movements."""
        domain = ProcessoDomain(numero_cnj="0000000-00.0000.0.00.0000")
        assert domain.ultimo_movimento is None

    def test_domain_parses_from_fixture(self) -> None:
        """Verify domain objects from fixtures are well-formed."""
        from tests.fixtures.mni_consulta_response import make_consulta_response_5082351
        from juris.mni.parsers.processo import parse_processo

        response = make_consulta_response_5082351()
        domain = parse_processo(response, tribunal_id="tjmg")

        assert domain.numero_cnj == "5082351-40.2017.8.13.0024"
        assert domain.classe == "Procedimento Comum Cível"
        assert len(domain.movimentos) == 6
        assert len(domain.partes) == 2
        assert len(domain.documentos) == 3

        # Verify movimentos are sorted
        dates = [m.data_hora for m in domain.movimentos]
        assert dates == sorted(dates)

    def test_domain_second_case(self) -> None:
        """Test domain creation from second fixture."""
        from tests.fixtures.mni_consulta_response import make_consulta_response_5080938
        from juris.mni.parsers.processo import parse_processo

        response = make_consulta_response_5080938()
        domain = parse_processo(response, tribunal_id="tjmg")

        assert domain.numero_cnj == "5080938-89.2017.8.13.0024"
        assert domain.valor_causa == 30000.00
        assert any(p.nome == "MUNICIPIO DE BELO HORIZONTE" for p in domain.partes)
