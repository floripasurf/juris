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

import json
import struct
import sys
from typing import IO, Any

_LEN = struct.Struct("<I")  # Chrome uses a 4-byte little-endian length prefix


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
