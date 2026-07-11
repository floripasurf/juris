"""Tests for CLI presentation helpers."""

from __future__ import annotations

from juris.cli.formatting import format_score_components


def test_none_or_empty_is_blank() -> None:
    assert format_score_components(None) == ""
    assert format_score_components({}) == ""


def test_itemises_contributing_signals_sorted_desc() -> None:
    components = {
        "relevancia": 0.28,
        "autoridade": 0.20,
        "vigencia": 0.15,
        "corroboracao": 0.07,
        "recencia": 0.0,
        "pacificacao": 0.0,
        "total": 0.70,
    }
    out = format_score_components(components)
    # highest contribution first, zero signals and the total dropped
    assert out.startswith("rel 0.28")
    assert "aut 0.20" in out
    assert "rec" not in out  # zero contribution omitted
    assert "total" not in out
    # ordering: relevância before vigência
    assert out.index("rel") < out.index("vig")


def test_caps_number_of_parts() -> None:
    components = {
        "relevancia": 0.30,
        "autoridade": 0.25,
        "vigencia": 0.15,
        "corroboracao": 0.10,
        "recencia": 0.05,
        "pacificacao": 0.03,
        "total": 0.88,
    }
    out = format_score_components(components, max_parts=2)
    assert out == "rel 0.30 · aut 0.25"
