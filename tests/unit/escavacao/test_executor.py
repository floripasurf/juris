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


def test_write_inteiro_teor_writes_one_json_per_record(tmp_path) -> None:
    from juris.escavacao.executor import write_inteiro_teor

    coletados = [
        InteiroTeor(numero_cnj="5082351-40.2017.8.13.0024", texto="acórdão A", fonte="datajud", origem_tema="STJ-1"),
        InteiroTeor(numero_cnj="0001234-56.2024.8.26.0001", texto="acórdão B", fonte="datajud", origem_tema="STJ-1"),
    ]
    paths = write_inteiro_teor(coletados, tmp_path)

    assert len(paths) == 2
    assert all(p.exists() for p in paths)
    import json

    data = json.loads(paths[0].read_text(encoding="utf-8"))
    assert data["numero_cnj"] == "5082351-40.2017.8.13.0024"
    assert data["texto"] == "acórdão A"
    assert data["fonte"] == "datajud"


def test_inteiro_teor_provenance_and_dedup() -> None:
    a = InteiroTeor(
        numero_cnj="5000000-00.2020.5.00.0000", texto="acórdão completo", fonte="tst",
        origem_tema="TST-1", parcial=False, url="https://jurisprudencia.tst.jus.br/x",
        licenca="dados públicos TST", data_coleta="2026-06-29",
    )
    import hashlib

    assert a.parcial is False
    assert a.url is not None
    assert a.content_hash == hashlib.sha256(b"ac\xc3\xb3rd\xc3\xa3o completo").hexdigest()
    cnj = "5000000-00.2020.5.00.0000"
    # same text + CNJ + source ⇒ same dedup key (idempotent re-collection)
    b = InteiroTeor(numero_cnj=cnj, texto="acórdão completo", fonte="tst", origem_tema="TST-1")
    assert a.dedup_key == b.dedup_key
    # different source ⇒ different key (corroboration kept)
    c = InteiroTeor(numero_cnj=cnj, texto="acórdão completo", fonte="datajud", origem_tema="TST-1")
    assert a.dedup_key != c.dedup_key


def test_load_inteiro_teor_round_trips_provenance(tmp_path) -> None:
    from juris.escavacao.executor import load_inteiro_teor, write_inteiro_teor

    original = [
        InteiroTeor(
            numero_cnj="5000000-00.2020.5.00.0000", texto="acórdão A", fonte="tst",
            origem_tema="TST-1", parcial=False, url="https://x", licenca="TST", data_coleta="2026-06-29",
        ),
    ]
    write_inteiro_teor(original, tmp_path)
    loaded = load_inteiro_teor(tmp_path)

    assert len(loaded) == 1
    assert loaded[0].fonte == "tst"
    assert loaded[0].parcial is False
    assert loaded[0].url == "https://x"
    assert loaded[0].dedup_key == original[0].dedup_key  # identity preserved


def test_dedup_inteiro_teor_keeps_corroborating_sources() -> None:
    from juris.escavacao.executor import dedup_inteiro_teor

    tst = InteiroTeor(numero_cnj="A", texto="mesmo acórdão", fonte="tst", origem_tema="T")
    tst_again = InteiroTeor(numero_cnj="A", texto="mesmo acórdão", fonte="tst", origem_tema="T")  # re-collected
    datajud = InteiroTeor(numero_cnj="A", texto="mesmo acórdão", fonte="datajud", origem_tema="T")

    deduped = dedup_inteiro_teor([tst, tst_again, datajud])

    assert len(deduped) == 2  # the re-collected tst is dropped; datajud (other source) kept
    assert {t.fonte for t in deduped} == {"tst", "datajud"}
