"""Tests for the TokenService and SigningService boundaries (ADR-0015)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from juris.mni.token import InProcessTokenService, TokenService
from juris.signing.service import InProcessSigningService, SigningService


def _settings() -> MagicMock:
    return MagicMock(pkcs11_module="/usr/local/lib/libeTPkcs11.dylib")


class TestTokenService:
    def test_inprocess_is_a_token_service(self) -> None:
        assert isinstance(InProcessTokenService(), TokenService)

    def test_read_material_delegates_to_extract(self) -> None:
        material = MagicMock(token_label="TOKEN CERTDATA")  # noqa: S106
        with (
            patch("juris.config.get_settings", return_value=_settings()),
            patch("juris.mni.token.extract_token_material", return_value=material) as mock_extract,
        ):
            out = InProcessTokenService().read_material()

        assert out is material
        mock_extract.assert_called_once_with("/usr/local/lib/libeTPkcs11.dylib")


class TestSigningService:
    def test_inprocess_is_a_signing_service(self) -> None:
        assert isinstance(InProcessSigningService(), SigningService)

    def test_sign_pdf_drives_pades_signer(self) -> None:
        result = MagicMock()
        signer_cls = MagicMock()
        signer_cls.return_value.__enter__.return_value.sign.return_value = result

        with (
            patch("juris.config.get_settings", return_value=_settings()),
            patch(
                "juris.mni.token.extract_token_material",
                return_value=MagicMock(token_label="TOKEN CERTDATA"),  # noqa: S106
            ),
            patch("juris.signing.pades.PAdESSigner", signer_cls),
        ):
            out = InProcessSigningService().sign_pdf(
                b"%PDF-1.4 ...",
                pin="1234",  # noqa: S106
                field_name="AdvogadoSignature",
            )

        assert out is result
        # The token label is resolved and the PDF is signed through PAdESSigner.
        signer_cls.assert_called_once()
        signer_cls.return_value.__enter__.return_value.sign.assert_called_once()
