"""Tests for DataJud safety primitives: cache, rate limiting, audit, and batch guard."""

from __future__ import annotations

import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from juris.datajud.safety import (
    BatchGuardError,
    DataJudCache,
    DataJudRequestMeta,
    RateLimiter,
    audit_datajud_call,
    default_audit_path,
    default_cache_dir,
    ensure_batch_allowed,
)
from juris.persistence.audit import AuditLog


def _meta(
    *,
    cnj: str = "0001234-56.2026.8.13.0001",
    endpoint: str = "/api_publica_tjmg/_search",
    query_hash: str = "abc123",
) -> DataJudRequestMeta:
    return DataJudRequestMeta(
        cnj=cnj,
        tribunal="tjmg",
        endpoint=endpoint,
        query_hash=query_hash,
    )


class TestRateLimiter:
    def test_default_interval_is_one_second(self) -> None:
        limiter = RateLimiter()
        assert limiter.interval_seconds == 1.0

    def test_waits_for_remaining_interval(self) -> None:
        slept: list[float] = []
        clock_values = iter([10.0, 10.25, 11.0])

        limiter = RateLimiter(clock=lambda: next(clock_values), sleeper=slept.append)
        limiter.wait()
        limiter.wait()

        assert slept == [pytest.approx(0.75)]


class TestDataJudCache:
    def test_default_paths_honor_juris_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JURIS_HOME", str(tmp_path))

        assert default_cache_dir() == tmp_path / "cache" / "datajud"
        assert default_audit_path() == tmp_path / "audit.jsonl"

    def test_cache_roundtrip_uses_query_hash_key(self, tmp_path: Path) -> None:
        cache = DataJudCache(tmp_path)
        meta = _meta(query_hash="hash-one")
        payload = {"hits": {"hits": [{"_source": {"numeroProcesso": "x"}}]}}

        cache.set(meta, payload)

        assert cache.get(meta) == payload
        assert (tmp_path / "tjmg" / "hash-one.json").exists()

    def test_cache_files_are_private(self, tmp_path: Path) -> None:
        cache = DataJudCache(tmp_path)
        cache.set(_meta(query_hash="private"), {"ok": True})

        path = tmp_path / "tjmg" / "private.json"

        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_expired_cache_entry_is_ignored(self, tmp_path: Path) -> None:
        now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        cache = DataJudCache(tmp_path, now=lambda: now)
        meta = _meta()
        cache.set(meta, {"ok": True})

        later = DataJudCache(tmp_path, now=lambda: now + timedelta(hours=25))

        assert later.get(meta, ttl=timedelta(hours=24)) is None

    def test_purge_removes_cached_files(self, tmp_path: Path) -> None:
        cache = DataJudCache(tmp_path)
        cache.set(_meta(query_hash="one"), {"ok": 1})
        cache.set(_meta(query_hash="two"), {"ok": 2})

        removed = cache.purge()

        assert removed == 2
        assert not any(tmp_path.rglob("*.json"))


class TestAudit:
    def test_audit_datajud_call_records_cache_hit_and_call_metadata(self, tmp_path: Path) -> None:
        audit_path = tmp_path / "audit.jsonl"

        audit_datajud_call(
            AuditLog(audit_path),
            _meta(),
            cache_hit=True,
            status_code=200,
            duration_ms=12.5,
            result_count=1,
        )

        line = audit_path.read_text(encoding="utf-8").strip()
        entry = json.loads(line)
        assert entry["event_type"] == "datajud.request"
        assert entry["processo_cnj"] == "0001234-56.2026.8.13.0001"
        expected = {
            "tribunal": "tjmg",
            "endpoint": "/api_publica_tjmg/_search",
            "query_hash": "abc123",
            "cache_hit": True,
            "status_code": 200,
            "result_count": 1,
        }
        assert expected.items() <= entry["details"].items()
        assert entry["details"]["duration_ms"] == 12.5

    def test_audit_file_is_private(self, tmp_path: Path) -> None:
        audit_path = tmp_path / "audit.jsonl"

        audit_datajud_call(
            AuditLog(audit_path),
            _meta(),
            cache_hit=False,
            status_code=200,
            duration_ms=1.0,
        )

        assert stat.S_IMODE(audit_path.stat().st_mode) == 0o600


class TestBatchGuard:
    def test_small_batches_do_not_require_confirmation(self) -> None:
        plan = ensure_batch_allowed(cnj_count=9, confirm_batch=False, calls_per_cnj=1)

        assert plan.requires_confirmation is False
        assert plan.estimated_calls == 9

    def test_ten_or_more_cnjs_require_confirmation(self) -> None:
        with pytest.raises(BatchGuardError) as exc:
            ensure_batch_allowed(cnj_count=10, confirm_batch=False, calls_per_cnj=2)

        assert "10 CNJs" in str(exc.value)
        assert "20 chamadas" in str(exc.value)
        assert "--confirm-batch" in str(exc.value)

    def test_confirmed_large_batch_returns_operator_plan(self) -> None:
        plan = ensure_batch_allowed(cnj_count=10, confirm_batch=True, calls_per_cnj=2)

        assert plan.requires_confirmation is True
        assert plan.estimated_calls == 20
        assert plan.rate_limit_per_second == 1.0
