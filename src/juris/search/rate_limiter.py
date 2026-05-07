"""Per-court async rate limiter with cross-invocation persistence."""
from __future__ import annotations
import asyncio
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)
_DEFAULT_STATE_FILE = Path.home() / ".juris" / "rate_limits.json"


class CourtRateLimiter:
    def __init__(
        self,
        default_interval: float = 2.0,
        court_intervals: dict[str, float] | None = None,
        state_file: Path | None = None,
    ) -> None:
        self._default_interval = default_interval
        self._court_intervals = court_intervals or {}
        self._state_file = state_file or _DEFAULT_STATE_FILE
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
                return json.loads(self._state_file.read_text())
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_state(self) -> None:
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(json.dumps(self._last_request))
        except OSError:
            logger.debug("Failed to persist rate limit state", exc_info=True)

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
