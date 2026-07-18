"""entregar_manifestacao não é idempotente: uma falha de transporte NÃO deve ser
retentada automaticamente, sob risco de protocolo em dobro caso o tribunal já
tenha processado a petição antes do timeout."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from zeep.exceptions import Fault, TransportError

from juris.mni.operations.peticionamento import entregar_manifestacao


def _fake_client(calls: dict[str, int], *, raises: BaseException) -> MagicMock:
    def _side_effect(*_args: object, **_kwargs: object) -> SimpleNamespace:
        calls["n"] += 1
        raise raises

    client = MagicMock()
    client.service.entregarManifestacaoProcessual.side_effect = _side_effect
    return client


def test_entregar_manifestacao_nao_retenta_em_falha_de_transporte() -> None:
    """TransportError é retentável pelo mni_retry — mas entregar_manifestacao não
    pode carregar esse decorator, então uma única tentativa deve ocorrer."""
    calls = {"n": 0}
    client = _fake_client(calls, raises=TransportError("timeout"))

    with pytest.raises(TransportError):
        entregar_manifestacao(client, "123", "s", "0001", b"%PDF", "manifestacao")

    assert calls["n"] == 1


def test_entregar_manifestacao_nao_retenta_em_timeout_de_conexao() -> None:
    """TimeoutError também é retentável pelo mni_retry; mesma garantia de tentativa única."""
    calls = {"n": 0}
    client = _fake_client(calls, raises=TimeoutError("connection timed out"))

    with pytest.raises(TimeoutError):
        entregar_manifestacao(client, "123", "s", "0001", b"%PDF", "manifestacao")

    assert calls["n"] == 1


def test_entregar_manifestacao_propaga_fault_sem_retentar() -> None:
    """Faults do tribunal (ex.: erro de negócio) também não são retentados —
    comportamento preexistente que não pode regredir com a remoção do decorator."""
    calls = {"n": 0}
    fault = Fault("processo inexistente", code="Server")
    client = _fake_client(calls, raises=fault)

    with pytest.raises(Fault):
        entregar_manifestacao(client, "123", "s", "0001", b"%PDF", "manifestacao")

    assert calls["n"] == 1
