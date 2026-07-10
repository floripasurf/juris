"""MNI auth safety tests for certificate-backed flows."""

from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from requests import Session

from juris.mni.auth import CertificateAuth, PasswordAuth, PKCS11Auth


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_certificate_auth_rejects_world_readable_p12(tmp_path: Path) -> None:
    cert = tmp_path / "cert.p12"
    cert.write_bytes(b"not-a-real-p12")
    cert.chmod(0o644)

    with pytest.raises(PermissionError, match="too open"):
        CertificateAuth(str(cert), "secret", "12345678901")


def test_certificate_auth_accepts_owner_only_p12_and_mounts_adapter(tmp_path: Path) -> None:
    cert = tmp_path / "cert.p12"
    cert.write_bytes(b"not-a-real-p12")
    cert.chmod(0o600)
    session = Session()

    with patch("juris.mni.auth.Pkcs12Adapter", autospec=True) as adapter_cls:
        adapter = MagicMock()
        adapter_cls.return_value = adapter
        auth = CertificateAuth(str(cert), "secret", "12345678901")

        configured = auth.configure_session(session)

    assert configured is session
    adapter_cls.assert_called_once_with(pkcs12_filename=str(cert), pkcs12_password="secret")  # noqa: S106
    assert auth.get_id_consultante() == "12345678901"
    assert auth.get_senha_consultante() == "12345678901"


def test_pkcs11_exported_certificate_tempfile_is_owner_only_and_cleaned(monkeypatch: pytest.MonkeyPatch) -> None:
    auth = PKCS11Auth("/usr/local/lib/libeTPkcs11.dylib", "1234", "12345678901")
    monkeypatch.setattr(auth, "_find_user_cert", lambda: (b"\x30\x82DER", b""))

    pem_path = Path(auth._export_cert_pem())

    try:
        assert pem_path.exists()
        assert pem_path.read_text(encoding="ascii").startswith("-----BEGIN CERTIFICATE-----")
        assert _mode(pem_path) == 0o600
    finally:
        auth.cleanup()
    assert not pem_path.exists()


def test_password_auth_keeps_session_unchanged() -> None:
    session = Session()
    auth = PasswordAuth("12345678901", "senha-pje")

    assert auth.configure_session(session) is session
    assert auth.get_id_consultante() == "12345678901"
    assert auth.get_senha_consultante() == "senha-pje"
