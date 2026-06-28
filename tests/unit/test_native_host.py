"""Tests for the Chrome Native Messaging host framing (ADR-0018 bridge)."""

from __future__ import annotations

import io
import json
import struct

from juris.api.native_host import read_message, write_message


def test_write_then_read_round_trips() -> None:
    buffer = io.BytesIO()
    write_message(buffer, {"type": "completion", "content": "olá"})
    buffer.seek(0)
    assert read_message(buffer) == {"type": "completion", "content": "olá"}


def test_write_uses_chrome_length_prefix() -> None:
    buffer = io.BytesIO()
    write_message(buffer, {"a": 1})
    raw = buffer.getvalue()
    length = struct.unpack("<I", raw[:4])[0]  # 4-byte little-endian length prefix
    assert length == len(raw) - 4
    assert json.loads(raw[4:]) == {"a": 1}


def test_read_returns_none_at_eof() -> None:
    assert read_message(io.BytesIO(b"")) is None
