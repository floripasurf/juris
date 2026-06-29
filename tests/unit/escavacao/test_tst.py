"""Tests for the TST inteiro-teor adapter (frente C — first real source).

The parser is validated against a realistic fixture; the selectors are isolated so
a real-sample smoke test can retune them. The HTTP fetch is injected, so these
tests never touch the network (and never bypass a WAF/captcha).
"""

from __future__ import annotations

import pytest

from juris.escavacao.queue import AlvoEscavacao
from juris.escavacao.tst import TSTEscavacaoFetcher, parse_tst_acordao

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
