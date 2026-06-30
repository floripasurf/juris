"""Chrome Native Messaging host — the OS bridge for the browser session (ADR-0018).

Chrome launches this host and speaks the Native Messaging wire format over
stdin/stdout: each message is a 4-byte little-endian length prefix followed by
UTF-8 JSON. The host relays those messages to/from the juris local agent (a
localhost WS), so the cloud → local-agent → host → extension → Claude.ai chain is
complete.

The framing (the testable core) lives here; the extension content script (DOM
automation of the chat UI) is the JS half — see docs/browser-extension/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

_LEN = struct.Struct("<I")  # Chrome uses a 4-byte little-endian length prefix
HOST_NAME = "com.juris.host"
DEFAULT_WS_HOST = "127.0.0.1"
DEFAULT_WS_PORT = 8787


def read_message(stream: IO[bytes]) -> dict[str, Any] | None:
    """Read one Native Messaging frame; return None at EOF."""
    header = stream.read(4)
    if len(header) < 4:
        return None
    (length,) = _LEN.unpack(header)
    body = stream.read(length)
    if len(body) < length:
        return None
    parsed: dict[str, Any] = json.loads(body.decode("utf-8"))
    return parsed


def write_message(stream: IO[bytes], message: dict[str, Any]) -> None:
    """Write one Native Messaging frame (length prefix + JSON)."""
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    stream.write(_LEN.pack(len(body)))
    stream.write(body)
    stream.flush()


def serve(handler: Any, *, stdin: IO[bytes] | None = None, stdout: IO[bytes] | None = None) -> None:
    """Read messages from Chrome and write each ``handler(msg)`` reply back.

    ``handler`` maps a request dict to a response dict (e.g. relays to the juris
    local agent). Loops until Chrome closes stdin (EOF).
    """
    rx = stdin or sys.stdin.buffer
    tx = stdout or sys.stdout.buffer
    while True:
        request = read_message(rx)
        if request is None:
            return
        write_message(tx, handler(request))


def _failure(request: dict[str, Any], error: str) -> dict[str, Any]:
    request_id = str(request.get("request_id") or "")
    return {"request_id": request_id, "success": False, "content": None, "error": error}


class NativeMessagingRelay:
    """Relay one WS request through Chrome Native Messaging and await its reply."""

    def __init__(
        self,
        *,
        stdin: IO[bytes] | None = None,
        stdout: IO[bytes] | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._stdin = stdin or sys.stdin.buffer
        self._stdout = stdout or sys.stdout.buffer
        self._timeout = timeout
        self._lock = asyncio.Lock()

    async def request(self, message: dict[str, Any]) -> dict[str, Any]:
        """Send ``message`` to the extension and return its CompletionResponse.

        Native Messaging is a single stdio pipe. Serialize calls so concurrent
        WS clients cannot interleave frames or steal each other's replies.
        """
        async with self._lock:
            await asyncio.to_thread(write_message, self._stdout, message)
            try:
                reply = await asyncio.wait_for(
                    asyncio.to_thread(read_message, self._stdin),
                    timeout=self._timeout,
                )
            except TimeoutError:
                return _failure(message, "timeout aguardando resposta da extensão")
            if reply is None:
                return _failure(message, "extensão encerrou o canal nativo")
            return reply


async def run_websocket_bridge(
    *,
    host: str = DEFAULT_WS_HOST,
    port: int = DEFAULT_WS_PORT,
    relay: NativeMessagingRelay | None = None,
) -> None:
    """Expose the Native Messaging pipe as the localhost WS bridge used by juris."""
    import websockets

    bridge = relay or NativeMessagingRelay()

    async def _handle(websocket: Any) -> None:
        raw = await websocket.recv()
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            await websocket.send(
                json.dumps(
                    {"request_id": "", "success": False, "content": None, "error": "JSON inválido no bridge"},
                    ensure_ascii=False,
                )
            )
            return
        reply = await bridge.request(message)
        await websocket.send(json.dumps(reply, ensure_ascii=False))

    async with websockets.serve(_handle, host, port):
        await asyncio.Future()


def _native_hosts_dir(browser: str = "chrome") -> Path:
    system = platform.system()
    home = Path.home()
    browser_key = browser.lower()
    if system == "Darwin":
        bases = {
            "chrome": home / "Library/Application Support/Google/Chrome",
            "chromium": home / "Library/Application Support/Chromium",
            "brave": home / "Library/Application Support/BraveSoftware/Brave-Browser",
            "edge": home / "Library/Application Support/Microsoft Edge",
        }
    elif system == "Linux":
        bases = {
            "chrome": home / ".config/google-chrome",
            "chromium": home / ".config/chromium",
            "brave": home / ".config/BraveSoftware/Brave-Browser",
            "edge": home / ".config/microsoft-edge",
        }
    else:
        msg = f"instalação automática do Native Messaging não suportada em {system}"
        raise RuntimeError(msg)
    try:
        return bases[browser_key] / "NativeMessagingHosts"
    except KeyError as exc:
        supported = ", ".join(sorted(bases))
        msg = f"navegador não suportado: {browser}. Use um de: {supported}"
        raise RuntimeError(msg) from exc


def default_manifest_path(browser: str = "chrome") -> Path:
    """Default per-user Chrome Native Messaging manifest path."""
    return _native_hosts_dir(browser) / f"{HOST_NAME}.json"


@dataclass(frozen=True)
class NativeHostInstallation:
    launcher_path: Path
    manifest_path: Path
    bridge_url: str


def _launcher_content(*, python_executable: str, ws_host: str, ws_port: int) -> str:
    return "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            f'exec "{python_executable}" -m juris.api.native_host serve-ws --host "{ws_host}" --port "{ws_port}"',
            "",
        ]
    )


def install_native_host(
    *,
    extension_id: str,
    browser: str = "chrome",
    install_root: Path | None = None,
    manifest_dir: Path | None = None,
    python_executable: str | None = None,
    ws_host: str = DEFAULT_WS_HOST,
    ws_port: int = DEFAULT_WS_PORT,
) -> NativeHostInstallation:
    """Install a per-user Chrome Native Messaging host manifest + launcher."""
    if not extension_id or extension_id == "REPLACE_WITH_EXTENSION_ID":
        msg = "extension_id obrigatório: copie o id em chrome://extensions após carregar a extensão"
        raise ValueError(msg)

    root = install_root or (Path.home() / ".juris" / "browser-session")
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher_path = bin_dir / "juris-native-host"
    launcher_path.write_text(
        _launcher_content(
            python_executable=python_executable or sys.executable,
            ws_host=ws_host,
            ws_port=ws_port,
        ),
        encoding="utf-8",
    )
    launcher_path.chmod(0o700)

    target_manifest_dir = manifest_dir or _native_hosts_dir(browser)
    target_manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = target_manifest_dir / f"{HOST_NAME}.json"
    manifest = {
        "name": HOST_NAME,
        "description": "Juris native messaging host — relays completions to the juris local agent",
        "path": str(launcher_path),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{extension_id}/"],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return NativeHostInstallation(
        launcher_path=launcher_path,
        manifest_path=manifest_path,
        bridge_url=f"ws://{ws_host}:{ws_port}",
    )


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Juris Chrome Native Messaging host")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve_ws = sub.add_parser("serve-ws", help="Run the WS <-> Native Messaging bridge")
    serve_ws.add_argument("--host", default=DEFAULT_WS_HOST)
    serve_ws.add_argument("--port", type=int, default=DEFAULT_WS_PORT)
    args = parser.parse_args(argv)
    if args.cmd == "serve-ws":
        asyncio.run(run_websocket_bridge(host=args.host, port=args.port))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
