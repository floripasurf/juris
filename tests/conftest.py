"""Shared test fixtures."""

import importlib
import os
import signal
import socket
from pathlib import Path
from typing import Any

import pytest

_REAL_SOCKET = socket.socket


def _is_unit_test(request: pytest.FixtureRequest) -> bool:
    parts = set(Path(str(request.node.path)).parts)
    return "tests" in parts and "unit" in parts


def _network_allowed(request: pytest.FixtureRequest) -> bool:
    if not _is_unit_test(request):
        return True
    if request.node.get_closest_marker("live") is not None:
        return True
    return os.environ.get("JURIS_ALLOW_NETWORK_TESTS", "").strip().lower() in {"1", "true", "yes"}


def _assert_loopback(address: Any) -> None:
    if isinstance(address, str):  # AF_UNIX path
        return
    host = address[0] if isinstance(address, tuple) and address else ""
    if host in {"", "localhost", "127.0.0.1", "::1"}:
        return
    if isinstance(host, str) and (host.startswith("127.") or host == "::"):
        return
    msg = f"External network disabled in unit tests: attempted connect to {host!r}"
    raise RuntimeError(msg)


def _clear_if_cached(fn: Any) -> None:
    cache_clear = getattr(fn, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()


@pytest.fixture(autouse=True)
def _clear_process_wide_caches():
    """Reset process-wide config/routing caches so env and rate buckets don't leak
    between tests."""
    from juris import config
    from juris.api.agent_config import _load_agent_bindings

    web_app = importlib.import_module("juris.web.app")

    _clear_if_cached(_load_agent_bindings)
    config._settings = None  # noqa: SLF001 - test isolation for Settings singleton
    _clear_if_cached(web_app._api_rate_limiter)
    _clear_if_cached(web_app._api_expensive_rate_limiter)
    _clear_if_cached(web_app._ws_agent_relay_rate_limiter)
    yield
    _clear_if_cached(_load_agent_bindings)
    config._settings = None  # noqa: SLF001 - test isolation for Settings singleton
    _clear_if_cached(web_app._api_rate_limiter)
    _clear_if_cached(web_app._api_expensive_rate_limiter)
    _clear_if_cached(web_app._ws_agent_relay_rate_limiter)


@pytest.fixture(autouse=True)
def _block_external_network_in_unit_tests(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Fail fast if a unit test tries to use real external network.

    Loopback remains allowed because FastAPI/TestClient and local service probes
    are legitimate unit-test dependencies. Mark a test ``live`` or set
    ``JURIS_ALLOW_NETWORK_TESTS=1`` for intentional external I/O.
    """
    if _network_allowed(request):
        yield
        return

    class GuardedSocket(_REAL_SOCKET):
        def connect(self, address: Any) -> None:  # noqa: ANN401 - socket API accepts many shapes
            _assert_loopback(address)
            return super().connect(address)

        def connect_ex(self, address: Any) -> int:  # noqa: ANN401 - socket API accepts many shapes
            _assert_loopback(address)
            return super().connect_ex(address)

    monkeypatch.setattr(socket, "socket", GuardedSocket)
    yield


@pytest.fixture(autouse=True)
def _unit_test_timeout(request: pytest.FixtureRequest):
    """Dump/fail individual unit tests that hang indefinitely."""
    if not _is_unit_test(request) or request.node.get_closest_marker("slow") is not None:
        yield
        return
    if not hasattr(signal, "setitimer") or not hasattr(signal, "SIGALRM"):
        yield
        return
    timeout = int(os.environ.get("JURIS_UNIT_TEST_TIMEOUT_SECONDS", "120"))
    previous_handler = signal.getsignal(signal.SIGALRM)

    def _handler(_signum: int, _frame: object) -> None:
        pytest.fail(f"unit test timed out after {timeout}s", pytrace=False)

    signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
