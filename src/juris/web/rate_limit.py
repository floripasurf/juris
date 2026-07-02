"""Rate limiter for the web API — process-local by default, Redis-backed for SaaS.

Protects the SaaS surface from accidental or scripted bursts per API key. Behind
multiple workers the counter MUST be shared (Redis) or enforced at the proxy, or the
effective limit becomes ``N_workers × limit``; use :func:`build_rate_limiter` with a
``redis_url`` for that. Both limiters share the :class:`RateLimiter` interface.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0


class RateLimiter(Protocol):
    """The limiter interface the web middleware depends on (in-memory or Redis)."""

    @property
    def enabled(self) -> bool: ...

    def check(self, key: str, *, now: float | None = None) -> RateLimitDecision: ...


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


class RedisFixedWindowRateLimiter:
    """Fixed-window limiter whose counter is SHARED across workers/instances via Redis.

    Uses an atomic INCR + EXPIRE on a per-(key, window) counter, so N workers enforce ONE
    global quota (unlike the process-local limiter). ``client`` is any object exposing
    redis-py's ``incr``/``expire``. If Redis is unreachable it fails OPEN (does not block
    the API on a limiter outage) — the proxy/WAF remains the hard backstop.
    """

    def __init__(
        self, client: Any, *, limit: int, window_seconds: int = 60, prefix: str = "juris:rl:"
    ) -> None:
        self._client = client
        self._limit = limit
        self._window_seconds = window_seconds
        self._prefix = prefix

    @property
    def enabled(self) -> bool:
        return self._limit > 0

    def check(self, key: str, *, now: float | None = None) -> RateLimitDecision:
        if not self.enabled:
            return RateLimitDecision(True)
        current = int(now if now is not None else time.time())
        window_start = current - (current % self._window_seconds)
        redis_key = f"{self._prefix}{key}:{window_start}"
        try:
            count = int(self._client.incr(redis_key))
            if count == 1:
                self._client.expire(redis_key, self._window_seconds)
        except Exception:  # noqa: BLE001 — Redis outage must not take the API down
            from juris.core.observability import get_logger

            get_logger(__name__).warning("rate_limit_redis_unavailable")
            return RateLimitDecision(True)  # fail open
        if count > self._limit:
            retry_after = max(1, window_start + self._window_seconds - current)
            return RateLimitDecision(False, retry_after)
        return RateLimitDecision(True)


def build_rate_limiter(
    *,
    limit: int,
    window_seconds: int = 60,
    redis_url: str | None = None,
    prefix: str = "juris:rl:",
) -> RateLimiter:
    """Pick the shared Redis limiter when ``redis_url`` is set, else the process-local one."""
    if redis_url:
        import redis

        client = redis.Redis.from_url(redis_url)
        return RedisFixedWindowRateLimiter(
            client,
            limit=limit,
            window_seconds=window_seconds,
            prefix=prefix,
        )
    return FixedWindowRateLimiter(limit=limit, window_seconds=window_seconds)
