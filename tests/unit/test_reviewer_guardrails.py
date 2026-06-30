"""Deterministic legal guardrails for the reviewer."""

from __future__ import annotations

from juris.review.models import CitationRef, ReviewRequest
from juris.review.reviewer import deterministic_legal_issues


def _titles(text: str, citations: list[CitationRef] | None = None) -> set[str]:
    request = ReviewRequest(petition_text=text, petition_type="contestacao")
    return {issue.title for issue in deterministic_legal_issues(request, citations or [])}


def test_flags_claim_without_evidence() -> None:
    titles = _titles("A parte autora alega que houve dano material relevante.")

    assert "Alegação sem prova indicada" in titles


def test_does_not_flag_claim_when_evidence_marker_is_nearby() -> None:
    titles = _titles("A parte autora alega mora contratual, conforme contrato e comprovante em anexo.")

    assert "Alegação sem prova indicada" not in titles


def test_flags_request_without_foundation() -> None:
    titles = _titles("Dos pedidos\n\nRequer a condenação do réu ao pagamento integral.")

    assert "Pedido sem fundamento explícito" in titles


def test_does_not_flag_request_with_legal_basis() -> None:
    titles = _titles("Dos pedidos\n\nRequer a condenação com base no art. 389 do CC.")

    assert "Pedido sem fundamento explícito" not in titles


def test_flags_generic_or_unverified_jurisprudence() -> None:
    titles = _titles("Conforme a jurisprudência pacífica, o pedido deve ser acolhido.")

    assert "Jurisprudência fraca ou genérica" in titles

    titles = _titles(
        "Conforme REsp 123456/SP, o pedido procede.",
        [CitationRef("REsp 123456/SP", "resp-123456-sp", False)],
    )
    assert "Jurisprudência fraca ou genérica" in titles


def test_flags_excessive_thesis_language() -> None:
    titles = _titles("A procedência certa do pedido decorre dos fatos.")

    assert "Risco de tese excessiva" in titles
