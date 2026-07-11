"""Client IP extraction for rate limits behind an explicitly trusted proxy."""

from __future__ import annotations

import ipaddress

from starlette.requests import HTTPConnection


def _valid_ip(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return None
    return candidate


def _connection_host(conn: HTTPConnection) -> str:
    if conn.client is None:
        return "unknown"
    return conn.client.host


def client_ip(conn: HTTPConnection, *, trusted_proxy: bool = False) -> str:
    """Return the effective client IP for abuse buckets.

    Proxy headers are spoofable when the app is directly exposed, so they are
    ignored unless the deployment opts in with ``JURIS_TRUSTED_PROXY=1``.
    """
    fallback = _connection_host(conn)
    if not trusted_proxy:
        return fallback

    cf_ip = _valid_ip(conn.headers.get("cf-connecting-ip"))
    if cf_ip is not None:
        return cf_ip

    xff = conn.headers.get("x-forwarded-for", "")
    first_forwarded = xff.split(",", 1)[0]
    forwarded_ip = _valid_ip(first_forwarded)
    return forwarded_ip or fallback
