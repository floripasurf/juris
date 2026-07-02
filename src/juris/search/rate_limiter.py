"""Per-court async rate limiter with cross-invocation persistence."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from pathlib import Path

from juris.core.paths import ensure_private_dir, juris_home, restrict_file
from juris.core.sanitize import safe_error_text

logger = logging.getLogger(__name__)


def default_state_file() -> Path:
    """Default persisted rate-limit state path."""
    return juris_home() / "rate_limits.json"


class CourtRateLimiter:
    def __init__(
        self,
        default_interval: float = 2.0,
        court_intervals: dict[str, float] | None = None,
        state_file: Path | None = None,
    ) -> None:
        self._default_interval = default_interval
        self._court_intervals = court_intervals or {}
        self._uses_default_state_file = state_file is None
        self._state_file = state_file or default_state_file()
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_request = self._load_state()

    def get_interval(self, court: str) -> float:
        return self._court_intervals.get(court, self._default_interval)

    def _get_lock(self, court: str) -> asyncio.Lock:
        if court not in self._locks:
            self._locks[court] = asyncio.Lock()
        return self._locks[court]

    def _load_state(self) -> dict[str, float]:
        if self._state_file.exists():
            try:
                restrict_file(self._state_file)
                raw = json.loads(self._state_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
            if isinstance(raw, dict):
                parsed: dict[str, float] = {}
                for key, value in raw.items():
                    try:
                        timestamp = float(value)
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(timestamp) and timestamp >= 0:
                        parsed[str(key)] = timestamp
                return parsed
        return {}

    def _save_state(self) -> None:
        try:
            ensure_private_dir(self._state_file.parent, restrict_existing=self._uses_default_state_file)
            tmp = self._state_file.with_suffix(f"{self._state_file.suffix}.tmp")
            tmp.write_text(json.dumps(self._last_request), encoding="utf-8")
            restrict_file(tmp)
            tmp.replace(self._state_file)
            restrict_file(self._state_file)
        except OSError as exc:
            logger.debug("Failed to persist rate limit state: %s", safe_error_text(exc))

    async def acquire(self, court: str) -> None:
        lock = self._get_lock(court)
        async with lock:
            now = time.time()
            last = self._last_request.get(court, 0.0)
            interval = self.get_interval(court)
            wait = interval - (now - last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request[court] = time.time()
            self._save_state()
