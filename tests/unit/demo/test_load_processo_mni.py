"""Tests for the MNI source path in demo.orchestrator.load_processo."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from juris.demo.orchestrator import SourceMode, load_processo
from juris.mni.parsers.processo import Movimento, ProcessoDomain

_CNJ = "5082351-40.2017.8.13.0024"


def _domain() -> ProcessoDomain:
    return ProcessoDomain(
        numero_cnj=_CNJ,
        tribunal="tjmg",
        movimentos=[
            Movimento(data_hora=datetime(2018, 11, 7, 0, 31), tipo="nacional", codigo_nacional=1051),
        ],
    )


def test_mni_source_returns_domain_via_fetch() -> None:
    domain = _domain()
    with patch("juris.mni.fetch.fetch_processo_mni", return_value=domain) as mock_fetch:
        out = load_processo(
            _CNJ,
            "tjmg",
            SourceMode.MNI,
            cpf="07671039632",
            senha="senha",
            token_pin="1234",  # noqa: S106
        )

    assert out is domain
    mock_fetch.assert_called_once()
    # CPF, PJe password and token PIN must be threaded to the fetch helper.
    _, kwargs = mock_fetch.call_args
    assert kwargs.get("token_pin") == "1234"


def test_mni_source_requires_cpf() -> None:
    with pytest.raises(ValueError, match="cpf"):
        load_processo(_CNJ, "tjmg", SourceMode.MNI, cpf=None)


def test_mni_source_unknown_tribunal_raises() -> None:
    with pytest.raises(KeyError):
        load_processo(_CNJ, "zzz", SourceMode.MNI, cpf="07671039632", senha="s", token_pin="1")  # noqa: S106
