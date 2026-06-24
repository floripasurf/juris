"""Tests for the MNIReadService boundary (ADR-0015)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from juris.mni.parsers.processo import Movimento, ProcessoDomain
from juris.mni.service import InProcessMNIReadService, MNIReadService
from juris.mni.tribunais import get_tribunal

_CNJ = "5082351-40.2017.8.13.0024"


def _domain() -> ProcessoDomain:
    return ProcessoDomain(
        numero_cnj=_CNJ,
        tribunal="tjmg",
        movimentos=[Movimento(data_hora=datetime(2018, 11, 7, 0, 31), tipo="nacional", codigo_nacional=1051)],
    )


def test_inprocess_is_a_mni_read_service() -> None:
    assert isinstance(InProcessMNIReadService(), MNIReadService)


def test_inprocess_delegates_to_fetch() -> None:
    domain = _domain()
    with patch("juris.mni.fetch.fetch_processo_mni", return_value=domain) as mock_fetch:
        out = InProcessMNIReadService().consultar_processo(
            _CNJ,
            get_tribunal("tjmg"),
            "07671039632",
            "senha",
            token_pin="1234",  # noqa: S106
        )

    assert out is domain
    mock_fetch.assert_called_once()
    _, kwargs = mock_fetch.call_args
    assert kwargs["token_pin"] == "1234"  # noqa: S105
