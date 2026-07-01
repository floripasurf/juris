"""Tests for the Chrome Native Messaging host framing (ADR-0018 bridge)."""

from __future__ import annotations

import io
import json
import struct

import pytest

from juris.api.native_host import HOST_NAME, NativeMessagingRelay, install_native_host, read_message, write_message


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


def test_read_rejects_oversized_frame() -> None:
    frame = struct.pack("<I", 10)

    with pytest.raises(ValueError, match="excede"):
        read_message(io.BytesIO(frame), max_bytes=1)


def test_write_rejects_oversized_message() -> None:
    with pytest.raises(ValueError, match="excede"):
        write_message(io.BytesIO(), {"content": "grande"}, max_bytes=4)


def test_read_rejects_non_object_json() -> None:
    buffer = io.BytesIO()
    raw = b'["not", "object"]'
    buffer.write(struct.pack("<I", len(raw)))
    buffer.write(raw)
    buffer.seek(0)

    with pytest.raises(ValueError, match="objeto JSON"):
        read_message(buffer)


@pytest.mark.asyncio
async def test_relay_writes_request_and_reads_reply() -> None:
    stdin = io.BytesIO()
    write_message(stdin, {"request_id": "r1", "success": True, "content": "resposta", "error": None})
    stdin.seek(0)
    stdout = io.BytesIO()
    relay = NativeMessagingRelay(stdin=stdin, stdout=stdout)

    result = await relay.request({"request_id": "r1", "prompt": "tese"})

    assert result["content"] == "resposta"
    stdout.seek(0)
    assert read_message(stdout) == {"request_id": "r1", "prompt": "tese"}


@pytest.mark.asyncio
async def test_relay_returns_failure_on_malformed_extension_reply() -> None:
    stdin = io.BytesIO()
    raw = b"not-json"
    stdin.write(struct.pack("<I", len(raw)))
    stdin.write(raw)
    stdin.seek(0)
    relay = NativeMessagingRelay(stdin=stdin, stdout=io.BytesIO())

    result = await relay.request({"request_id": "r1", "prompt": "tese"})

    assert result["request_id"] == "r1"
    assert result["success"] is False
    assert "resposta inválida" in result["error"]


@pytest.mark.asyncio
async def test_relay_returns_failure_when_extension_closes() -> None:
    relay = NativeMessagingRelay(stdin=io.BytesIO(b""), stdout=io.BytesIO())

    result = await relay.request({"request_id": "r1", "prompt": "tese"})

    assert result == {
        "request_id": "r1",
        "success": False,
        "content": None,
        "error": "extensão encerrou o canal nativo",
    }


def test_install_native_host_writes_manifest_and_launcher(tmp_path) -> None:
    installation = install_native_host(
        extension_id="abcdefghijklmnopabcdefghijklmnop",
        install_root=tmp_path / "install",
        manifest_dir=tmp_path / "manifests",
        python_executable="/opt/juris/python",
        ws_port=9191,
    )

    manifest = json.loads(installation.manifest_path.read_text(encoding="utf-8"))
    assert manifest["name"] == HOST_NAME
    assert manifest["path"] == str(installation.launcher_path)
    assert manifest["allowed_origins"] == ["chrome-extension://abcdefghijklmnopabcdefghijklmnop/"]
    assert installation.bridge_url == "ws://127.0.0.1:9191"
    launcher = installation.launcher_path.read_text(encoding="utf-8")
    assert "/opt/juris/python" in launcher
    assert "juris.api.native_host serve-ws" in launcher


def test_install_native_host_rejects_placeholder_extension_id(tmp_path) -> None:
    with pytest.raises(ValueError, match="extension_id obrigatório"):
        install_native_host(
            extension_id="REPLACE_WITH_EXTENSION_ID",
            install_root=tmp_path / "install",
            manifest_dir=tmp_path / "manifests",
        )
