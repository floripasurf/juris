"""Secure credential storage for MNI authentication.

Stores credentials (PJe passwords, token PINs) in the macOS Keychain
or a local encrypted file, so users only need to enter them once.
"""

from __future__ import annotations

import base64
import getpass
import json
import os
import uuid
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from juris.core.observability import get_logger

logger = get_logger(__name__)

_SECURITY_BIN = "/usr/bin/security"
_KEYCHAIN_SERVICE = "juris-legal-ai"
_FALLBACK_DIR: Path | None = None
_FALLBACK_WARNING_EMITTED = False
_KDF_ITERATIONS = 390_000


def store_credential(key: str, value: str) -> None:
    """Store a credential securely.

    Tries macOS Keychain first, falls back to encrypted file.

    Args:
        key: Credential identifier (e.g., 'tjmg_password', 'token_pin').
        value: The secret value.
    """
    if _try_keychain_store(key, value):
        logger.info("credential_stored", key=key, backend="keychain")
        return

    _file_store(key, value)
    logger.info("credential_stored", key=key, backend="file")


def get_credential(key: str) -> str | None:
    """Retrieve a stored credential.

    Args:
        key: Credential identifier.

    Returns:
        The secret value, or None if not found.
    """
    value = _try_keychain_get(key)
    if value is not None:
        return value

    return _file_get(key)


def delete_credential(key: str) -> None:
    """Remove a stored credential."""
    _try_keychain_delete(key)
    _file_delete(key)


def _try_keychain_store(key: str, value: str) -> bool:
    """Store in macOS Keychain via security command."""
    try:
        import subprocess

        # Delete existing entry first (security add fails if exists)
        subprocess.run(  # noqa: S603
            [_SECURITY_BIN, "delete-generic-password", "-s", _KEYCHAIN_SERVICE, "-a", key],
            capture_output=True,
        )
        result = subprocess.run(  # noqa: S603
            [_SECURITY_BIN, "add-generic-password", "-s", _KEYCHAIN_SERVICE, "-a", key, "-w", value],
            capture_output=True, text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False  # Not on macOS


def _try_keychain_get(key: str) -> str | None:
    """Get from macOS Keychain."""
    try:
        import subprocess

        result = subprocess.run(  # noqa: S603
            [_SECURITY_BIN, "find-generic-password", "-s", _KEYCHAIN_SERVICE, "-a", key, "-w"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except FileNotFoundError:
        return None


def _try_keychain_delete(key: str) -> None:
    """Delete from macOS Keychain."""
    try:
        import subprocess

        subprocess.run(  # noqa: S603
            [_SECURITY_BIN, "delete-generic-password", "-s", _KEYCHAIN_SERVICE, "-a", key],
            capture_output=True,
        )
    except FileNotFoundError:
        pass


def _file_store(key: str, value: str) -> None:
    """Fallback: store in an encrypted local file with restricted permissions."""
    _warn_file_fallback()
    fallback_dir = _fallback_dir()
    fallback_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(fallback_dir, 0o700)

    cred_file = fallback_dir / "credentials.json"
    data: dict[str, str | dict[str, str]] = {}
    if cred_file.exists():
        _restrict_file_permissions(cred_file)
        data = json.loads(cred_file.read_text(encoding="utf-8"))

    data[key] = _encrypt_value(value)
    cred_file.write_text(json.dumps(data), encoding="utf-8")
    _restrict_file_permissions(cred_file)


def _file_get(key: str) -> str | None:
    """Fallback: get from local encrypted file."""
    cred_file = _fallback_dir() / "credentials.json"
    if not cred_file.exists():
        return None
    _warn_file_fallback()
    _restrict_file_permissions(cred_file)
    data = json.loads(cred_file.read_text(encoding="utf-8"))
    stored_value = data.get(key)
    if stored_value is None:
        return None
    if isinstance(stored_value, str):
        # Migrate legacy plaintext entry to encrypted on access
        _file_store(key, stored_value)
        return stored_value
    return _decrypt_value(stored_value)


def _file_delete(key: str) -> None:
    """Fallback: delete from local encrypted file."""
    cred_file = _fallback_dir() / "credentials.json"
    if not cred_file.exists():
        return
    _restrict_file_permissions(cred_file)
    data = json.loads(cred_file.read_text(encoding="utf-8"))
    data.pop(key, None)
    cred_file.write_text(json.dumps(data), encoding="utf-8")
    _restrict_file_permissions(cred_file)


def _fallback_dir() -> Path:
    """Directory for file fallback, overridable in tests and by ``JURIS_HOME``."""
    if _FALLBACK_DIR is not None:
        return _FALLBACK_DIR
    return Path(os.environ.get("JURIS_HOME", str(Path.home() / ".juris"))) / "credentials"


def _restrict_file_permissions(path: Path) -> None:
    """Ensure the fallback credential file is owner-read/write only."""
    os.chmod(path.parent, 0o700)
    os.chmod(path, 0o600)


def _warn_file_fallback() -> None:
    """Emit a one-time warning when the encrypted file fallback is used."""
    global _FALLBACK_WARNING_EMITTED  # noqa: PLW0603
    if _FALLBACK_WARNING_EMITTED:
        return
    logger.warning("keyring_unavailable_using_encrypted_file_fallback")
    _FALLBACK_WARNING_EMITTED = True


def _encrypt_value(value: str) -> dict[str, str]:
    """Encrypt a credential for file-based storage."""
    key, salt_b64 = _get_or_create_key()
    ciphertext = Fernet(key).encrypt(value.encode("utf-8")).decode("ascii")
    return {"salt": salt_b64, "ciphertext": ciphertext}


def _decrypt_value(payload: dict[str, str]) -> str:
    """Decrypt a credential from file-based storage."""
    key, _ = _get_or_create_key(payload["salt"])
    plaintext = Fernet(key).decrypt(payload["ciphertext"].encode("ascii"))
    return plaintext.decode("utf-8")


def _get_or_create_key(salt_b64: str | None = None) -> tuple[bytes, str]:
    """Derive an encryption key from machine identity and a per-entry salt."""
    if salt_b64 is None:
        salt = os.urandom(16)
        salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
    else:
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))

    machine_identity = _get_machine_identity().encode("utf-8")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_KDF_ITERATIONS,
    )
    derived = kdf.derive(machine_identity)
    return base64.urlsafe_b64encode(derived), salt_b64


def _get_machine_identity() -> str:
    """Build a stable machine-local identity for key derivation."""
    return f"{getpass.getuser()}:{uuid.getnode()}"
