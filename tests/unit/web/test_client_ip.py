"""Client-IP extraction behind trusted proxies."""

from __future__ import annotations

from starlette.requests import Request

from juris.web.client_ip import client_ip


def _request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": raw_headers,
            "client": ("127.0.0.1", 53100),
        }
    )


def test_client_ip_uses_cf_connecting_ip_when_proxy_trusted() -> None:
    request = _request({"CF-Connecting-IP": "203.0.113.9", "X-Forwarded-For": "198.51.100.7"})

    assert client_ip(request, trusted_proxy=True) == "203.0.113.9"


def test_client_ip_uses_first_x_forwarded_for_when_proxy_trusted() -> None:
    request = _request({"X-Forwarded-For": "198.51.100.7, 198.51.100.8"})

    assert client_ip(request, trusted_proxy=True) == "198.51.100.7"


def test_client_ip_ignores_forwarded_headers_without_trusted_proxy() -> None:
    request = _request({"CF-Connecting-IP": "203.0.113.9", "X-Forwarded-For": "198.51.100.7"})

    assert client_ip(request, trusted_proxy=False) == "127.0.0.1"


def test_client_ip_falls_back_on_invalid_forwarded_values() -> None:
    request = _request({"CF-Connecting-IP": "not-an-ip", "X-Forwarded-For": "bad, 198.51.100.8"})

    assert client_ip(request, trusted_proxy=True) == "127.0.0.1"
