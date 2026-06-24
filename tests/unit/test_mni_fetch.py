"""Tests for the unified MNI fetch helper (mTLS + password paths)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from juris.mni.fetch import fetch_processo_mni
from juris.mni.parsers.processo import Movimento, ProcessoDomain
from juris.mni.tribunais import get_tribunal


def _domain() -> ProcessoDomain:
    return ProcessoDomain(
        numero_cnj="5082351-40.2017.8.13.0024",
        tribunal="tjmg",
        movimentos=[
            Movimento(data_hora=datetime(2018, 11, 7, 0, 31), tipo="nacional", codigo_nacional=1051),
        ],
    )


def _settings(token_pin: str | None = None) -> MagicMock:
    return MagicMock(
        pkcs11_module="/usr/local/lib/libeTPkcs11.dylib",
        token_pin=MagicMock(get_secret_value=lambda: token_pin) if token_pin else None,
    )


class TestFetchMtls:
    def test_mtls_tribunal_uses_token_path(self) -> None:
        domain = _domain()
        mtls_result = MagicMock(sucesso=True)
        mtls_result.to_processo_domain.return_value = domain

        with (
            patch("juris.config.get_settings", return_value=_settings()),
            patch("juris.mni.token.extract_token_material", return_value=MagicMock()),
            patch("juris.mni.token.build_pkcs11_config", return_value=MagicMock()),
            patch(
                "juris.mni.operations.consulta_pkcs11.consultar_processo_pkcs11",
                return_value=mtls_result,
            ) as mock_call,
        ):
            out = fetch_processo_mni(
                "5082351-40.2017.8.13.0024",
                get_tribunal("tjmg"),
                cpf="07671039632",
                senha="senha",
                token_pin="1234",  # noqa: S106
            )

        mock_call.assert_called_once()
        assert out is domain
        mtls_result.to_processo_domain.assert_called_once_with(
            tribunal_id="tjmg", numero_cnj="5082351-40.2017.8.13.0024"
        )

    def test_mtls_failure_raises(self) -> None:
        mtls_result = MagicMock(sucesso=False, mensagem="Processo nao encontrado")

        with (
            patch("juris.config.get_settings", return_value=_settings()),
            patch("juris.mni.token.extract_token_material", return_value=MagicMock()),
            patch("juris.mni.token.build_pkcs11_config", return_value=MagicMock()),
            patch(
                "juris.mni.operations.consulta_pkcs11.consultar_processo_pkcs11",
                return_value=mtls_result,
            ),
            pytest.raises(RuntimeError, match="Processo nao encontrado"),
        ):
            fetch_processo_mni(
                "5082351-40.2017.8.13.0024",
                get_tribunal("tjmg"),
                cpf="07671039632",
                senha="senha",
                token_pin="1234",  # noqa: S106
            )

    def test_mtls_requires_pin(self) -> None:
        # No --pin arg and no settings.token_pin -> can't unlock the token.
        with (
            patch("juris.config.get_settings", return_value=_settings(token_pin=None)),
            pytest.raises(RuntimeError, match="PIN"),
        ):
            fetch_processo_mni(
                "5082351-40.2017.8.13.0024",
                get_tribunal("tjmg"),
                cpf="07671039632",
                senha="senha",
                token_pin=None,
            )


class TestFetchPassword:
    def test_password_tribunal_uses_zeep_path(self) -> None:
        domain = _domain()
        with (
            patch("juris.mni.auth.PasswordAuth"),
            patch("juris.mni.client.get_mni_client"),
            patch(
                "juris.mni.operations.consulta.consultar_processo",
                return_value=MagicMock(sucesso=True),
            ) as mock_call,
            patch("juris.mni.parsers.processo.parse_processo", return_value=domain),
        ):
            out = fetch_processo_mni(
                "0001000-00.2024.8.08.0024",
                get_tribunal("tjes"),
                cpf="07671039632",
                senha="senha",
            )

        mock_call.assert_called_once()
        assert out is domain

    def test_password_failure_raises(self) -> None:
        with (
            patch("juris.mni.auth.PasswordAuth"),
            patch("juris.mni.client.get_mni_client"),
            patch(
                "juris.mni.operations.consulta.consultar_processo",
                return_value=MagicMock(sucesso=False, mensagem="Falha de login"),
            ),
            pytest.raises(RuntimeError, match="Falha de login"),
        ):
            fetch_processo_mni(
                "0001000-00.2024.8.08.0024",
                get_tribunal("tjes"),
                cpf="07671039632",
                senha="senha",
            )
