"""Shared HTTP client factory for court portal adapters.

Brazilian court portals (.jus.br) commonly serve certificate chains
(ICP-Brasil and intermediates) that are present in the operating system
trust store but absent from the ``certifi`` bundle httpx uses by default.
Building the SSL context with :mod:`truststore` validates against the OS
trust store instead, which matches what browsers and ``curl`` do.
"""

from __future__ import annotations

import ssl

import httpx
import truststore

_ssl_context: ssl.SSLContext | None = None


def _get_ssl_context() -> ssl.SSLContext:
    """Return a process-wide SSL context backed by the OS trust store."""
    global _ssl_context  # noqa: PLW0603 — context creation is expensive; cache it
    if _ssl_context is None:
        _ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return _ssl_context


def make_portal_client(
    user_agent: str,
    *,
    timeout: float = 30.0,
    follow_redirects: bool = False,
) -> httpx.AsyncClient:
    """Create an :class:`httpx.AsyncClient` configured for .jus.br portals.

    Args:
        user_agent: User-Agent header identifying the tool.
        timeout: Request timeout in seconds.
        follow_redirects: Whether to follow HTTP redirects.

    Returns:
        An async client that validates TLS against the OS trust store.
    """
    return httpx.AsyncClient(
        headers={"User-Agent": user_agent},
        timeout=timeout,
        follow_redirects=follow_redirects,
        verify=_get_ssl_context(),
    )
