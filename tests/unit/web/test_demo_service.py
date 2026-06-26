"""Tests for web demo_service helpers (operator console)."""

from __future__ import annotations

from types import SimpleNamespace

from juris.web.demo_service import estrategia_payload


def _linha(tese: str, **kw: object) -> SimpleNamespace:
    base = dict(
        tese=tese,
        ordem="principal",
        confianca="alta",
        score=0.8,
        fundamentos=["f1"],
        citacoes=["STJ-1"],
        riscos=[],
        fundamento_consequencialista="reduz o custo decisório",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_payload_none_when_no_strategy() -> None:
    assert estrategia_payload(None) is None
    assert estrategia_payload(SimpleNamespace(estrategia=None)) is None


def test_payload_surfaces_chosen_line_alternatives_and_flags() -> None:
    est = SimpleNamespace(
        escolhida=_linha("forte"),
        alternativas=[_linha("vice", ordem="subsidiaria", confianca="media", score=0.4)],
        avisos_deontologicos=["Afirma êxito garantido — vedado pelo CED."],
        revisao_humana_obrigatoria=True,
    )
    payload = estrategia_payload(SimpleNamespace(estrategia=est))

    assert payload is not None
    assert payload["escolhida"]["tese"] == "forte"
    assert payload["escolhida"]["confianca"] == "alta"
    assert payload["escolhida"]["citacoes"] == ["STJ-1"]
    assert [a["tese"] for a in payload["alternativas"]] == ["vice"]
    assert payload["avisos_deontologicos"]
    assert payload["revisao_humana_obrigatoria"] is True
