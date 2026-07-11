"""Tests for web demo_service helpers (operator console)."""

from __future__ import annotations

from types import SimpleNamespace

from juris.web.demo_service import estrategia_payload


def _linha(tese: str, **kw: object) -> SimpleNamespace:
    base = {
        "tese": tese,
        "ordem": "principal",
        "confianca": "alta",
        "score": 0.8,
        "fundamentos": ["f1"],
        "citacoes": ["STJ-1"],
        "riscos": [],
        "fundamento_consequencialista": "reduz o custo decisório",
    }
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
        classificacao=[SimpleNamespace(texto="contrato assinado", tipo="prova")],
        matriz_probatoria=[
            SimpleNamespace(alegacao="mora contratual", provas=["contrato"], lacunas=[]),
            SimpleNamespace(alegacao="dano material", provas=[], lacunas=["nota fiscal ausente"]),
        ],
    )
    payload = estrategia_payload(SimpleNamespace(estrategia=est))

    assert payload is not None
    assert payload["escolhida"]["tese"] == "forte"
    assert payload["escolhida"]["confianca"] == "alta"
    assert payload["escolhida"]["citacoes"] == ["STJ-1"]
    assert [a["tese"] for a in payload["alternativas"]] == ["vice"]
    assert payload["avisos_deontologicos"]
    assert payload["revisao_humana_obrigatoria"] is True
    assert payload["tom_minuta"] == "não protocolar"  # revisão obrigatória sobrepõe a confiança
    assert payload["classificacao"] == [{"texto": "contrato assinado", "tipo": "prova"}]
    assert payload["matriz_probatoria"][1]["alegacao"] == "dano material"
    assert payload["lacunas_prova"] == [{"alegacao": "dano material", "lacunas": ["nota fiscal ausente"]}]


def test_payload_marks_low_confidence_as_draft_tone() -> None:
    est = SimpleNamespace(
        escolhida=_linha("fraca", confianca="baixa"),
        alternativas=[],
        avisos_deontologicos=[],
        revisao_humana_obrigatoria=False,  # isolate the confidence→tone mapping
        classificacao=[],
        matriz_probatoria=[],
    )

    payload = estrategia_payload(SimpleNamespace(estrategia=est))

    assert payload is not None
    assert payload["tom_minuta"] == "rascunho"


def test_mandatory_review_forces_do_not_file_tone() -> None:
    est = SimpleNamespace(
        escolhida=_linha("forte", confianca="alta"),  # even high confidence
        alternativas=[],
        avisos_deontologicos=[],
        revisao_humana_obrigatoria=True,
        classificacao=[],
        matriz_probatoria=[],
    )

    payload = estrategia_payload(SimpleNamespace(estrategia=est))

    assert payload is not None
    assert payload["tom_minuta"] == "não protocolar"  # mandatory review ⇒ never auto-file


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


# --- grounding (anti-hallucination state as first-class data) ---


def _grounding(status: str, **kw: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "status": SimpleNamespace(value=status),
        "is_verified": status == "verified",
        "failed_citation_ids": [],
        "spurious_citations": [],
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_grounding_payload_none_when_no_draft() -> None:
    from juris.web.demo_service import grounding_payload

    assert grounding_payload(None) is None


def test_grounding_payload_surfaces_verified() -> None:
    from juris.web.demo_service import grounding_payload

    draft = SimpleNamespace(grounding_report=_grounding("verified"), blocked_reason=None)
    payload = grounding_payload(draft)
    assert payload == {
        "status": "verified",
        "blocked": False,
        "blocked_reason": None,
        "failed_citation_ids": [],
        "spurious_citations": [],
    }


def test_grounding_payload_surfaces_blocked_with_offending_refs() -> None:
    from juris.web.demo_service import grounding_payload

    draft = SimpleNamespace(
        grounding_report=_grounding(
            "blocked", failed_citation_ids=["inventado"], spurious_citations=["REsp 1.234.567/SP"]
        ),
        blocked_reason="citacoes_sem_marcador",
    )
    payload = grounding_payload(draft)
    assert payload is not None
    assert payload["status"] == "blocked"
    assert payload["blocked"] is True
    assert payload["blocked_reason"] == "citacoes_sem_marcador"
    assert payload["spurious_citations"] == ["REsp 1.234.567/SP"]


def test_tom_minuta_scales_with_confidence() -> None:
    def _tom(confianca):
        est = SimpleNamespace(
            escolhida=_linha("t", confianca=confianca), alternativas=[],
            avisos_deontologicos=[], revisao_humana_obrigatoria=False,
            classificacao=[], matriz_probatoria=[],
        )
        return estrategia_payload(SimpleNamespace(estrategia=est))["tom_minuta"]

    assert _tom("alta") == "forte"
    assert _tom("media") == "cauteloso"
    assert _tom("baixa") == "rascunho"
