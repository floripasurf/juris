"""Safety primitives for DataJud calls.

This module keeps compliance-sensitive behavior close to the DataJud client:
rate limiting, local response caching, batch guards, and audit entries. The
defaults are intentionally conservative for pilot use.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from juris.persistence.audit import AuditLog

ENV_RATE_LIMIT_PER_SECOND = "JURIS_DATAJUD_RATE_LIMIT_PER_SECOND"
ENV_CACHE_DIR = "JURIS_DATAJUD_CACHE_DIR"
ENV_AUDIT_PATH = "JURIS_AUDIT_PATH"

DEFAULT_RATE_LIMIT_PER_SECOND = 1.0
DEFAULT_MOVEMENT_TTL = timedelta(hours=24)
DEFAULT_STATIC_TTL = timedelta(days=7)
DEFAULT_BATCH_CONFIRM_THRESHOLD = 10
_AUDIT_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class DataJudRequestMeta:
    """Stable metadata used for cache keys and audit entries."""

    cnj: str | None
    tribunal: str
    endpoint: str
    query_hash: str


@dataclass(frozen=True, slots=True)
class BatchPlan:
    """Operator-facing summary for a DataJud batch plan."""

    cnj_count: int
    estimated_calls: int
    rate_limit_per_second: float
    requires_confirmation: bool


class BatchGuardError(RuntimeError):
    """Raised when a batch crosses the confirmation threshold."""


def configured_rate_limit_per_second() -> float:
    """Return DataJud rate limit from env, falling back to 1 req/sec."""
    raw = os.environ.get(ENV_RATE_LIMIT_PER_SECOND)
    if raw is None or raw.strip() == "":
        return DEFAULT_RATE_LIMIT_PER_SECOND
    try:
        parsed = float(raw)
    except ValueError:
        return DEFAULT_RATE_LIMIT_PER_SECOND
    return parsed if parsed > 0 else DEFAULT_RATE_LIMIT_PER_SECOND


class RateLimiter:
    """Simple process-local rate limiter."""

    def __init__(
        self,
        *,
        calls_per_second: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._calls_per_second = calls_per_second or configured_rate_limit_per_second()
        self.interval_seconds = 1.0 / self._calls_per_second
        self._clock = clock
        self._sleeper = sleeper
        self._last_call_at: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> None:
        """Sleep until a call is allowed."""
        with self._lock:
            now = self._clock()
            if self._last_call_at is not None:
                elapsed = now - self._last_call_at
                remaining = self.interval_seconds - elapsed
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._clock()
            self._last_call_at = now


def default_cache_dir() -> Path:
    """Default DataJud cache directory."""
    explicit = os.environ.get(ENV_CACHE_DIR)
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".juris" / "cache" / "datajud"


def default_audit_path() -> Path:
    """Default audit path for DataJud calls outside per-case demo logs."""
    explicit = os.environ.get(ENV_AUDIT_PATH)
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".juris" / "audit.jsonl"


def query_hash(payload: dict[str, Any]) -> str:
    """Hash a DataJud request body for cache keys."""
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


class DataJudCache:
    """Local JSON response cache keyed by tribunal and request hash."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = root or default_cache_dir()
        self._now = now or (lambda: datetime.now(UTC))

    def _path_for(self, meta: DataJudRequestMeta) -> Path:
        safe_tribunal = meta.tribunal.lower().strip() or "unknown"
        return self.root / safe_tribunal / f"{meta.query_hash}.json"

    def get(self, meta: DataJudRequestMeta, *, ttl: timedelta = DEFAULT_MOVEMENT_TTL) -> dict[str, Any] | None:
        """Return a cached JSON payload if present and fresh."""
        path = self._path_for(meta)
        if not path.exists():
            return None
        try:
            wrapper = json.loads(path.read_text(encoding="utf-8"))
            cached_at = datetime.fromisoformat(wrapper["cached_at"])
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=UTC)
            if self._now() - cached_at > ttl:
                return None
            payload = wrapper["payload"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def set(self, meta: DataJudRequestMeta, payload: dict[str, Any]) -> None:
        """Persist a DataJud JSON payload."""
        path = self._path_for(meta)
        path.parent.mkdir(parents=True, exist_ok=True)
        wrapper = {
            "cached_at": self._now().isoformat(),
            "meta": {
                "cnj": meta.cnj,
                "tribunal": meta.tribunal,
                "endpoint": meta.endpoint,
                "query_hash": meta.query_hash,
            },
            "payload": payload,
        }
        path.write_text(json.dumps(wrapper, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    def purge(self) -> int:
        """Remove cached JSON files and return the number removed."""
        if not self.root.exists():
            return 0
        count = sum(1 for p in self.root.rglob("*.json") if p.is_file())
        shutil.rmtree(self.root)
        return count


def audit_datajud_call(
    audit: AuditLog,
    meta: DataJudRequestMeta,
    *,
    cache_hit: bool,
    status_code: int | None,
    duration_ms: float,
    result_count: int | None = None,
) -> None:
    """Append a DataJud request event to the audit chain."""
    details: dict[str, Any] = {
        "tribunal": meta.tribunal,
        "endpoint": meta.endpoint,
        "query_hash": meta.query_hash,
        "cache_hit": cache_hit,
        "status_code": status_code,
        "duration_ms": duration_ms,
    }
    if result_count is not None:
        details["result_count"] = result_count
    with _AUDIT_LOCK:
        audit.log(
            event_type="datajud.request",
            actor="system",
            processo_cnj=meta.cnj,
            details=details,
        )


def ensure_batch_allowed(
    *,
    cnj_count: int,
    confirm_batch: bool,
    calls_per_cnj: int = 1,
    rate_limit_per_second: float | None = None,
    threshold: int = DEFAULT_BATCH_CONFIRM_THRESHOLD,
    item_label: str = "CNJs",
) -> BatchPlan:
    """Refuse large DataJud batches unless the operator explicitly confirms."""
    estimated_calls = cnj_count * calls_per_cnj
    resolved_rate = rate_limit_per_second or configured_rate_limit_per_second()
    requires_confirmation = cnj_count >= threshold
    if requires_confirmation and not confirm_batch:
        msg = (
            f"Batch DataJud com {cnj_count} {item_label} ({estimated_calls} chamadas estimadas) "
            f"exige --confirm-batch/--confirm-datajud-batch. "
            f"Rate limit atual: {resolved_rate:g} req/s."
        )
        raise BatchGuardError(msg)
    return BatchPlan(
        cnj_count=cnj_count,
        estimated_calls=estimated_calls,
        rate_limit_per_second=resolved_rate,
        requires_confirmation=requires_confirmation,
    )
