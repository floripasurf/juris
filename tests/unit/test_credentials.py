"""Tests for credential storage."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.fernet import InvalidToken

from juris.core.credentials import (
    _get_or_create_key,
    delete_credential,
    get_credential,
    store_credential,
)


class TestFileCredentials:
    """Test file-based credential storage (doesn't depend on macOS Keychain)."""

    def test_store_and_get(self, tmp_path: Path, monkeypatch: object) -> None:
        import juris.core.credentials as creds

        monkeypatch.setattr(creds, "_FALLBACK_DIR", tmp_path / "creds")
        monkeypatch.setattr(creds, "_try_keychain_store", lambda k, v: False)
        monkeypatch.setattr(creds, "_try_keychain_get", lambda k: None)
        monkeypatch.setattr(creds, "_get_machine_identity", lambda: "test-user:12345")

        store_credential("test_key", "secret123")
        assert get_credential("test_key") == "secret123"

        cred_file = tmp_path / "creds" / "credentials.json"
        raw = cred_file.read_text()
        assert "secret123" not in raw

    def test_get_nonexistent(self, tmp_path: Path, monkeypatch: object) -> None:
        import juris.core.credentials as creds

        monkeypatch.setattr(creds, "_FALLBACK_DIR", tmp_path / "creds")
        monkeypatch.setattr(creds, "_try_keychain_get", lambda k: None)
        monkeypatch.setattr(creds, "_get_machine_identity", lambda: "test-user:12345")

        assert get_credential("nonexistent") is None

    def test_delete(self, tmp_path: Path, monkeypatch: object) -> None:
        import juris.core.credentials as creds

        monkeypatch.setattr(creds, "_FALLBACK_DIR", tmp_path / "creds")
        monkeypatch.setattr(creds, "_try_keychain_store", lambda k, v: False)
        monkeypatch.setattr(creds, "_try_keychain_get", lambda k: None)
        monkeypatch.setattr(creds, "_try_keychain_delete", lambda k: None)
        monkeypatch.setattr(creds, "_get_machine_identity", lambda: "test-user:12345")

        store_credential("to_delete", "value")
        assert get_credential("to_delete") == "value"

        delete_credential("to_delete")
        assert get_credential("to_delete") is None

    def test_file_permissions(self, tmp_path: Path, monkeypatch: object) -> None:
        import juris.core.credentials as creds

        cred_dir = tmp_path / "creds"
        monkeypatch.setattr(creds, "_FALLBACK_DIR", cred_dir)
        monkeypatch.setattr(creds, "_try_keychain_store", lambda k, v: False)
        monkeypatch.setattr(creds, "_get_machine_identity", lambda: "test-user:12345")

        store_credential("perm_test", "value")

        cred_file = cred_dir / "credentials.json"
        mode = cred_file.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0600, got {oct(mode)}"

    def test_tampered_ciphertext_raises(self, tmp_path: Path, monkeypatch: object) -> None:
        import juris.core.credentials as creds

        cred_dir = tmp_path / "creds"
        monkeypatch.setattr(creds, "_FALLBACK_DIR", cred_dir)
        monkeypatch.setattr(creds, "_try_keychain_store", lambda k, v: False)
        monkeypatch.setattr(creds, "_try_keychain_get", lambda k: None)
        monkeypatch.setattr(creds, "_get_machine_identity", lambda: "test-user:12345")

        store_credential("test_key", "secret123")

        cred_file = cred_dir / "credentials.json"
        data = json.loads(cred_file.read_text())
        ciphertext = data["test_key"]["ciphertext"]
        data["test_key"]["ciphertext"] = ciphertext[:-2] + "xx"
        cred_file.write_text(json.dumps(data))

        with pytest.raises(InvalidToken):
            get_credential("test_key")

    def test_different_salts_produce_different_keys(self, monkeypatch: object) -> None:
        import juris.core.credentials as creds

        monkeypatch.setattr(creds, "_get_machine_identity", lambda: "test-user:12345")

        salt_a = base64.urlsafe_b64encode(b"salt-000000000001").decode("ascii")
        salt_b = base64.urlsafe_b64encode(b"salt-000000000002").decode("ascii")

        key_a, _ = _get_or_create_key(salt_a)
        key_b, _ = _get_or_create_key(salt_b)

        assert key_a != key_b
