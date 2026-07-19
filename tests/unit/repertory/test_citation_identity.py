"""Identity (número + órgão) enforcement in prose citation resolution.

`resolve_narrative_citation` used to accept the top-1 fuzzy search result as
"verified" whenever its score cleared a threshold, without checking that the
result actually IS the cited source — "Súmula 297 do STJ" could resolve to a
different súmula from a different tribunal and pass. These tests lock in the
identity gate: número and órgão must both be corroborated by the candidate's
own source_id or texto before a citation counts as found.

Real source_id formats surveyed from the seed corpus (data/corpus/*.json via
the ingestion registry, `juris.repertory.ingestion.registry.REGISTRY` /
`seed_loader._entry_to_fonte` / `stj_repetitivos.py`), used below instead of
made-up shapes:
    - sumula_STF_297                       (súmula STF)
    - sumula_STJ_297                       (súmula STJ)
    - sumula_TST_1                         (súmula TST)
    - sumula_vinculante_STF_1              (súmula vinculante STF)
    - re_stf_STF_1234                      (tema de repercussão geral STF)
    - resp_repetitivo_STJ_1234567          (tema repetitivo STJ)
    - jurisprudencia_uniforme_TST_SDI1-394 (OJ TST, numero "SDI1-394")
"""

from __future__ import annotations

from typing import Any

from juris.repertory.citation_lookup import _extract_citation_ref, resolve_narrative_citation
from juris.repertory.retrieval.service import RetrievalResult


def _result(source_id: str, *, score: float = 0.9, texto: str = "texto do precedente") -> RetrievalResult:
    return RetrievalResult(
        source_id=source_id,
        score=score,
        hierarchy=4,
        hierarchy_label="Súmula",
        tribunal="STJ",
        texto=texto,
        tipo="sumula",
        uso="fundamento",
    )


class _FakeRepertory:
    def __init__(self, results: list[RetrievalResult] | None = None, *, fail: bool = False) -> None:
        self.results = results or []
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def search_jurisprudencia(self, **kwargs: Any) -> list[RetrievalResult]:
        self.calls.append(dict(kwargs))
        if self.fail:
            raise RuntimeError("repertory offline")
        return list(self.results)


# --- _extract_citation_ref -------------------------------------------------


def test_extract_ref_formatos_reais() -> None:
    assert _extract_citation_ref("sumula 297 do stj") == ("297", "stj")
    assert _extract_citation_ref("resp 1.234.567/sp do stj") == ("1234567", "stj")
    assert _extract_citation_ref("tema 1234 do stf") == ("1234", "stf")
    assert _extract_citation_ref("oj 394 da sdi-1 do tst") == ("394", "tst")
    assert _extract_citation_ref("jurisprudencia pacifica") == (None, None)


def test_extract_ref_e_insensivel_a_acento() -> None:
    # normalize_citation lowercases but never strips diacritics — the raw
    # Portuguese spelling ("súmula") must resolve the same as the ASCII form.
    assert _extract_citation_ref("súmula 297 do stj") == ("297", "stj")


def test_extract_ref_sumula_vinculante_stf() -> None:
    assert _extract_citation_ref("sumula vinculante 1 do stf") == ("1", "stf")


def test_extract_ref_repetitivo_stj() -> None:
    assert _extract_citation_ref("tema repetitivo 1234567 do stj") == ("1234567", "stj")


def test_extract_ref_numero_apos_abreviacao_normalizada() -> None:
    # normalize_citation turns "n." into "numero" before this ever runs —
    # the marker->number search must skip over that infix word.
    assert _extract_citation_ref("sumula numero 297 do stj") == ("297", "stj")


def test_extract_ref_sem_orgao_extraivel_e_none() -> None:
    assert _extract_citation_ref("sumula 297") == (None, None)


# --- resolve_narrative_citation --------------------------------------------


def test_resolve_rejeita_orgao_errado() -> None:
    """Top-1 result scores high but is a different tribunal's súmula — reject."""
    repertory = _FakeRepertory([_result("sumula_STF_297", score=0.95, texto="Súmula 297 do STF: outro tema.")])

    found, sid = resolve_narrative_citation("Súmula 297 do STJ", repertory)  # type: ignore[arg-type]

    assert (found, sid) == (False, None)


def test_resolve_aceita_match_em_source_id() -> None:
    repertory = _FakeRepertory([_result("sumula_STJ_297", score=0.9)])

    found, sid = resolve_narrative_citation("Súmula 297 do STJ", repertory)  # type: ignore[arg-type]

    assert (found, sid) == (True, "sumula_STJ_297")


def test_resolve_aceita_match_apenas_no_texto() -> None:
    # source_id carries neither the número nor o órgão — identity must come
    # from the start of texto instead (the "OU" branch of the brief).
    repertory = _FakeRepertory(
        [
            _result(
                "acordao_publicado_stj_000999",
                score=0.9,
                texto="Nos termos da Súmula 297 do STJ, é firme o entendimento...",
            )
        ]
    )

    found, sid = resolve_narrative_citation("Súmula 297 do STJ", repertory)  # type: ignore[arg-type]

    assert (found, sid) == (True, "acordao_publicado_stj_000999")


def test_resolve_normaliza_numero_com_pontos_resp() -> None:
    repertory = _FakeRepertory([_result("resp_repetitivo_STJ_1234567", score=0.9)])

    found, sid = resolve_narrative_citation("REsp 1.234.567/SP do STJ", repertory)  # type: ignore[arg-type]

    assert (found, sid) == (True, "resp_repetitivo_STJ_1234567")


def test_resolve_pula_candidato_errado_e_aceita_o_correto_dentro_do_top_k() -> None:
    """The fix scans every fetched candidate for identity, not just rank 0."""
    repertory = _FakeRepertory(
        [
            _result("sumula_STF_297", score=0.95, texto="Súmula 297 do STF."),
            _result("sumula_STJ_297", score=0.5),
        ]
    )

    found, sid = resolve_narrative_citation("Súmula 297 do STJ", repertory, threshold=0.4)  # type: ignore[arg-type]

    assert (found, sid) == (True, "sumula_STJ_297")


def test_resolve_ignora_candidato_com_identidade_certa_mas_score_abaixo_do_threshold() -> None:
    repertory = _FakeRepertory([_result("sumula_STJ_297", score=0.2)])

    found, sid = resolve_narrative_citation("Súmula 297 do STJ", repertory, threshold=0.3)  # type: ignore[arg-type]

    assert (found, sid) == (False, None)


def test_resolve_prosa_vaga_retorna_false_sem_consultar_repertorio() -> None:
    repertory = _FakeRepertory([_result("sumula_STJ_297", score=0.9)])

    found, sid = resolve_narrative_citation(  # type: ignore[arg-type]
        "É pacífica a jurisprudência sobre o tema", repertory
    )

    assert (found, sid) == (False, None)
    assert repertory.calls == []


def test_resolve_lookup_failure_com_identidade_valida_ainda_retorna_false() -> None:
    repertory = _FakeRepertory(fail=True)

    assert resolve_narrative_citation("Súmula 297 do STJ", repertory) == (False, None)  # type: ignore[arg-type]
