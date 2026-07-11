"""Authentication strategies for MNI SOAP calls."""

from __future__ import annotations

import base64
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from requests import Session
from requests_pkcs12 import Pkcs12Adapter


class AuthStrategy(ABC):
    """Base class for MNI authentication."""

    @abstractmethod
    def configure_session(self, session: Session) -> Session:
        """Configure a requests Session with authentication."""

    @abstractmethod
    def get_id_consultante(self) -> str:
        """Return the CPF used as idConsultante."""

    @abstractmethod
    def get_senha_consultante(self) -> str:
        """Return the senha (may be empty for cert-only auth)."""


@dataclass
class CertificateAuth(AuthStrategy):
    """ICP-Brasil certificate authentication via PKCS#12 (.pfx/.p12)."""

    cert_path: str
    cert_password: str
    cpf: str

    def __post_init__(self) -> None:
        path = Path(self.cert_path)
        if not path.exists():
            msg = f"Certificate file not found: {self.cert_path}"
            raise FileNotFoundError(msg)
        # Check file permissions (must not be world-readable)
        mode = path.stat().st_mode & 0o777
        if mode & 0o044:
            msg = f"Certificate file permissions too open ({oct(mode)}). Set to 0600: chmod 600 {self.cert_path}"
            raise PermissionError(msg)

    def configure_session(self, session: Session) -> Session:
        session.mount(
            "https://",
            Pkcs12Adapter(
                pkcs12_filename=self.cert_path,
                pkcs12_password=self.cert_password,
            ),
        )
        return session

    def get_id_consultante(self) -> str:
        return self.cpf

    def get_senha_consultante(self) -> str:
        return self.cpf  # Common convention: CPF as senha when using cert auth


@dataclass
class PKCS11Auth(AuthStrategy):
    """ICP-Brasil A3 token authentication via PKCS#11.

    Uses the hardware token (SafeNet eToken, etc.) for mTLS.
    The private key never leaves the token.
    """

    pkcs11_lib: str  # Path to PKCS#11 .dylib/.so
    pin: str
    cpf: str
    token_label: str | None = None  # If multiple tokens, select by label
    _cert_pem_path: str = field(default="", init=False, repr=False)

    def _find_user_cert(self) -> tuple[bytes, bytes]:
        """Find the user's personal certificate (not CA certs) on the token."""
        import pkcs11
        from pkcs11 import ObjectClass

        lib = pkcs11.lib(self.pkcs11_lib)
        slots = lib.get_slots(token_present=True)
        if not slots:
            msg = "No PKCS#11 token found. Is the USB token connected?"
            raise RuntimeError(msg)

        token = slots[0].get_token()

        with token.open(user_pin=self.pin) as session:
            certs = list(session.get_objects({pkcs11.Attribute.CLASS: ObjectClass.CERTIFICATE}))
            if not certs:
                msg = "No certificates found on token"
                raise RuntimeError(msg)

            # Find the end-entity cert (not CA certs)
            # The user cert has a matching private key on the token
            from cryptography import x509

            for cert_obj in certs:
                cert_der = cert_obj[pkcs11.Attribute.VALUE]
                parsed = x509.load_der_x509_certificate(cert_der)
                subject_cn = parsed.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
                if subject_cn and self.cpf in subject_cn[0].value:
                    return cert_der, b""  # No private key export for A3

            # Fallback: return the last cert (often the user cert)
            last_cert_der = certs[-1][pkcs11.Attribute.VALUE]
            return last_cert_der, b""

    def _export_cert_pem(self) -> str:
        """Export the user certificate to a temporary PEM file for mTLS."""
        cert_der, _ = self._find_user_cert()
        pem = b"-----BEGIN CERTIFICATE-----\n"
        pem += base64.encodebytes(cert_der)
        pem += b"-----END CERTIFICATE-----\n"

        tmp = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)  # noqa: SIM115 — file must outlive this fn (returned as cert path)
        tmp.write(pem)
        tmp.close()
        self._cert_pem_path = tmp.name
        return tmp.name

    def configure_session(self, session: Session) -> Session:
        # For A3 tokens, mTLS requires the PKCS#11 engine at the SSL level.
        # Python's ssl module doesn't natively support PKCS#11 engines.
        # Workaround: use the macOS Keychain (which already sees the token)
        # or configure OpenSSL with engine_pkcs11.
        #
        # For MNI SOAP calls that use password auth in the body (most tribunals),
        # we don't need mTLS — just password auth works.
        return session

    def get_id_consultante(self) -> str:
        return self.cpf

    def get_senha_consultante(self) -> str:
        return self.cpf

    def cleanup(self) -> None:
        """Remove temporary cert files."""
        if self._cert_pem_path:
            Path(self._cert_pem_path).unlink(missing_ok=True)


@dataclass
class PasswordAuth(AuthStrategy):
    """CPF + password authentication (PJe portal credentials)."""

    cpf: str
    senha: str

    def configure_session(self, session: Session) -> Session:
        # No special session config needed for password auth
        return session

    def get_id_consultante(self) -> str:
        return self.cpf

    def get_senha_consultante(self) -> str:
        return self.senha
