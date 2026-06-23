"""Tests for CNJ number → court auto-detection per Resolução CNJ 65/2008."""

from __future__ import annotations

from juris.search.cnj_router import cnj_to_court


def _cnj(j: str, tr: str) -> str:
    """Build a minimal valid CNJ string for the given J and TR segments."""
    return f"0000001-00.2024.{j}.{tr}.0001"


class TestJusticaSegment:
    def test_j1_returns_stf(self) -> None:
        assert cnj_to_court(_cnj("1", "00")) == "stf"

    def test_j2_returns_none(self) -> None:
        assert cnj_to_court(_cnj("2", "00")) is None

    def test_j3_returns_stj(self) -> None:
        assert cnj_to_court(_cnj("3", "00")) == "stj"


class TestJusticaFederal:
    def test_j4_tr01_returns_trf1(self) -> None:
        assert cnj_to_court(_cnj("4", "01")) == "trf1"

    def test_j4_tr03_returns_trf3(self) -> None:
        assert cnj_to_court(_cnj("4", "03")) == "trf3"

    def test_j4_tr06_returns_trf6(self) -> None:
        assert cnj_to_court(_cnj("4", "06")) == "trf6"


class TestJusticaTrabalho:
    def test_j5_tr00_returns_tst(self) -> None:
        assert cnj_to_court(_cnj("5", "00")) == "tst"

    def test_j5_tr02_returns_trt2(self) -> None:
        assert cnj_to_court(_cnj("5", "02")) == "trt2"

    def test_j5_tr15_returns_trt15(self) -> None:
        assert cnj_to_court(_cnj("5", "15")) == "trt15"


class TestJusticaEleitoral:
    def test_j6_tr00_returns_tse(self) -> None:
        assert cnj_to_court(_cnj("6", "00")) == "tse"


class TestJusticaMilitarUniao:
    def test_j7_tr00_returns_stm(self) -> None:
        assert cnj_to_court(_cnj("7", "00")) == "stm"


class TestJusticaEstadual:
    def test_j8_tr26_returns_tjsp(self) -> None:
        assert cnj_to_court(_cnj("8", "26")) == "tjsp"

    def test_j8_tr13_returns_tjmg(self) -> None:
        assert cnj_to_court(_cnj("8", "13")) == "tjmg"

    def test_j8_tr19_returns_tjrj(self) -> None:
        assert cnj_to_court(_cnj("8", "19")) == "tjrj"

    def test_j8_tr21_returns_tjrs(self) -> None:
        assert cnj_to_court(_cnj("8", "21")) == "tjrs"

    def test_j8_tr07_returns_tjdft(self) -> None:
        assert cnj_to_court(_cnj("8", "07")) == "tjdft"

    def test_j8_tr99_unknown_returns_none(self) -> None:
        assert cnj_to_court(_cnj("8", "99")) is None


class TestInvalidInput:
    def test_invalid_cnj_returns_none(self) -> None:
        assert cnj_to_court("not-a-cnj") is None

    def test_empty_string_returns_none(self) -> None:
        assert cnj_to_court("") is None

    def test_partial_cnj_returns_none(self) -> None:
        assert cnj_to_court("0000001-00.2024.8") is None

    def test_whitespace_padded_valid_cnj(self) -> None:
        assert cnj_to_court("  " + _cnj("3", "00") + "  ") == "stj"
