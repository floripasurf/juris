"""PKCS#11-backed SOAP transport for mTLS with hardware tokens.

Uses OpenSSL's engine_pkcs11 (via subprocess) to perform TLS client
authentication with a private key that lives on a hardware token
(e.g., SafeNet eToken 5100 with ICP-Brasil A3 certificate).

The private key never leaves the token — all crypto operations happen
on the hardware device.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any

from juris.core.observability import get_logger

logger = get_logger(__name__)

# Paths to OpenSSL and PKCS#11 libraries (macOS with Homebrew)
_OPENSSL_BIN = "/opt/homebrew/opt/openssl@3/bin/openssl"
_PKCS11_ENGINE = "/opt/homebrew/lib/engines-3/pkcs11.dylib"
_PKCS11_MODULE_DEFAULT = "/usr/local/lib/libeTPkcs11.dylib"


@dataclass(frozen=True, slots=True)
class PKCS11Config:
    """Configuration for PKCS#11 hardware token access."""

    pkcs11_module: str = _PKCS11_MODULE_DEFAULT
    pin: str = ""
    cert_pem_path: str = ""  # Path to exported user cert PEM
    chain_pem_path: str = ""  # Path to CA chain PEM (optional)
    key_uri: str = ""  # PKCS#11 URI for the private key
    openssl_bin: str = _OPENSSL_BIN


@dataclass
class SOAPResponse:
    """Raw SOAP response from a PKCS#11 mTLS call."""

    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    is_multipart: bool = False

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


def pkcs11_soap_call(
    host: str,
    path: str,
    soap_xml: str | bytes,
    config: PKCS11Config,
    soap_action: str = "",
    timeout: int = 30,
) -> SOAPResponse:
    """Make a SOAP call using mTLS with a PKCS#11 hardware token.

    Args:
        host: Target hostname (e.g., 'pje-consulta-publica.tjmg.jus.br').
        path: URL path (e.g., '/pje/intercomunicacao').
        soap_xml: SOAP envelope XML (str or bytes).
        config: PKCS#11 configuration.
        soap_action: SOAPAction header value.
        timeout: Timeout in seconds.

    Returns:
        SOAPResponse with status, headers, and body.

    Raises:
        RuntimeError: If OpenSSL or PKCS#11 setup fails.
        TimeoutError: If the request times out.
    """
    if isinstance(soap_xml, str):
        soap_xml = soap_xml.encode("utf-8")

    content_length = len(soap_xml)

    # Build HTTP request
    http_request = (
        f"POST {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Content-Type: text/xml; charset=utf-8\r\n"
        f"Content-Length: {content_length}\r\n"
        f"SOAPAction: \"{soap_action}\"\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode("utf-8") + soap_xml

    # Build openssl s_client command
    cmd = [
        config.openssl_bin, "s_client",
        "-engine", "pkcs11",
        "-keyform", "engine",
        "-key", config.key_uri,
        "-cert", config.cert_pem_path,
        "-connect", f"{host}:443",
        "-servername", host,
        "-quiet",
    ]

    if config.chain_pem_path:
        cmd.extend(["-CAfile", config.chain_pem_path])

    env = os.environ.copy()
    env["PKCS11_MODULE_PATH"] = config.pkcs11_module
    if config.pin:
        env["PKCS11_PIN"] = config.pin

    logger.info(
        "pkcs11_soap_call",
        host=host,
        path=path,
        content_length=content_length,
    )

    try:
        result = subprocess.run(
            cmd,
            input=http_request,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        msg = f"PKCS#11 SOAP call timed out after {timeout}s"
        raise TimeoutError(msg) from e

    stderr = result.stderr.decode("utf-8", errors="replace")
    if "error" in stderr.lower() and "verify" not in stderr.lower():
        # Log non-verification errors
        for line in stderr.split("\n"):
            if "error" in line.lower():
                logger.warning("pkcs11_stderr", line=line.strip())

    return _parse_http_response(result.stdout)


def _parse_http_response(raw: bytes) -> SOAPResponse:
    """Parse raw HTTP response bytes into a SOAPResponse."""
    if not raw:
        return SOAPResponse(status_code=0, body=b"")

    # Split headers and body
    # Handle both \r\n\r\n and \n\n
    header_end = raw.find(b"\r\n\r\n")
    if header_end >= 0:
        header_bytes = raw[:header_end]
        body = raw[header_end + 4:]
    else:
        header_end = raw.find(b"\n\n")
        if header_end >= 0:
            header_bytes = raw[:header_end]
            body = raw[header_end + 2:]
        else:
            # No header/body split found — treat entire thing as body
            return SOAPResponse(status_code=0, body=raw)

    header_text = header_bytes.decode("utf-8", errors="replace")
    lines = header_text.split("\r\n") if "\r\n" in header_text else header_text.split("\n")

    # Parse status line
    status_code = 0
    if lines:
        status_match = re.match(r"HTTP/[\d.]+ (\d+)", lines[0])
        if status_match:
            status_code = int(status_match.group(1))

    # Parse headers
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()

    is_multipart = "multipart" in headers.get("content-type", "").lower()

    # Handle chunked transfer encoding
    if headers.get("transfer-encoding", "").lower() == "chunked":
        body = _decode_chunked(body)

    return SOAPResponse(
        status_code=status_code,
        headers=headers,
        body=body,
        is_multipart=is_multipart,
    )


def _decode_chunked(data: bytes) -> bytes:
    """Decode HTTP chunked transfer encoding."""
    result = bytearray()
    pos = 0
    while pos < len(data):
        # Find chunk size line
        line_end = data.find(b"\r\n", pos)
        if line_end < 0:
            break
        size_str = data[pos:line_end].decode("ascii", errors="replace").strip()
        if not size_str:
            pos = line_end + 2
            continue
        try:
            chunk_size = int(size_str.split(";")[0], 16)
        except ValueError:
            break
        if chunk_size == 0:
            break
        chunk_start = line_end + 2
        chunk_end = chunk_start + chunk_size
        result.extend(data[chunk_start:chunk_end])
        pos = chunk_end + 2  # Skip trailing \r\n
    return bytes(result)


def extract_soap_body(response: SOAPResponse) -> bytes:
    """Extract the SOAP XML body from a response, handling MTOM multipart."""
    if not response.is_multipart:
        return response.body

    # For MTOM responses, extract the XML part from the multipart message
    content_type = response.headers.get("content-type", "")
    boundary_match = re.search(r'boundary="?([^";]+)"?', content_type)
    if not boundary_match:
        return response.body

    boundary = boundary_match.group(1).encode()
    parts = response.body.split(b"--" + boundary)

    for part in parts:
        if b"text/xml" in part or b"application/xop+xml" in part:
            # Find the XML content after headers
            xml_start = part.find(b"<?xml")
            if xml_start < 0:
                xml_start = part.find(b"<soap:")
            if xml_start < 0:
                xml_start = part.find(b"<S:")
            if xml_start >= 0:
                # Find end (before next boundary marker or end of part)
                return part[xml_start:].rstrip(b"\r\n- ")

    return response.body
