"""Tests for the escavação executor (queue → fetcher → full-text records)."""

from __future__ import annotations

import pytest

from juris.escavacao.executor import InteiroTeor, executar_escavacao
from juris.escavacao.queue import AlvoEscavacao


def _alvo(cnj: str, tema: str = "STJ-1") -> AlvoEscavacao:
    return AlvoEscavacao(numero_cnj=cnj, origem_tema=tema, prioridade=6.0, tribunal="tjmg")


class _Fetcher:
    """Fetcher stub: returns text for known CNJs, None/raises otherwise."""

    def __init__(self, texts: dict[str, str], *, raises: set[str] | None = None) -> None:
        self._texts = texts
        self._raises = raises or set()

    async def fetch(self, alvo: AlvoEscavacao) -> InteiroTeor | None:
        if alvo.numero_cnj in self._raises:
            raise RuntimeError("provider down")
        texto = self._texts.get(alvo.numero_cnj)
        if texto is None:
            return None
        return InteiroTeor(
            numero_cnj=alvo.numero_cnj, texto=texto, fonte="datajud", origem_tema=alvo.origem_tema
        )


@pytest.mark.asyncio
async def test_collects_fetched_full_text() -> None:
    fila = [_alvo("A"), _alvo("B")]
    fetcher = _Fetcher({"A": "acórdão A", "B": "acórdão B"})

    result = await executar_escavacao(fila, fetcher)

    assert {t.numero_cnj for t in result.coletados} == {"A", "B"}
    assert result.falhas == []


@pytest.mark.asyncio
async def test_unavailable_target_is_recorded_as_failure_not_crash() -> None:
    fila = [_alvo("A"), _alvo("MISSING")]
    fetcher = _Fetcher({"A": "acórdão A"})  # MISSING → None

    result = await executar_escavacao(fila, fetcher)

    assert [t.numero_cnj for t in result.coletados] == ["A"]
    assert result.falhas == ["MISSING"]


@pytest.mark.asyncio
async def test_fetcher_error_is_isolated_batch_continues() -> None:
    fila = [_alvo("BOOM"), _alvo("A")]
    fetcher = _Fetcher({"A": "acórdão A"}, raises={"BOOM"})

    result = await executar_escavacao(fila, fetcher)

    assert [t.numero_cnj for t in result.coletados] == ["A"]
    assert result.falhas == ["BOOM"]


@pytest.mark.asyncio
async def test_max_alvos_caps_the_run_and_counts_skipped() -> None:
    fila = [_alvo("A"), _alvo("B"), _alvo("C")]
    fetcher = _Fetcher({"A": "x", "B": "y", "C": "z"})

    result = await executar_escavacao(fila, fetcher, max_alvos=2)

    assert len(result.coletados) == 2
    assert result.pulados == 1


@pytest.mark.asyncio
async def test_empty_queue() -> None:
    result = await executar_escavacao([], _Fetcher({}))
    assert result.coletados == []
    assert result.falhas == []
