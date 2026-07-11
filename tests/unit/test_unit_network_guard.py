"""Unit tests must not perform real external network I/O."""

from __future__ import annotations

import socket

import pytest


def test_unit_tests_block_external_socket_connect() -> None:
    sock = socket.socket()
    try:
        with pytest.raises(RuntimeError, match="External network disabled"):
            sock.connect(("198.51.100.1", 443))
    finally:
        sock.close()
