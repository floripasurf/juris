from __future__ import annotations

from datetime import date

from juris.search.utils import clean_ementa, normalize_cnj, normalize_oab, parse_br_date


class TestNormalizeCnj:
    def test_formatted_cnj(self) -> None:
        assert normalize_cnj("0001234-56.2024.8.26.0001") == "0001234-56.2024.8.26.0001"

    def test_unformatted_cnj(self) -> None:
        assert normalize_cnj("00012345620248260001") == "0001234-56.2024.8.26.0001"

    def test_with_spaces(self) -> None:
        assert normalize_cnj(" 0001234-56.2024.8.26.0001 ") == "0001234-56.2024.8.26.0001"

    def test_invalid_returns_none(self) -> None:
        assert normalize_cnj("invalid") is None

    def test_none_input(self) -> None:
        assert normalize_cnj(None) is None


class TestParseBrDate:
    def test_dd_mm_yyyy(self) -> None:
        assert parse_br_date("15/06/2024") == date(2024, 6, 15)

    def test_yyyy_mm_dd(self) -> None:
        assert parse_br_date("2024-06-15") == date(2024, 6, 15)

    def test_dje_format(self) -> None:
        assert parse_br_date("Publicado em DJe de 15/06/2024") == date(2024, 6, 15)

    def test_invalid_returns_none(self) -> None:
        assert parse_br_date("not a date") is None

    def test_none_input(self) -> None:
        assert parse_br_date(None) is None


class TestCleanEmenta:
    def test_strip_html_tags(self) -> None:
        assert clean_ementa("<b>EMENTA</b>: Texto") == "EMENTA: Texto"

    def test_collapse_whitespace(self) -> None:
        assert clean_ementa("Texto   com    espaços") == "Texto com espaços"

    def test_strip_boilerplate(self) -> None:
        text = "TRIBUNAL REGIONAL FEDERAL DA 3ª REGIÃO\nEMENTA: Real content"
        result = clean_ementa(text)
        assert "Real content" in result


class TestNormalizeOab:
    def test_with_state_prefix(self) -> None:
        assert normalize_oab("SP123456") == ("SP", "123456")

    def test_with_slash(self) -> None:
        assert normalize_oab("123456/SP") == ("SP", "123456")

    def test_no_state(self) -> None:
        assert normalize_oab("123456") == (None, "123456")
