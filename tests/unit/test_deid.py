"""Tests for the de-identification capability (ADR-0016 cloud-de-identified path)."""

from __future__ import annotations

from juris.core.deid import deidentify, reidentify


def test_strips_structured_identifiers() -> None:
    text = "Autor João da Silva, CPF 123.456.789-09, processo 5082351-40.2017.8.13.0024, OAB/MG 123456."
    result = deidentify(text)

    # the direct identifiers no longer appear verbatim
    assert "123.456.789-09" not in result.text
    assert "5082351-40.2017.8.13.0024" not in result.text
    assert "123456" not in result.text
    # placeholders are present and reversible
    assert "[CPF_1]" in result.text
    assert result.mapping["[CPF_1]"] == "123.456.789-09"


def test_round_trip_restores_original() -> None:
    text = "CNPJ 12.345.678/0001-90 e CPF 987.654.321-00."
    result = deidentify(text)
    assert reidentify(result.text, result.mapping) == text


def test_stable_placeholder_for_repeated_identifier() -> None:
    text = "CPF 111.222.333-44 aparece duas vezes: 111.222.333-44."
    result = deidentify(text)
    # same original → same placeholder (only one mapping entry)
    cpf_keys = [k for k in result.mapping if k.startswith("[CPF_")]
    assert len(cpf_keys) == 1
    assert result.text.count("[CPF_1]") == 2


def test_no_identifiers_is_noop() -> None:
    text = "Pedido de indenização por danos morais."
    result = deidentify(text)
    assert result.text == text
    assert result.mapping == {}
