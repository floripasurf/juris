"""Tests for DataJud client and parser."""

from __future__ import annotations

from datetime import datetime

from juris.datajud.parser import _format_cnj, _parse_date, parse_datajud_processo


class TestFormatCNJ:
    def test_format_20_digits(self) -> None:
        assert _format_cnj("50823514020178130024") == "5082351-40.2017.8.13.0024"

    def test_passthrough_short(self) -> None:
        assert _format_cnj("12345") == "12345"


class TestParseDate:
    def test_iso_with_millis(self) -> None:
        dt = _parse_date("2017-06-19T13:20:04.000Z")
        assert dt.year == 2017
        assert dt.month == 6
        assert dt.hour == 13

    def test_compact_format(self) -> None:
        dt = _parse_date("20170619132004")
        assert dt.year == 2017

    def test_empty(self) -> None:
        assert _parse_date("") == datetime.min


SAMPLE_SOURCE = {
    "numeroProcesso": "50823514020178130024",
    "classe": {"codigo": 7, "nome": "Procedimento Comum Cível"},
    "tribunal": "TJMG",
    "grau": "G1",
    "dataHoraUltimaAtualizacao": "2021-06-18T03:16:48.799000Z",
    "dataAjuizamento": "19000101000000",
    "assuntos": [
        {"codigo": 9587, "nome": "Compra e Venda"},
        {"codigo": 10439, "nome": "Indenização por Dano Material"},
    ],
    "movimentos": [
        {
            "codigo": 26,
            "nome": "Distribuição",
            "dataHora": "2017-06-19T13:20:04.000Z",
            "orgaoJulgador": {"codigo": "3943", "nome": "21ª Vara Cível de BH"},
            "complementosTabelados": [
                {"codigo": 2, "valor": 2, "nome": "sorteio", "descricao": "tipo_de_distribuicao"},
            ],
        },
        {
            "codigo": 466,
            "nome": "Homologação de Transação",
            "dataHora": "2018-09-17T11:23:17.000Z",
            "orgaoJulgador": {"codigo": "3943", "nome": "21ª Vara Cível de BH"},
        },
    ],
}


class TestParseDatajudProcesso:
    def test_parse_basic_fields(self) -> None:
        p = parse_datajud_processo(SAMPLE_SOURCE)
        assert p.numero_cnj == "5082351-40.2017.8.13.0024"
        assert p.classe == "Procedimento Comum Cível"
        assert p.tribunal == "tjmg"
        assert p.grau == "G1"

    def test_parse_assuntos(self) -> None:
        p = parse_datajud_processo(SAMPLE_SOURCE)
        assert "Compra e Venda" in p.assunto
        assert "Indenização" in p.assunto

    def test_parse_movimentos(self) -> None:
        p = parse_datajud_processo(SAMPLE_SOURCE)
        assert len(p.movimentos) == 2
        assert p.movimentos[0].codigo_nacional == 26
        assert p.movimentos[0].descricao == "Distribuição"
        assert p.movimentos[1].codigo_nacional == 466

    def test_parse_orgao_from_last_movement(self) -> None:
        p = parse_datajud_processo(SAMPLE_SOURCE)
        assert "21ª Vara Cível" in p.orgao_julgador

    def test_parse_complemento(self) -> None:
        p = parse_datajud_processo(SAMPLE_SOURCE)
        assert "sorteio" in p.movimentos[0].complemento

    def test_invalid_ajuizamento_ignored(self) -> None:
        p = parse_datajud_processo(SAMPLE_SOURCE)
        assert p.data_ajuizamento is None  # 19000101000000 is treated as invalid

    def test_ultimo_movimento(self) -> None:
        p = parse_datajud_processo(SAMPLE_SOURCE)
        assert p.ultimo_movimento.codigo_nacional == 466
