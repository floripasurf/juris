"""Small redaction helpers for logs and operator-facing diagnostics."""

from __future__ import annotations

import re

from juris.core.deid import iter_structured_pii

_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(token|pin|senha|password|secret|api[_-]?key|authorization)\s*=\s*[^\s,;)&]+"
)
_AUTH_HEADER_RE = re.compile(
    r"(?i)\b(authorization|x-api-key|x-agent-token)\s*:\s*(?:bearer\s+)?[^\s,;)&]+"
)
_URL_CREDENTIALS_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+(?::[^/\s@]*)?@")
_LOCAL_PATH_RE = re.compile(
    r"(?:(?<=\s)|^)(?:~|/Users|/var|/private|/tmp|/Volumes|/Library|/System)(?:/[^\s,;)]+)+"
)


def _redact_structured_pii(text: str) -> str:
    replacements = sorted(set(iter_structured_pii(text)), key=lambda item: len(item[1]), reverse=True)
    for label, value in replacements:
        text = text.replace(value, f"<{label.lower()}>")
    return text


def safe_error_text(value: object) -> str:
    """Return diagnostic text safe enough for app/agent logs.

    This is intentionally conservative: logs should preserve the failure class and
    broad cause, not local paths, CPF, tokens, PINs or credentialed URLs.
    """
    text = (
        (str(value) or value.__class__.__name__)
        if isinstance(value, BaseException)
        else str(value or "")
    )
    text = _AUTH_HEADER_RE.sub(lambda match: f"{match.group(1)}: <redacted>", text)
    text = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted>", text)
    text = _URL_CREDENTIALS_RE.sub(r"\1<redacted>@", text)
    text = _redact_structured_pii(text)
    return _LOCAL_PATH_RE.sub("<local-path>", text)
