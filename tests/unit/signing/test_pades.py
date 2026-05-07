"""Unit tests for PAdES signing module — mock PKCS#11 (no hardware needed)."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from juris.signing.pades import (
    CertExpiredError,
    CertStatus,
    PAdESSigner,
    PINError,
    SigningResult,
    _extract_cn,
    _extract_cpf,
    _sha256_hex,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Minimal valid PDF (enough for tests; signing is mocked)
MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n"
    b"0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"
)

SIGNED_PDF = MINIMAL_PDF + b"\n%%SIGNED%%"


def _make_mock_cert(
    cn: str = "JOAO DA SILVA:12345678901",
    not_after: datetime | None = None,
) -> MagicMock:
    """Build a mock x509 certificate."""
    from cryptography import x509 as x509_mod

    cert = MagicMock()

    # CN attribute
    cn_attr = MagicMock()
    cn_attr.value = cn
    cert.subject.get_attributes_for_oid.return_value = [cn_attr]

    # Expiry
    if not_after is None:
        not_after = datetime(2027, 12, 31, tzinfo=UTC)
    cert.not_valid_after_utc = not_after

    # SAN — raise ExtensionNotFound so CPF falls back to CN parsing
    cert.extensions.get_extension_for_class.side_effect = x509_mod.ExtensionNotFound(
        "no SAN", x509_mod.SubjectAlternativeName([])
    )

    # PEM export for pyhanko
    cert.public_bytes.return_value = b"-----BEGIN CERTIFICATE-----\nMOCK\n-----END CERTIFICATE-----\n"

    return cert


def _make_mock_session(cert: MagicMock | None = None) -> MagicMock:
    """Build a mock PKCS#11 session with one certificate object."""
    session = MagicMock()

    if cert is None:
        cert = _make_mock_cert()


    cert_obj = MagicMock()
    # DER bytes not used directly in tests since we mock x509 loading
    cert_obj.__getitem__ = MagicMock(return_value=b"DER_BYTES")

    session.get_objects.return_value = [cert_obj]
    return session, cert


def _patch_pkcs11_lib(
    session: MagicMock,
    cert: MagicMock,
) -> MagicMock:
    """Create a mock pkcs11.lib that yields our session and cert."""
    mock_lib = MagicMock()
    mock_token = MagicMock()
    mock_token.open.return_value = session
    mock_token.label = "MyToken"
    mock_slot = MagicMock()
    mock_slot.get_token.return_value = mock_token
    mock_lib.get_slots.return_value = [mock_slot]
    mock_lib.get_token.return_value = mock_token
    return mock_lib


# ---------------------------------------------------------------------------
# Context manager tests
# ---------------------------------------------------------------------------


@patch("juris.signing.pades.x509.load_der_x509_certificate")
@patch("juris.signing.pades.pkcs11.lib")
def test_context_manager_opens_and_closes_session(
    mock_pkcs11_lib_cls: MagicMock,
    mock_load_cert: MagicMock,
) -> None:
    """Session is opened on __enter__ and closed on __exit__."""
    session, cert = _make_mock_session()
    mock_load_cert.return_value = cert
    mock_pkcs11_lib_cls.return_value = _patch_pkcs11_lib(session, cert)

    with PAdESSigner("/lib/pkcs11.so", "MyToken", "1234") as signer:
        assert signer._session is not None

    # After exit, session.close() was called
    session.close.assert_called_once()


@patch("juris.signing.pades.x509.load_der_x509_certificate")
@patch("juris.signing.pades.pkcs11.lib")
def test_session_closed_even_on_exception(
    mock_pkcs11_lib_cls: MagicMock,
    mock_load_cert: MagicMock,
) -> None:
    """Session is released even when code inside the context manager raises."""
    session, cert = _make_mock_session()
    mock_load_cert.return_value = cert
    mock_pkcs11_lib_cls.return_value = _patch_pkcs11_lib(session, cert)

    with pytest.raises(ValueError, match="boom"), PAdESSigner("/lib/pkcs11.so", "MyToken", "1234"):
        raise ValueError("boom")

    session.close.assert_called_once()


# ---------------------------------------------------------------------------
# sign() tests
# ---------------------------------------------------------------------------


@patch("juris.signing.pades.signers.PdfSigner")
@patch("juris.signing.pades.load_cert_from_pemder")
@patch("juris.signing.pades.signers.SimpleSigner")
@patch("juris.signing.pades.x509.load_der_x509_certificate")
@patch("juris.signing.pades.pkcs11.lib")
def test_sign_produces_valid_result(
    mock_pkcs11_lib_cls: MagicMock,
    mock_load_cert: MagicMock,
    mock_simple_signer: MagicMock,
    mock_load_pem: MagicMock,
    mock_pdf_signer_cls: MagicMock,
) -> None:
    """sign() returns a SigningResult with correct fields."""
    session, cert = _make_mock_session()
    mock_load_cert.return_value = cert
    mock_pkcs11_lib_cls.return_value = _patch_pkcs11_lib(session, cert)

    # Mock PdfSigner.sign_pdf to write our fake signed PDF
    def fake_sign_pdf(input_buf: BytesIO, output: BytesIO) -> None:
        output.write(SIGNED_PDF)

    mock_pdf_signer_cls.return_value.sign_pdf.side_effect = fake_sign_pdf

    with PAdESSigner("/lib/pkcs11.so", "MyToken", "1234") as signer:
        result = signer.sign(MINIMAL_PDF)

    assert isinstance(result, SigningResult)
    assert result.signed_pdf == SIGNED_PDF
    assert result.signer_name == "JOAO DA SILVA:12345678901"
    assert result.signer_cpf == "12345678901"
    assert isinstance(result.timestamp, datetime)
    assert result.pdf_hash == _sha256_hex(MINIMAL_PDF)
    assert result.signed_pdf_hash == _sha256_hex(SIGNED_PDF)
    assert result.cert_valid_until == date(2027, 12, 31)


# ---------------------------------------------------------------------------
# validate_cert() tests
# ---------------------------------------------------------------------------


@patch("juris.signing.pades.x509.load_der_x509_certificate")
@patch("juris.signing.pades.pkcs11.lib")
def test_validate_cert_returns_status(
    mock_pkcs11_lib_cls: MagicMock,
    mock_load_cert: MagicMock,
) -> None:
    """validate_cert() returns a valid CertStatus."""
    session, cert = _make_mock_session()
    mock_load_cert.return_value = cert
    mock_pkcs11_lib_cls.return_value = _patch_pkcs11_lib(session, cert)

    with PAdESSigner("/lib/pkcs11.so", "MyToken", "1234") as signer:
        status = signer.validate_cert()

    assert isinstance(status, CertStatus)
    assert status.valid is True
    assert status.cn == "JOAO DA SILVA:12345678901"
    assert status.cpf == "12345678901"
    assert status.valid_until == date(2027, 12, 31)
    assert status.error is None


@patch("juris.signing.pades.x509.load_der_x509_certificate")
@patch("juris.signing.pades.pkcs11.lib")
def test_validate_cert_expired(
    mock_pkcs11_lib_cls: MagicMock,
    mock_load_cert: MagicMock,
) -> None:
    """validate_cert() reports expired certificate."""
    expired_date = datetime(2020, 1, 1, tzinfo=UTC)
    cert = _make_mock_cert(not_after=expired_date)
    session, _ = _make_mock_session(cert)
    mock_load_cert.return_value = cert
    mock_pkcs11_lib_cls.return_value = _patch_pkcs11_lib(session, cert)

    with PAdESSigner("/lib/pkcs11.so", "MyToken", "1234") as signer:
        status = signer.validate_cert()

    assert status.valid is False
    assert "expired" in (status.error or "").lower()


# ---------------------------------------------------------------------------
# PIN error tests
# ---------------------------------------------------------------------------


@patch("juris.signing.pades.pkcs11.lib")
def test_pin_error_surfaces_attempts(mock_pkcs11_lib_cls: MagicMock) -> None:
    """PINError is raised with pin_attempts_remaining on bad PIN."""
    import pkcs11 as pkcs11_mod

    mock_lib = MagicMock()
    mock_token = MagicMock()
    mock_token.open.side_effect = pkcs11_mod.exceptions.PinIncorrect()
    mock_token.label = "MyToken"
    mock_slot = MagicMock()
    mock_slot.get_token.return_value = mock_token
    mock_lib.get_slots.return_value = [mock_slot]
    mock_lib.get_token.return_value = mock_token
    mock_pkcs11_lib_cls.return_value = mock_lib

    with pytest.raises(PINError) as exc_info, PAdESSigner("/lib/pkcs11.so", "MyToken", "wrong"):
        pass  # pragma: no cover

    assert exc_info.value.pin_attempts_remaining is None or isinstance(
        exc_info.value.pin_attempts_remaining, int
    )


# ---------------------------------------------------------------------------
# Expired cert at sign time
# ---------------------------------------------------------------------------


@patch("juris.signing.pades.x509.load_der_x509_certificate")
@patch("juris.signing.pades.pkcs11.lib")
def test_sign_raises_on_expired_cert(
    mock_pkcs11_lib_cls: MagicMock,
    mock_load_cert: MagicMock,
) -> None:
    """sign() raises CertExpiredError when the certificate is expired."""
    expired_date = datetime(2020, 1, 1, tzinfo=UTC)
    cert = _make_mock_cert(not_after=expired_date)
    session, _ = _make_mock_session(cert)
    mock_load_cert.return_value = cert
    mock_pkcs11_lib_cls.return_value = _patch_pkcs11_lib(session, cert)

    with pytest.raises(CertExpiredError), PAdESSigner("/lib/pkcs11.so", "MyToken", "1234") as signer:
        signer.sign(MINIMAL_PDF)


# ---------------------------------------------------------------------------
# SHA-256 hash tests
# ---------------------------------------------------------------------------


def test_sha256_hex_correctness() -> None:
    """_sha256_hex returns correct SHA-256 digest."""
    data = b"hello world"
    expected = hashlib.sha256(data).hexdigest()
    assert _sha256_hex(data) == expected


def test_signing_result_hashes_differ() -> None:
    """Input and output hashes must differ (different content)."""
    result = SigningResult(
        signed_pdf=SIGNED_PDF,
        signer_name="Test",
        signer_cpf="12345678901",
        timestamp=datetime.now(UTC),
        pdf_hash=_sha256_hex(MINIMAL_PDF),
        signed_pdf_hash=_sha256_hex(SIGNED_PDF),
        cert_valid_until=date(2027, 12, 31),
    )
    assert result.pdf_hash != result.signed_pdf_hash


# ---------------------------------------------------------------------------
# CPF extraction tests
# ---------------------------------------------------------------------------


def test_extract_cpf_from_cn() -> None:
    """CPF is extracted from CN string with colon format."""
    cert = _make_mock_cert(cn="MARIA SOUZA:98765432100")
    assert _extract_cpf(cert) == "98765432100"


def test_extract_cn() -> None:
    """CN is extracted from certificate subject."""
    cert = _make_mock_cert(cn="JOAO DA SILVA:12345678901")
    assert _extract_cn(cert) == "JOAO DA SILVA:12345678901"


def test_extract_cpf_no_match() -> None:
    """Returns empty string when CN has no CPF pattern."""
    cert = _make_mock_cert(cn="NO CPF HERE")
    assert _extract_cpf(cert) == ""


# ---------------------------------------------------------------------------
# Validate cert without session
# ---------------------------------------------------------------------------


def test_validate_cert_without_session() -> None:
    """validate_cert() returns error when session is not open."""
    signer = PAdESSigner("/lib/pkcs11.so", "MyToken", "1234")
    status = signer.validate_cert()
    assert status.valid is False
    assert status.error is not None


def test_sign_without_session() -> None:
    """sign() raises RuntimeError when session is not open."""
    signer = PAdESSigner("/lib/pkcs11.so", "MyToken", "1234")
    with pytest.raises(RuntimeError, match="session not open"):
        signer.sign(MINIMAL_PDF)
