"""Tests for MNI response parser."""

from __future__ import annotations

from datetime import datetime

from juris.mni.parsers.processo import parse_processo

from tests.fixtures.mni_consulta_response import (
    make_consulta_response_5080938,
    make_consulta_response_5082351,
    make_consulta_response_empty,
)


class TestParseProcesso:
    def test_parse_basic_fields(self) -> None:
        response = make_consulta_response_5082351()
        processo = parse_processo(response, tribunal_id="tjmg")

        assert processo.numero_cnj == "5082351-40.2017.8.13.0024"
        assert processo.classe == "Procedimento Comum Cível"
        assert processo.assunto == "Indenização por Dano Moral"
        assert processo.valor_causa == 50000.00
        assert processo.tribunal == "tjmg"
        assert "5ª Vara Cível" in (processo.orgao_julgador or "")

    def test_parse_movimentos(self) -> None:
        response = make_consulta_response_5082351()
        processo = parse_processo(response, tribunal_id="tjmg")

        assert len(processo.movimentos) == 6
        # Should be sorted by date
        dates = [m.data_hora for m in processo.movimentos]
        assert dates == sorted(dates)
        # First is distribuição
        assert processo.movimentos[0].codigo_nacional == 26
        # Last is sentença (TPU 132)
        assert processo.movimentos[-1].codigo_nacional == 132

    def test_parse_partes(self) -> None:
        response = make_consulta_response_5082351()
        processo = parse_processo(response, tribunal_id="tjmg")

        assert len(processo.partes) == 2
        autor = next(p for p in processo.partes if p.tipo == "AT")
        assert "JOAO RAPHAEL" in autor.nome
        assert autor.documento == "07671039632"
        assert len(autor.advogados) == 1

    def test_parse_documentos(self) -> None:
        response = make_consulta_response_5082351()
        processo = parse_processo(response, tribunal_id="tjmg")

        assert len(processo.documentos) == 3
        assert processo.documentos[0].id_documento == "DOC001"

    def test_ultimo_movimento(self) -> None:
        response = make_consulta_response_5082351()
        processo = parse_processo(response, tribunal_id="tjmg")

        ultimo = processo.ultimo_movimento
        assert ultimo is not None
        assert ultimo.codigo_nacional == 132  # Sentença
        assert ultimo.data_hora == datetime(2018, 9, 10, 10, 30)

    def test_parse_second_case(self) -> None:
        response = make_consulta_response_5080938()
        processo = parse_processo(response, tribunal_id="tjmg")

        assert processo.numero_cnj == "5080938-89.2017.8.13.0024"
        assert processo.assunto == "Obrigação de Fazer"
        assert len(processo.movimentos) == 6
        # Last movement is Apelação (code 60)
        assert processo.movimentos[-1].codigo_nacional == 60

    def test_parse_partes_second_case(self) -> None:
        response = make_consulta_response_5080938()
        processo = parse_processo(response, tribunal_id="tjmg")

        reu = next(p for p in processo.partes if p.tipo == "RE")
        assert "MUNICIPIO" in reu.nome
