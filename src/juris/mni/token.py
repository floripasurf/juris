"""ICP-Brasil A3 hardware-token access via PKCS#11.

Extracts the user certificate, CA chain and private-key URI from a
connected token (e.g. SafeNet eToken with an e-CPF) so they can be used
for mTLS against tribunals that require client-certificate authentication.

The private key never leaves the token — only the public certificate and
the key's PKCS#11 URI are materialised. All crypto happens on the device.
"""

from __future__ import annotations

import base64
import contextlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from juris.core.observability import get_logger
from juris.mni.pkcs11_transport import PKCS11Config

logger = get_logger(__name__)

# Default SafeNet eToken PKCS#11 module on macOS (Homebrew/eToken framework).
DEFAULT_PKCS11_MODULE = "/usr/local/lib/libeTPkcs11.dylib"


@dataclass(frozen=True, slots=True)
class TokenMaterial:
    """Public material extracted from a hardware token.

    Attributes:
        token_label: PKCS#11 token label (e.g. ``"TOKEN CERTDATA"``).
        subject: RFC4514 subject of the user certificate.
        cpf: CPF parsed from the e-CPF subject, if present.
        not_valid_after: Certificate expiry, ISO date string.
        cert_pem_path: Path to the user certificate in PEM form.
        chain_pem_path: Path to the concatenated CA chain in PEM form.
        key_id_hex: Hex-encoded CKA_ID shared by cert and private key.
    """

    token_label: str
    subject: str
    cpf: str | None
    not_valid_after: str
    cert_pem_path: str
    chain_pem_path: str
    key_id_hex: str


class TokenError(RuntimeError):
    """Raised when the token is absent or holds no usable certificate."""


def _der_to_pem(der: bytes) -> bytes:
    return b"-----BEGIN CERTIFICATE-----\n" + base64.encodebytes(der) + b"-----END CERTIFICATE-----\n"


def _cpf_from_subject(subject: str) -> str | None:
    # e-CPF subjects embed the CPF as ``CN=NOME:NNNNNNNNNNN``.
    import re

    m = re.search(r":(\d{11})\b", subject)
    return m.group(1) if m else None


def extract_token_material(
    pkcs11_module: str = DEFAULT_PKCS11_MODULE,
    out_dir: str | None = None,
) -> TokenMaterial:
    """Read the user certificate and CA chain from the connected token.

    No PIN is required: certificates are public objects on the token.

    Args:
        pkcs11_module: Path to the PKCS#11 .dylib/.so module.
        out_dir: Directory for the PEM files (a temp dir if omitted).

    Returns:
        :class:`TokenMaterial` with PEM paths and the private-key id.

    Raises:
        TokenError: If no token or no user certificate is found.
    """
    import pkcs11
    from cryptography import x509
    from pkcs11 import Attribute, ObjectClass

    if not Path(pkcs11_module).exists():
        msg = f"PKCS#11 module not found: {pkcs11_module}"
        raise TokenError(msg)

    lib = pkcs11.lib(pkcs11_module)
    slots = lib.get_slots(token_present=True)
    if not slots:
        msg = "No hardware token detected. Is the USB token connected?"
        raise TokenError(msg)

    token = slots[0].get_token()
    user_pem: bytes | None = None
    user_subject = ""
    user_expiry = ""
    key_id_hex = ""
    chain: list[bytes] = []

    with token.open() as session:
        certs = list(session.get_objects({Attribute.CLASS: ObjectClass.CERTIFICATE}))
        if not certs:
            msg = "Token holds no certificates."
            raise TokenError(msg)

        for cert in certs:
            der = cert[Attribute.VALUE]
            parsed = x509.load_der_x509_certificate(der)
            is_ca = False
            with contextlib.suppress(x509.ExtensionNotFound):
                is_ca = parsed.extensions.get_extension_for_class(x509.BasicConstraints).value.ca

            if is_ca:
                chain.append(_der_to_pem(der))
            else:
                user_pem = _der_to_pem(der)
                user_subject = parsed.subject.rfc4514_string()
                user_expiry = parsed.not_valid_after_utc.date().isoformat()
                key_id_hex = bytes(cert[Attribute.ID]).hex()

    if user_pem is None or not key_id_hex:
        msg = "No user (non-CA) certificate found on token."
        raise TokenError(msg)

    base = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="juris-token-"))
    base.mkdir(parents=True, exist_ok=True)
    cert_path = base / "user_cert.pem"
    chain_path = base / "chain.pem"
    cert_path.write_bytes(user_pem)
    chain_path.write_bytes(b"".join(chain))
    # PEM files carry only public material; tighten perms regardless.
    cert_path.chmod(0o600)
    chain_path.chmod(0o600)

    logger.info(
        "token_material_extracted",
        token_label=token.label,
        subject=user_subject,
        expires=user_expiry,
        ca_count=len(chain),
    )

    return TokenMaterial(
        token_label=token.label,
        subject=user_subject,
        cpf=_cpf_from_subject(user_subject),
        not_valid_after=user_expiry,
        cert_pem_path=str(cert_path),
        chain_pem_path=str(chain_path),
        key_id_hex=key_id_hex,
    )


def _percent_encode_bytes(raw: bytes) -> str:
    """Percent-encode every byte (PKCS#11 URI id component)."""
    return "".join(f"%{b:02x}" for b in raw)


def build_pkcs11_config(
    material: TokenMaterial,
    pin: str,
    pkcs11_module: str = DEFAULT_PKCS11_MODULE,
) -> PKCS11Config:
    """Assemble a :class:`PKCS11Config` from extracted token material and a PIN.

    Args:
        material: Output of :func:`extract_token_material`.
        pin: Token PIN (held only in memory).
        pkcs11_module: Path to the PKCS#11 module.

    Returns:
        A :class:`PKCS11Config` pointing at the private key on the token.
    """
    token_label = quote(material.token_label)
    key_id = _percent_encode_bytes(bytes.fromhex(material.key_id_hex))
    key_uri = f"pkcs11:token={token_label};id={key_id};type=private"

    return PKCS11Config(
        pkcs11_module=pkcs11_module,
        pin=pin,
        cert_pem_path=material.cert_pem_path,
        chain_pem_path=material.chain_pem_path,
        key_uri=key_uri,
    )
