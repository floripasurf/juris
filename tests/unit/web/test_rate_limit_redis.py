"""Redis-backed rate limiter shares one quota across workers (distributed)."""

from __future__ import annotations

from juris.web.rate_limit import RedisFixedWindowRateLimiter, build_rate_limiter


class _FakeRedis:
    """Minimal INCR/EXPIRE double — mimics Redis semantics without a server."""

    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def expire(self, key: str, seconds: int) -> None:
        self.expiries[key] = seconds


def test_redis_limiter_shares_one_counter_across_instances() -> None:
    # Two limiter instances (simulating two workers) over ONE Redis → ONE global quota.
    fake = _FakeRedis()
    w1 = RedisFixedWindowRateLimiter(fake, limit=3, window_seconds=60)
    w2 = RedisFixedWindowRateLimiter(fake, limit=3, window_seconds=60)

    assert w1.check("k", now=100).allowed is True  # 1
    assert w2.check("k", now=100).allowed is True  # 2 (other worker, same counter)
    assert w1.check("k", now=100).allowed is True  # 3
    blocked = w2.check("k", now=100)  # 4 > limit → blocked GLOBALLY
    assert blocked.allowed is False
    assert blocked.retry_after_seconds > 0
    assert fake.expiries  # TTL set on the window key


def test_redis_limiter_new_window_resets() -> None:
    fake = _FakeRedis()
    limiter = RedisFixedWindowRateLimiter(fake, limit=1, window_seconds=60)
    assert limiter.check("k", now=100).allowed is True
    assert limiter.check("k", now=100).allowed is False  # same window, over limit
    assert limiter.check("k", now=200).allowed is True  # next window → fresh counter


def test_redis_limiter_fails_open_on_outage() -> None:
    class _BrokenRedis:
        def incr(self, key: str) -> int:
            raise ConnectionError("redis down")

    limiter = RedisFixedWindowRateLimiter(_BrokenRedis(), limit=1, window_seconds=60)
    # A Redis outage must not block the API (proxy/WAF is the hard backstop).
    assert limiter.check("k", now=100).allowed is True


def test_build_rate_limiter_picks_backend() -> None:
    from juris.web.rate_limit import FixedWindowRateLimiter

    assert isinstance(build_rate_limiter(limit=5), FixedWindowRateLimiter)  # no redis_url → local


def test_redis_limiter_prefix_separates_buckets() -> None:
    fake = _FakeRedis()
    standard = RedisFixedWindowRateLimiter(fake, limit=1, window_seconds=60, prefix="juris:rl:api:")
    expensive = RedisFixedWindowRateLimiter(
        fake, limit=1, window_seconds=60, prefix="juris:rl:api-expensive:"
    )
    relay = RedisFixedWindowRateLimiter(fake, limit=1, window_seconds=60, prefix="juris:rl:ws-agent-relay:")

    assert standard.check("tenant:a", now=100).allowed is True
    assert expensive.check("tenant:a", now=100).allowed is True
    assert relay.check("tenant:a:host:127.0.0.1", now=100).allowed is True
    assert standard.check("tenant:a", now=100).allowed is False
    assert expensive.check("tenant:a", now=100).allowed is False
    assert relay.check("tenant:a:host:127.0.0.1", now=100).allowed is False
    assert len(fake.store) == 3
