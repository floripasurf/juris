"""Test TJMG MNI WSDL access using A3 token via PKCS#11 for mTLS.

Tries multiple approaches:
1. PKCS#11 token detection + cert extraction
2. curl with OpenSSL engine_pkcs11
3. Python ssl context with exported cert + engine
4. Direct zeep with custom transport

Usage:
    uv run python scripts/test_tjmg_mtls.py
"""

from __future__ import annotations

import base64
import getpass
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PKCS11_LIB = "/usr/local/lib/libeTPkcs11.dylib"
TJMG_WSDL = "https://pje.tjmg.jus.br/pje/intercomunicacao?wsdl"
TJMG_BASE = "https://pje.tjmg.jus.br/pje/intercomunicacao"
CPF = "07671039632"


def step1_detect_token() -> bool:
    """Check if the A3 token is connected via PKCS#11."""
    print("\n[1] Detecting A3 token via PKCS#11...")

    if not Path(PKCS11_LIB).exists():
        print(f"  ERROR: PKCS#11 library not found at {PKCS11_LIB}")
        return False

    try:
        import pkcs11
        lib = pkcs11.lib(PKCS11_LIB)
        slots = lib.get_slots(token_present=True)
        if not slots:
            print("  ERROR: No token found. Is the USB token connected?")
            return False

        token = slots[0].get_token()
        print(f"  Token: {token.label} ({token.model})")
        print(f"  Manufacturer: {token.manufacturer_id}")
        return True
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def step2_extract_cert(pin: str) -> tuple[str, str] | None:
    """Extract the user certificate from the token to a temp PEM file."""
    print("\n[2] Extracting certificate from token...")

    try:
        import pkcs11
        from pkcs11 import ObjectClass

        lib = pkcs11.lib(PKCS11_LIB)
        slots = lib.get_slots(token_present=True)
        token = slots[0].get_token()

        with token.open(user_pin=pin) as session:
            certs = list(session.get_objects({pkcs11.Attribute.CLASS: ObjectClass.CERTIFICATE}))
            print(f"  Found {len(certs)} certificate(s) on token")

            # Find user cert (not CA)
            from cryptography import x509

            user_cert_der = None
            for cert_obj in certs:
                cert_der = cert_obj[pkcs11.Attribute.VALUE]
                parsed = x509.load_der_x509_certificate(cert_der)
                cn_attrs = parsed.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
                if cn_attrs:
                    cn = cn_attrs[0].value
                    print(f"    Cert CN: {cn}")
                    print(f"    Valid until: {parsed.not_valid_after_utc}")
                    # User cert has CPF in the CN or is not a CA
                    if CPF in cn or not parsed.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
                        user_cert_der = cert_der
                        print(f"    >>> Using this cert (user cert)")

            if user_cert_der is None:
                # Fallback: use last cert
                user_cert_der = certs[-1][pkcs11.Attribute.VALUE]
                print(f"    Using last cert as fallback")

            # Save cert PEM
            pem = b"-----BEGIN CERTIFICATE-----\n"
            pem += base64.encodebytes(user_cert_der)
            pem += b"-----END CERTIFICATE-----\n"

            cert_path = tempfile.mktemp(suffix=".pem")
            Path(cert_path).write_bytes(pem)
            print(f"  Cert saved to: {cert_path}")

            # Also check for private key objects (A3 = key stays on token)
            priv_keys = list(session.get_objects({pkcs11.Attribute.CLASS: ObjectClass.PRIVATE_KEY}))
            print(f"  Private keys on token: {len(priv_keys)}")

            return cert_path, pin

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


def step3_curl_with_pkcs11_engine(cert_pem: str, pin: str) -> bool:
    """Try curl with OpenSSL engine_pkcs11."""
    print("\n[3] Testing with curl + PKCS#11 engine...")

    # First: simple curl without client cert (baseline)
    print("  [3a] Baseline: curl without client cert...")
    try:
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "15", TJMG_WSDL],
            capture_output=True, text=True, timeout=20,
        )
        print(f"  HTTP status: {result.stdout}")
    except Exception as e:
        print(f"  Error: {e}")

    # Try curl with the engine_pkcs11
    # This requires: brew install engine_pkcs11 (libp11)
    print("\n  [3b] Checking for OpenSSL PKCS#11 engine...")
    engine_paths = [
        "/usr/local/lib/engines-3/pkcs11.dylib",
        "/opt/homebrew/lib/engines-3/pkcs11.dylib",
        "/usr/local/lib/engines/pkcs11.dylib",
        "/opt/homebrew/lib/engines/pkcs11.dylib",
    ]
    engine_found = None
    for ep in engine_paths:
        if Path(ep).exists():
            engine_found = ep
            print(f"  Found engine at: {ep}")
            break

    if not engine_found:
        print("  PKCS#11 engine not found. Install with: brew install libp11")
        print("  Skipping curl engine test.")
    else:
        # Build PKCS#11 URI for the key
        pkcs11_uri = f"pkcs11:manufacturer=SafeNet;pin-value={pin}"
        print(f"  Trying curl with engine...")
        try:
            result = subprocess.run(
                [
                    "curl", "-v", "--max-time", "15",
                    "--engine", "pkcs11",
                    "--key-type", "ENG",
                    "--key", pkcs11_uri,
                    "--cert-type", "PEM",
                    "--cert", cert_pem,
                    TJMG_WSDL,
                ],
                capture_output=True, text=True, timeout=20,
            )
            print(f"  Exit code: {result.returncode}")
            if result.stdout:
                is_wsdl = "wsdl:" in result.stdout[:500] or "<?xml" in result.stdout[:100]
                print(f"  WSDL detected: {is_wsdl}")
                if is_wsdl:
                    print(f"  >>> SUCCESS! TJMG WSDL accessible with mTLS! <<<")
                    return True
                print(f"  Response preview: {result.stdout[:300]}")
            if result.stderr:
                # Filter for useful SSL info
                for line in result.stderr.split("\n"):
                    if any(kw in line.lower() for kw in ["ssl", "tls", "cert", "error", "alert"]):
                        print(f"  {line.strip()}")
        except Exception as e:
            print(f"  Error: {e}")

    return False


def step4_python_ssl_with_pkcs11(cert_pem: str, pin: str) -> bool:
    """Try Python requests with custom SSL context using PKCS#11."""
    print("\n[4] Testing Python SSL with PKCS#11...")

    # Approach A: Try with just the cert PEM (no private key — will fail for mTLS but shows SSL behavior)
    print("  [4a] requests with cert PEM only (expect failure — no private key)...")
    try:
        import requests
        resp = requests.get(TJMG_WSDL, timeout=15, cert=cert_pem)
        print(f"  Status: {resp.status_code}")
        is_wsdl = "wsdl:" in resp.text[:500] or "<?xml" in resp.text[:100]
        if is_wsdl:
            print(f"  >>> WSDL found without mTLS! <<<")
            return True
        print(f"  Response: {resp.text[:200]}")
    except Exception as e:
        err = str(e)
        if "SSL" in err or "handshake" in err.lower():
            print(f"  SSL error (expected without private key): {err[:150]}")
        else:
            print(f"  Error: {type(e).__name__}: {err[:150]}")

    # Approach B: Try OpenSSL with PKCS#11 provider via ctypes/subprocess
    print("\n  [4b] openssl s_client with PKCS#11...")
    try:
        # Test if we can reach the server at all
        result = subprocess.run(
            [
                "openssl", "s_client",
                "-connect", "pje.tjmg.jus.br:443",
                "-servername", "pje.tjmg.jus.br",
                "-brief",
            ],
            input="", capture_output=True, text=True, timeout=15,
        )
        for line in result.stdout.split("\n")[:10]:
            if line.strip():
                print(f"    {line.strip()}")
        for line in result.stderr.split("\n"):
            if any(kw in line.lower() for kw in ["verify", "certificate", "error", "subject"]):
                print(f"    {line.strip()}")
    except Exception as e:
        print(f"  Error: {e}")

    return False


def step5_try_zeep_without_cert() -> bool:
    """Test if TJMG WSDL is actually accessible without cert (maybe it changed)."""
    print("\n[5] Testing zeep without client cert (maybe TJMG opened the WSDL)...")
    try:
        from zeep import Client, Settings
        from zeep.transports import Transport
        from requests import Session

        transport = Transport(session=Session(), timeout=15, operation_timeout=30)
        settings = Settings(strict=False, xml_huge_tree=True)
        client = Client(wsdl=TJMG_WSDL, transport=transport, settings=settings)
        ops = list(client.service._operations.keys())
        print(f"  Operations: {', '.join(ops)}")
        print(f"  >>> TJMG WSDL accessible WITHOUT mTLS! <<<")
        return True
    except Exception as e:
        print(f"  Failed: {type(e).__name__}: {str(e)[:200]}")
        return False


def step6_try_alternative_urls() -> bool:
    """Try alternative TJMG PJe URLs that might expose MNI."""
    print("\n[6] Testing alternative TJMG endpoints...")

    import requests

    alternatives = [
        "https://pje.tjmg.jus.br/pje/intercomunicacao?wsdl",
        "https://pje.tjmg.jus.br/pje/Intercomunicacao?wsdl",
        "https://pje.tjmg.jus.br/pje/intercomunicacao-2.2.2?wsdl",
        "https://pje.tjmg.jus.br/pje/mni/intercomunicacao?wsdl",
        "https://pje.tjmg.jus.br/pje/ws/intercomunicacao?wsdl",
        # PJe 2nd instance
        "https://pje2.tjmg.jus.br/pje/intercomunicacao?wsdl",
        # SJMG (Seção Judiciária de MG — federal, now TRF6)
        "https://pje.trf6.jus.br/pje/intercomunicacao?wsdl",
        "https://pje1.trf6.jus.br/pje/intercomunicacao?wsdl",
    ]

    for url in alternatives:
        try:
            resp = requests.get(url, timeout=10, allow_redirects=True)
            is_wsdl = any(m in resp.text[:500] for m in ["wsdl:", "definitions", "<wsdl"])
            status = "WSDL" if is_wsdl else f"HTTP{resp.status_code}"
            print(f"  {url}")
            print(f"    Status: {status}")
            if is_wsdl:
                print(f"    >>> FOUND WSDL! <<<")
                return True
        except requests.exceptions.SSLError:
            print(f"  {url}")
            print(f"    SSL_ERR (may need client cert)")
        except requests.exceptions.ConnectionError:
            print(f"  {url}")
            print(f"    CONN_ERR")
        except requests.exceptions.Timeout:
            print(f"  {url}")
            print(f"    TIMEOUT")
        except Exception as e:
            print(f"  {url}")
            print(f"    {type(e).__name__}: {str(e)[:80]}")

    return False


def main() -> None:
    print("=" * 60)
    print("TJMG MNI mTLS Test — Using A3 Token via PKCS#11")
    print("=" * 60)

    if not step1_detect_token():
        print("\nToken not detected. Connect your USB token and try again.")
        sys.exit(1)

    pin = os.environ.get("TOKEN_PIN", "")
    if not pin:
        try:
            pin = getpass.getpass("PIN do token A3: ")
        except EOFError:
            print("\nCannot read PIN interactively. Set TOKEN_PIN env var:")
            print("  TOKEN_PIN=yourpin uv run python scripts/test_tjmg_mtls.py")
            sys.exit(1)

    cert_info = step2_extract_cert(pin)
    if not cert_info:
        print("\nFailed to extract certificate. Check PIN and try again.")
        sys.exit(1)

    cert_pem, pin = cert_info

    # Try all approaches
    success = False
    success = step5_try_zeep_without_cert() or success
    success = step6_try_alternative_urls() or success
    success = step3_curl_with_pkcs11_engine(cert_pem, pin) or success
    success = step4_python_ssl_with_pkcs11(cert_pem, pin) or success

    # Cleanup
    Path(cert_pem).unlink(missing_ok=True)

    print("\n" + "=" * 60)
    if success:
        print("SUCCESS: Found a way to access TJMG MNI!")
    else:
        print("TJMG MNI remains inaccessible.")
        print("\nNext steps:")
        print("  1. Install libp11: brew install libp11")
        print("  2. Try mTLS with engine_pkcs11 + your A3 token")
        print("  3. Or register your CPF on TJES (pje.tjes.jus.br)")
        print("     for immediate live testing on a working tribunal")
    print("=" * 60)


if __name__ == "__main__":
    main()
