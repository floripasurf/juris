"""Authentication strategies for MNI SOAP calls."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
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
