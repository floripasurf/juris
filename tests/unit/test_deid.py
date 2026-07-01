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


def test_oab_dotted_and_prefixed_forms_fully_redacted() -> None:
    from juris.core.deid import deidentify

    for raw in ["OAB/SP 234.567", "OAB/SP nº 234.567", "OAB/DF 1.234"]:
        out = deidentify(raw).text
        # the ENTIRE OAB number must be gone — the old \d{1,6} leaked the ".567" tail
        assert "234.567" not in out and "234" not in out and "1.234" not in out, f"leaked: {out!r}"
        assert "[OAB_1]" in out or "[OAB_" in out


def test_email_is_redacted_and_reversible() -> None:
    text = "Contato: joao.silva@escritorio.adv.br para intimações."
    result = deidentify(text)
    assert "joao.silva@escritorio.adv.br" not in result.text
    assert "[EMAIL_1]" in result.text
    assert reidentify(result.text, result.mapping) == text


def test_brazilian_phone_numbers_redacted() -> None:
    for raw in ["(11) 91234-5678", "(48) 3222-1010", "+55 11 98765-4321"]:
        out = deidentify(f"Telefone {raw}.").text
        assert raw not in out, f"phone leaked: {out!r}"
        assert "[TELEFONE_" in out


def test_rg_redacted_without_catching_cpf() -> None:
    # RG is 2.3.3-1 digits; CPF is 3.3.3-2. They must not be confused.
    result = deidentify("RG 12.345.678-9 e CPF 123.456.789-09.")
    assert "12.345.678-9" not in result.text
    assert "[RG_1]" in result.text
    assert "[CPF_1]" in result.text  # CPF still handled by its own pattern


def test_cep_redacted() -> None:
    result = deidentify("Endereço na Rua X, CEP 88010-400.")
    assert "88010-400" not in result.text
    assert "[CEP_1]" in result.text


def test_monetary_value_redacted_and_reversible() -> None:
    text = "Valor da causa: R$ 1.234.567,89."
    result = deidentify(text)
    assert "1.234.567,89" not in result.text
    assert "[VALOR_1]" in result.text
    assert reidentify(result.text, result.mapping) == text  # reversible → draft fidelity kept


def test_full_date_redacted_and_reversible() -> None:
    text = "Nascido em 07/09/1985, intimado em 01/12/2024."
    result = deidentify(text)
    assert "07/09/1985" not in result.text
    assert "01/12/2024" not in result.text
    assert reidentify(result.text, result.mapping) == text


def test_cnj_not_misparsed_as_cep_or_date() -> None:
    # A CNJ must stay a single [CNJ_x] placeholder — the new CEP/date patterns
    # must not carve pieces out of it.
    result = deidentify("Processo 5082351-40.2017.8.13.0024.")
    assert result.text.count("[CNJ_1]") == 1
    assert "[CEP_" not in result.text
    assert "[DATA_" not in result.text
