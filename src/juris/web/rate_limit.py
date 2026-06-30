"""Small process-local rate limiter for the web API.

This is intentionally simple: it protects the pilot SaaS surface from accidental
or scripted bursts per API key. It is not a distributed quota system; production
behind multiple workers should also enforce limits at the reverse proxy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0


class FixedWindowRateLimiter:
    """Fixed-window limiter keyed by API key or public tenant marker."""

    def __init__(self, *, limit: int, window_seconds: int = 60) -> None:
        self._limit = limit
        self._window_seconds = window_seconds
        self._buckets: dict[str, tuple[int, int]] = {}
        self._lock = Lock()

    @property
    def enabled(self) -> bool:
        return self._limit > 0

    def check(self, key: str, *, now: float | None = None) -> RateLimitDecision:
        if not self.enabled:
            return RateLimitDecision(True)

        current = int(now if now is not None else time.time())
        window_start = current - (current % self._window_seconds)
        with self._lock:
            bucket_start, count = self._buckets.get(key, (window_start, 0))
            if bucket_start != window_start:
                bucket_start, count = window_start, 0
            if count >= self._limit:
                retry_after = max(1, bucket_start + self._window_seconds - current)
                return RateLimitDecision(False, retry_after)
            self._buckets[key] = (bucket_start, count + 1)
        return RateLimitDecision(True)
