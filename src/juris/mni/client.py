"""Cached SOAP client factory for MNI endpoints."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Any

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


class _ServiceProxyWrapper:
    """Wraps a zeep ServiceProxy so it can be used like a Client.

    Operations code calls `client.service.consultarProcesso(...)`.
    A regular Client has `.service`, but `create_service()` returns a
    ServiceProxy where you call operations directly. This wrapper makes
    both cases work uniformly.
    """

    def __init__(self, proxy: Any) -> None:
        self._proxy = proxy

    @property
    def service(self) -> Any:
        return self._proxy


@lru_cache(maxsize=64)
def _create_client(
    wsdl_url: str,
    cert_path: str | None,
    cert_password: str | None,
    service_url_override: str | None = None,
) -> Any:
    """Create and cache a zeep Client for a given WSDL endpoint."""
    session = Session()

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

    logger.info("creating_soap_client", wsdl_url=wsdl_url, override=service_url_override)
    client = Client(wsdl=wsdl_url, transport=transport, settings=_ZEEP_SETTINGS)

    if service_url_override:
        binding_name = str(list(client.wsdl.bindings.keys())[0])
        proxy = client.create_service(binding_name, service_url_override)
        return _ServiceProxyWrapper(proxy)

    return client


def get_mni_client(tribunal_id: str, auth: AuthStrategy) -> Any:
    """Get a cached MNI SOAP client for a tribunal with the given auth strategy.

    Args:
        tribunal_id: Tribunal identifier (e.g., 'trt2', 'trf3', 'tjmg').
        auth: Authentication strategy (certificate or password).

    Returns:
        Object with `.service` attribute for SOAP operations.
    """
    tribunal = get_tribunal(tribunal_id)

    from juris.mni.auth import CertificateAuth

    if isinstance(auth, CertificateAuth):
        return _create_client(
            tribunal.wsdl_url, auth.cert_path, auth.cert_password,
            tribunal.service_url_override,
        )
    return _create_client(tribunal.wsdl_url, None, None, tribunal.service_url_override)
