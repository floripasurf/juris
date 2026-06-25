"""Tests for the de-identification capability (ADR-0016 cloud-de-identified path)."""

from __future__ import annotations

import pytest

from juris.core.deid import deidentify, ensure_cloud_safe, reidentify


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


def test_structured_only_is_flagged_incomplete() -> None:
    # Names in free text are NOT handled without a NER redactor → partial de-id.
    result = deidentify("Autor João da Silva, CPF 123.456.789-09.")
    assert result.complete is False
    assert "João da Silva" in result.text  # name leaks — must not be cloud-safe


def test_ner_redactor_completes_deid() -> None:
    result = deidentify(
        "Autor João da Silva.", ner_redactor=lambda _t: ["João da Silva"]
    )
    assert result.complete is True
    assert "João da Silva" not in result.text


def test_ensure_cloud_safe_blocks_partial_deid() -> None:
    partial = deidentify("Autor João da Silva, CPF 123.456.789-09.")
    with pytest.raises(ValueError, match="parcial"):
        ensure_cloud_safe(partial)


def test_ensure_cloud_safe_allows_complete_or_explicit_override() -> None:
    complete = deidentify("Autor X.", ner_redactor=lambda _t: [])
    ensure_cloud_safe(complete)  # does not raise
    partial = deidentify("CPF 123.456.789-09.")
    ensure_cloud_safe(partial, allow_partial=True)  # explicit opt-in, no raise
