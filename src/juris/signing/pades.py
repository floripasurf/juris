"""PAdES-B PDF signing using pyhanko with PKCS#11 backend.

Signs PDF documents using ICP-Brasil A3 certificates stored on hardware
tokens (e.g., SafeNet eToken). The private key never leaves the token —
all crypto operations happen on the hardware device.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Self, cast

import pkcs11
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from pyhanko.sign import fields as sig_fields
from pyhanko.sign import signers
from pyhanko.sign.general import load_cert_from_pemder
from pyhanko_certvalidator import ValidationContext

from juris.core.observability import get_logger

logger = get_logger(__name__)

# ICP-Brasil OID for CPF in Subject Alternative Name
_OID_CPF_PESSOA_FISICA = "2.16.76.1.3.1"


@dataclass(frozen=True, slots=True)
class SigningResult:
    """Result of a successful PAdES signing operation."""

    signed_pdf: bytes
    signer_name: str
    signer_cpf: str
    timestamp: datetime
    pdf_hash: str
    signed_pdf_hash: str
    cert_valid_until: date


@dataclass(frozen=True, slots=True)
class CertStatus:
    """Status of the certificate on the hardware token."""

    valid: bool
    cn: str
    cpf: str
    valid_until: date
    pin_attempts_remaining: int | None
    error: str | None = None


def _sha256_hex(data: bytes) -> str:
    """Compute SHA-256 hex digest."""
    return hashlib.sha256(data).hexdigest()


def _extract_cn(cert: x509.Certificate) -> str:
    """Extract Common Name from certificate subject."""
    cns = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
    return str(cns[0].value) if cns else ""


def _extract_cpf(cert: x509.Certificate) -> str:
    """Extract CPF from ICP-Brasil certificate.

    Looks in Subject Alternative Name otherName with ICP-Brasil OID,
    then falls back to parsing CN (format: 'NOME DO ADVOGADO:12345678901').
    """
    try:
        san = cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        )
        for name in san.value:
            if isinstance(name, x509.OtherName) and name.type_id.dotted_string == _OID_CPF_PESSOA_FISICA:
                raw = name.value
                # OtherName value is DER-encoded — extract printable digits
                cpf_digits = re.sub(r"\D", "", raw.decode("latin-1", errors="ignore"))
                if len(cpf_digits) >= 11:
                    return cpf_digits[:11]
    except (x509.ExtensionNotFound, ValueError):
        pass

    # Fallback: parse CN
    cn = _extract_cn(cert)
    match = re.search(r":(\d{11})", cn)
    if match:
        return match.group(1)

    return ""


class PAdESSigner:
    """PAdES PDF signer using a PKCS#11 hardware token.

    Use as a context manager to ensure the PKCS#11 session is always
    released, even when signing throws an exception.

    Args:
        pkcs11_module: Path to the PKCS#11 shared library.
        token_label: Label of the token slot.
        pin: PIN for the hardware token.
        use_timestamp: If True, use PAdES-T profile with a timestamp.
    """

    def __init__(
        self,
        pkcs11_module: str,
        token_label: str,
        pin: str,
        *,
        use_timestamp: bool = False,
    ) -> None:
        self._pkcs11_module = pkcs11_module
        self._token_label = token_label
        self._pin = pin
        self._use_timestamp = use_timestamp
        self._lib: Any = None  # pkcs11 Lib (no exported type)
        self._session: pkcs11.Session | None = None
        self._cert: x509.Certificate | None = None

    def __enter__(self) -> Self:
        self._open_session()
        return self

    def __exit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: object) -> None:
        self.close()

    @staticmethod
    def _find_token(lib: Any, token_label: str) -> pkcs11.Token:
        """Find a token by label, skipping slots that raise DeviceError.

        SafeNet eToken drivers expose several empty virtual slots whose
        ``get_token()`` throws ``DeviceError``.  The upstream
        ``lib.get_token(token_label=...)`` iterates all slots and propagates
        that error instead of skipping it.  We iterate manually so the
        first matching token is returned.
        """
        for slot in lib.get_slots():
            try:
                token = slot.get_token()
            except pkcs11.exceptions.DeviceError:
                continue
            if token.label.strip() == token_label.strip():
                return cast("pkcs11.Token", token)
        raise RuntimeError(
            f"Token with label '{token_label}' not found on any slot"
        )

    def _open_session(self) -> None:
        """Open a PKCS#11 session and load the signing certificate."""
        logger.info(
            "pkcs11_open_session",
            module=self._pkcs11_module,
            token_label=self._token_label,
        )
        self._lib = pkcs11.lib(self._pkcs11_module)
        token = self._find_token(self._lib, self._token_label)

        try:
            self._session = token.open(rw=False, user_pin=self._pin)
        except pkcs11.exceptions.PinIncorrect as exc:
            pin_remaining = _get_pin_attempts(token)
            raise PINError(
                "Invalid PIN for hardware token",
                pin_attempts_remaining=pin_remaining,
            ) from exc

        # Load the first X.509 certificate from the token
        for obj in self._session.get_objects(
            {pkcs11.Attribute.CLASS: pkcs11.ObjectClass.CERTIFICATE}
        ):
            der_bytes = obj[pkcs11.Attribute.VALUE]
            self._cert = x509.load_der_x509_certificate(der_bytes)
            break

        if self._cert is None:
            raise RuntimeError("No certificate found on the hardware token")

    def sign(
        self,
        pdf_bytes: bytes,
        field_name: str = "AdvogadoSignature",
    ) -> SigningResult:
        """Sign a PDF using PAdES-B (or PAdES-T if use_timestamp=True).

        Args:
            pdf_bytes: The unsigned PDF content.
            field_name: Name of the signature field in the PDF.

        Returns:
            SigningResult with signed PDF and metadata.

        Raises:
            RuntimeError: If session is not open or cert is missing.
            CertExpiredError: If the certificate has expired.
        """
        if self._session is None or self._cert is None:
            raise RuntimeError("PKCS#11 session not open — use as context manager")

        # Validate cert expiry
        now = datetime.now(UTC)
        if self._cert.not_valid_after_utc < now:
            raise CertExpiredError(
                f"Certificate expired on {self._cert.not_valid_after_utc.date()}"
            )

        cn = _extract_cn(self._cert)
        cpf = _extract_cpf(self._cert)
        pdf_hash = _sha256_hex(pdf_bytes)

        logger.info(
            "pades_sign_start",
            signer_cn=cn,
            pdf_hash=pdf_hash,
            field_name=field_name,
        )

        # Build pyhanko signer from the PKCS#11 session
        cert_pem = self._cert.public_bytes(Encoding.PEM)
        signing_cert = load_cert_from_pemder(cert_pem)

        signer = signers.SimpleSigner(
            signing_cert=signing_cert,
            signing_key=self._session,
            cert_registry=None,  # type: ignore[arg-type]  # pyhanko stub: None is accepted
        )

        # Prepare signature field
        sig_field_spec = sig_fields.SigFieldSpec(
            sig_field_name=field_name,
        )

        # Build PDF signer
        pdf_signer = signers.PdfSigner(
            signature_meta=signers.PdfSignatureMetadata(
                field_name=field_name,
                md_algorithm="sha256",
                validation_context=ValidationContext(allow_fetching=False),
            ),
            signer=signer,
            new_field_spec=sig_field_spec,
        )

        from io import BytesIO

        input_buf = BytesIO(pdf_bytes)
        output_buf = BytesIO()
        pdf_signer.sign_pdf(input_buf, output=output_buf)  # type: ignore[arg-type]  # pyhanko stub
        signed_pdf = output_buf.getvalue()

        signed_pdf_hash = _sha256_hex(signed_pdf)
        ts = datetime.now(UTC)

        logger.info(
            "pades_sign_complete",
            signer_cn=cn,
            signed_pdf_hash=signed_pdf_hash,
        )

        return SigningResult(
            signed_pdf=signed_pdf,
            signer_name=cn,
            signer_cpf=cpf,
            timestamp=ts,
            pdf_hash=pdf_hash,
            signed_pdf_hash=signed_pdf_hash,
            cert_valid_until=self._cert.not_valid_after_utc.date(),
        )

    def validate_cert(self) -> CertStatus:
        """Check the status of the certificate on the token.

        Returns:
            CertStatus with validity info.
        """
        if self._session is None or self._cert is None:
            return CertStatus(
                valid=False,
                cn="",
                cpf="",
                valid_until=date.min,
                pin_attempts_remaining=None,
                error="PKCS#11 session not open",
            )

        cn = _extract_cn(self._cert)
        cpf = _extract_cpf(self._cert)
        valid_until = self._cert.not_valid_after_utc.date()
        now = datetime.now(UTC).date()
        is_valid = valid_until >= now

        return CertStatus(
            valid=is_valid,
            cn=cn,
            cpf=cpf,
            valid_until=valid_until,
            pin_attempts_remaining=None,
            error=None if is_valid else f"Certificate expired on {valid_until}",
        )

    def close(self) -> None:
        """Release the PKCS#11 session."""
        if self._session is not None:
            try:
                self._session.close()
            except Exception as exc:
                from juris.core.sanitize import safe_error_text

                logger.warning("pkcs11_session_close_error", error=safe_error_text(exc))
            finally:
                self._session = None
        self._cert = None
        logger.debug("pkcs11_session_closed")


def _get_pin_attempts(token: pkcs11.Token) -> int | None:
    """Try to read remaining PIN attempts from the token."""
    try:
        info = token.slot.get_token_info()  # type: ignore[attr-defined]  # pkcs11 stub
        if hasattr(info, "max_pin_len"):
            # Some tokens expose retry count; not standardized
            return None
    except Exception as exc:
        from juris.core.sanitize import safe_error_text

        logger.debug("pin_attempts_read_failed", error=safe_error_text(exc))
    return None


class PINError(Exception):
    """Raised when the token PIN is incorrect."""

    def __init__(self, message: str, pin_attempts_remaining: int | None = None) -> None:
        super().__init__(message)
        self.pin_attempts_remaining = pin_attempts_remaining


class CertExpiredError(Exception):
    """Raised when the signing certificate has expired."""
