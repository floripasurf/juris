from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from juris.search.rate_limiter import CourtRateLimiter


@pytest.mark.asyncio
class TestCourtRateLimiter:
    async def test_first_request_immediate(self, tmp_path: Path) -> None:
        limiter = CourtRateLimiter(default_interval=2.0, state_file=tmp_path / "rates.json")
        start = time.monotonic()
        await limiter.acquire("stf")
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    async def test_second_request_waits(self, tmp_path: Path) -> None:
        limiter = CourtRateLimiter(default_interval=0.2, state_file=tmp_path / "rates.json")
        await limiter.acquire("stf")
        start = time.monotonic()
        await limiter.acquire("stf")
        elapsed = time.monotonic() - start
        assert elapsed >= 0.15

    async def test_different_courts_independent(self, tmp_path: Path) -> None:
        limiter = CourtRateLimiter(default_interval=1.0, state_file=tmp_path / "rates.json")
        await limiter.acquire("stf")
        start = time.monotonic()
        await limiter.acquire("stj")
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    async def test_persists_to_file(self, tmp_path: Path) -> None:
        state_file = tmp_path / "rates.json"
        limiter = CourtRateLimiter(default_interval=2.0, state_file=state_file)
        await limiter.acquire("stf")
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert "stf" in data

    async def test_loads_existing_state(self, tmp_path: Path) -> None:
        state_file = tmp_path / "rates.json"
        recent_ts = time.time()
        state_file.write_text(json.dumps({"stf": recent_ts}))
        limiter = CourtRateLimiter(default_interval=2.0, state_file=state_file)
        start = time.monotonic()
        await limiter.acquire("stf")
        elapsed = time.monotonic() - start
        assert elapsed >= 1.5

    async def test_custom_interval_per_court(self, tmp_path: Path) -> None:
        limiter = CourtRateLimiter(
            default_interval=2.0,
            court_intervals={"trf5": 5.0},
            state_file=tmp_path / "rates.json",
        )
        assert limiter.get_interval("trf5") == 5.0
        assert limiter.get_interval("stf") == 2.0
