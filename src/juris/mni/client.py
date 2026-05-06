"""Cached SOAP client factory for MNI endpoints."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from requests import Session
from zeep import Client, Settings
from zeep.transports import Transport

from juris.core.observability import get_logger
from juris.mni.tribunais import get_tribunal

if TYPE_CHECKING:
    from juris.mni.auth import AuthStrategy

logger = get_logger(__name__)

# Zeep settings: lenient parsing for varied tribunal implementations
_ZEEP_SETTINGS = Settings(strict=False, xml_huge_tree=True)

# Timeouts
_CONNECT_TIMEOUT = 60  # seconds
_OPERATION_TIMEOUT = 120  # seconds


@lru_cache(maxsize=64)
def _create_client(wsdl_url: str, cert_path: str | None, cert_password: str | None) -> Client:
    """Create and cache a zeep Client for a given WSDL endpoint.

    Cache key includes cert_path to support multiple auth strategies.
    """
    session = Session()

    # If cert-based auth, mount the PKCS#12 adapter
    if cert_path and cert_password:
        from requests_pkcs12 import Pkcs12Adapter

        session.mount(
            "https://",
            Pkcs12Adapter(pkcs12_filename=cert_path, pkcs12_password=cert_password),
        )

    transport = Transport(
        session=session,
        timeout=_CONNECT_TIMEOUT,
        operation_timeout=_OPERATION_TIMEOUT,
    )

    logger.info("creating_soap_client", wsdl_url=wsdl_url)
    return Client(wsdl=wsdl_url, transport=transport, settings=_ZEEP_SETTINGS)


def get_mni_client(tribunal_id: str, auth: AuthStrategy) -> Client:
    """Get a cached MNI SOAP client for a tribunal with the given auth strategy.

    Args:
        tribunal_id: Tribunal identifier (e.g., 'trt2', 'trf3').
        auth: Authentication strategy (certificate or password).

    Returns:
        Configured zeep Client ready for SOAP operations.
    """
    tribunal = get_tribunal(tribunal_id)

    # For cert auth, pass cert details for caching; for password auth, no cert
    from juris.mni.auth import CertificateAuth

    if isinstance(auth, CertificateAuth):
        return _create_client(tribunal.wsdl_url, auth.cert_path, auth.cert_password)
    return _create_client(tribunal.wsdl_url, None, None)
