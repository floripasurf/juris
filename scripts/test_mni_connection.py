"""Test MNI connection using the A3 token via PKCS#11.

Usage:
    uv run python scripts/test_mni_connection.py

This script:
1. Opens the PKCS#11 token (prompts for PIN securely)
2. Extracts the certificate
3. Attempts to connect to the TJMG MNI WSDL
4. If successful, queries a test process
"""

from __future__ import annotations

import getpass
import ssl
import tempfile
from pathlib import Path

import pkcs11
from pkcs11 import KeyType, ObjectClass

PKCS11_LIB = "/usr/local/lib/libeTPkcs11.dylib"

# Candidate WSDL endpoints for TJMG
TJMG_ENDPOINTS = [
    "https://pje.tjmg.jus.br/pje/intercomunicacao?wsdl",
    "https://pje.tjmg.jus.br/pje/Intercomunicacao?wsdl",
    "https://pje.tjmg.jus.br/pje/intercomunicacao-2.2.2?wsdl",
]

TEST_PROCESSO = "5082351-40.2017.8.13.0024"
CPF = "07671039632"


def main() -> None:
    pin = getpass.getpass("PIN do token A3: ")

    print("\n[1] Opening PKCS#11 token...")
    lib = pkcs11.lib(PKCS11_LIB)
    slots = lib.get_slots(token_present=True)
    if not slots:
        print("ERROR: No token found. Is the USB token connected?")
        return

    token = slots[0].get_token()
    print(f"    Token: {token.label} ({token.model})")

    with token.open(user_pin=pin) as session:
        print("    Session opened OK")

        # Find certificate
        certs = list(session.get_objects({pkcs11.Attribute.CLASS: ObjectClass.CERTIFICATE}))
        print(f"    Found {len(certs)} certificate(s)")

        if not certs:
            print("ERROR: No certificates on token")
            return

        cert = certs[0]
        cert_der = cert[pkcs11.Attribute.VALUE]
        print(f"    Certificate size: {len(cert_der)} bytes")

        # Save cert to temp file for requests
        cert_pem_path = Path(tempfile.mktemp(suffix=".pem"))
        # Convert DER to PEM
        import base64
        pem = b"-----BEGIN CERTIFICATE-----\n"
        pem += base64.encodebytes(cert_der)
        pem += b"-----END CERTIFICATE-----\n"
        cert_pem_path.write_bytes(pem)
        print(f"    Certificate saved to: {cert_pem_path}")

        # Extract certificate details
        try:
            from cryptography import x509
            parsed = x509.load_der_x509_certificate(cert_der)
            print(f"    Subject: {parsed.subject}")
            print(f"    Issuer: {parsed.issuer}")
            print(f"    Valid until: {parsed.not_valid_after_utc}")
        except Exception as e:
            print(f"    Could not parse cert details: {e}")

    # Now try WSDL endpoints
    # Note: For A3 tokens, we can't use requests-pkcs12 (that's for .pfx files)
    # We need to use the macOS Keychain or a custom SSL context
    print("\n[2] Testing TJMG MNI endpoints...")
    import requests

    for url in TJMG_ENDPOINTS:
        try:
            # Try without cert first
            resp = requests.get(url, timeout=15)
            is_wsdl = "wsdl:" in resp.text or "<?xml" in resp.text[:100]
            print(f"    {url}")
            print(f"      Status: {resp.status_code} | WSDL: {is_wsdl}")
            if is_wsdl:
                print(f"      SUCCESS — WSDL found!")
                print(f"      First 200 chars: {resp.text[:200]}")
        except Exception as e:
            print(f"    {url}")
            print(f"      ERROR: {e}")

    # Try with client certificate via SSL context
    print("\n[3] Testing with client certificate (PEM)...")
    for url in TJMG_ENDPOINTS:
        try:
            resp = requests.get(url, timeout=15, cert=str(cert_pem_path))
            is_wsdl = "wsdl:" in resp.text or "<?xml" in resp.text[:100]
            print(f"    {url}")
            print(f"      Status: {resp.status_code} | WSDL: {is_wsdl}")
            if is_wsdl:
                print(f"      SUCCESS with cert!")
        except Exception as e:
            print(f"    {url}")
            print(f"      ERROR: {type(e).__name__}: {e}")

    # Cleanup
    cert_pem_path.unlink(missing_ok=True)
    print("\nDone. If no WSDL was found, TJMG may not expose MNI publicly.")
    print("Alternative: use DataJud API for process discovery + TJMG portal for details.")


if __name__ == "__main__":
    main()
