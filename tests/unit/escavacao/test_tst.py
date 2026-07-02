"""Tests for the TST inteiro-teor adapter (frente C — first real source).

The parser is validated against a realistic fixture; the selectors are isolated so
a real-sample smoke test can retune them. The HTTP fetch is injected, so these
tests never touch the network (and never bypass a WAF/captcha).
"""

from __future__ import annotations

import pytest

from juris.escavacao.queue import AlvoEscavacao
from juris.escavacao.tst import (
    TSTEscavacaoFetcher,
    extract_tst_backend_html,
    parse_tst_acordao,
    tst_backend_search_body,
)

# A realistic TST acórdão page (jurisprudencia.tst.jus.br renders the decision in a
# document container with an ementa block and the acórdão body).
_FIXTURE = """
<html><head><title>Consulta</title></head><body>
  <div class="navbar">menu irrelevante</div>
  <div class="documento">
    <div class="cabecalho">PROCESSO Nº TST-RR-1000-55.2020.5.09.0001</div>
    <div class="ementa">
      <p>RECURSO DE REVISTA. HORAS EXTRAS. MINUTOS RESIDUAIS. SÚMULA 366/TST.</p>
      <p>O tempo à disposição do empregador integra a jornada.</p>
    </div>
    <div class="acordao">
      <p>Vistos, relatados e discutidos estes autos de Recurso de Revista.</p>
      <p>ACORDAM os Ministros da Turma, por unanimidade, conhecer e dar provimento.</p>
    </div>
  </div>
</body></html>
"""

_BACKEND_HTML = (
    "<p>A C Ó R D Ã O</p>"
    "<p>RECURSO DE REVISTA. HORAS EXTRAS. MINUTOS RESIDUAIS. SÚMULA 366/TST.</p>"
    "<p>Vistos, relatados e discutidos estes autos de Recurso de Revista. "
    "ACORDAM os Ministros da Turma, por unanimidade, conhecer e dar provimento.</p>"
)

_BACKEND_PAYLOAD = {
    "registros": [
        {
            "registro": {
                "numero": "00020932120175090015",
                "numFormatado": "RRAg - 2093-21.2017.5.09.0015",
                "id": "doc-123",
                "inteiroTeorHtml": _BACKEND_HTML,
                "txtEmentaHighlight": "<p>ementa curta</p>",
            }
        }
    ]
}


def _alvo(cnj: str) -> AlvoEscavacao:
    return AlvoEscavacao(numero_cnj=cnj, origem_tema="TST-366", prioridade=1.0, tribunal="tst")


def test_parse_extracts_ementa_and_acordao_text() -> None:
    text = parse_tst_acordao(_FIXTURE)
    assert text is not None
    assert "HORAS EXTRAS" in text
    assert "ACORDAM os Ministros" in text
    assert "menu irrelevante" not in text  # chrome stripped
    assert "<p>" not in text  # tags stripped


def test_parse_returns_none_when_no_decision() -> None:
    assert parse_tst_acordao("<html><body><div class='navbar'>só menu</div></body></html>") is None


def test_parse_accepts_backend_full_text_without_spa_selectors() -> None:
    text = parse_tst_acordao(_BACKEND_HTML)

    assert text is not None
    assert "RECURSO DE REVISTA" in text
    assert "ACORDAM os Ministros" in text


def test_backend_payload_extracts_real_inteiro_teor_html() -> None:
    html = extract_tst_backend_html(_BACKEND_PAYLOAD, "2093-21.2017.5.09.0015")

    assert html is not None
    assert "documento" in html
    assert "ACORDAM os Ministros" in html
    assert "ementa curta" not in html  # full text field wins over ementa/highlight fallback


def test_backend_payload_rejects_non_matching_cnj() -> None:
    assert extract_tst_backend_html(_BACKEND_PAYLOAD, "9999-99.2020.5.09.0001") is None


def test_backend_search_body_keeps_tipos_filter_non_empty() -> None:
    body = tst_backend_search_body("2093-21.2017.5.09.0015")

    assert body["e"] == "2093-21.2017.5.09.0015"
    assert body["tipos"][0]["codigo"] == "ACORDAO"


@pytest.mark.asyncio
async def test_fetcher_builds_complete_inteiro_teor() -> None:
    fetcher = TSTEscavacaoFetcher(fetch_html=lambda cnj: _FIXTURE, today="2026-06-29")
    teor = await fetcher.fetch(_alvo("1000-55.2020.5.09.0001"))

    assert teor is not None
    assert teor.fonte == "tst"
    assert teor.parcial is False  # the real acórdão, not a trail
    assert "ACORDAM" in teor.texto
    assert teor.url is not None
    assert teor.licenca is not None
    assert teor.data_coleta == "2026-06-29"


@pytest.mark.asyncio
async def test_fetcher_returns_none_when_source_unavailable() -> None:
    # WAF/login/empty → graceful None so the FailoverFetcher falls back to DataJud.
    fetcher = TSTEscavacaoFetcher(fetch_html=lambda cnj: None)
    assert await fetcher.fetch(_alvo("X")) is None


@pytest.mark.asyncio
async def test_default_fetcher_is_gated_until_tos_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JURIS_TST_INTEIRO_TEOR_ENABLED", "false")

    fetcher = TSTEscavacaoFetcher(today="2026-07-01")

    assert await fetcher.fetch(_alvo("2093-21.2017.5.09.0015")) is None
