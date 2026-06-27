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


def _issue(severity: str, title: str, dimension: str = "authority", **kw: object) -> SimpleNamespace:
    return SimpleNamespace(
        severity=severity,
        dimension=dimension,
        title=title,
        description=kw.get("description", "desc"),
        suggestion=kw.get("suggestion"),
        line_anchor=kw.get("line_anchor"),
        citations=list(kw.get("citations", [])),
    )


def test_review_payload_none_when_no_report() -> None:
    from juris.web.demo_service import review_payload

    assert review_payload(None) is None
    assert review_payload(SimpleNamespace(reviewer_report=None)) is None


def test_review_payload_groups_issues_and_counts() -> None:
    from juris.web.demo_service import review_payload

    rep = SimpleNamespace(
        issues=[_issue("critical", "Citação não verificada"), _issue("suggestion", "Melhorar transição")],
        citations_found=[
            SimpleNamespace(raw_text="Súmula 7", normalized="sumula-7", found_in_repertory=True)
        ],
    )
    payload = review_payload(SimpleNamespace(reviewer_report=rep))

    assert payload is not None
    assert payload["counts"]["critical"] == 1
    assert payload["counts"]["suggestion"] == 1
    assert payload["issues"][0]["title"] == "Citação não verificada"
    assert payload["issues"][0]["severity"] == "critical"
    assert payload["citations"][0]["found"] is True
