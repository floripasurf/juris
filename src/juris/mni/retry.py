"""Retry logic with exponential backoff and circuit breaker for MNI calls."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import TypeVar

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)
from zeep.exceptions import Fault, TransportError

from juris.core.observability import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

# Retryable exceptions (server errors, timeouts)
RETRYABLE_EXCEPTIONS = (TransportError, TimeoutError, ConnectionError, OSError)

# Non-retryable SOAP faults (auth errors, bad requests)
NON_RETRYABLE_FAULT_CODES = {"Client", "Client.Authentication", "Client.Authorization"}


def _is_retryable_fault(exc: BaseException) -> bool:
    """Check if a SOAP fault should be retried."""
    if isinstance(exc, Fault):
        code = getattr(exc, "code", "") or ""
        return code not in NON_RETRYABLE_FAULT_CODES
    return False


def _log_retry(retry_state: RetryCallState) -> None:
    """Log retry attempts."""
    logger.warning(
        "retrying_mni_call",
        attempt=retry_state.attempt_number,
        exception=str(retry_state.outcome.exception()) if retry_state.outcome else None,
    )


# Standard retry decorator for MNI operations
mni_retry = retry(
    retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
    wait=wait_exponential_jitter(initial=1, max=60, jitter=5),
    stop=stop_after_attempt(5),
    before_sleep=_log_retry,
    reraise=True,
)


# --- Circuit Breaker ---

@dataclass
class CircuitState:
    """State for a per-tribunal circuit breaker."""

    failures: int = 0
    last_failure_time: float = 0.0
    is_open: bool = False
    opened_at: float = 0.0


class CircuitBreaker:
    """Per-tribunal circuit breaker.

    Opens after `failure_threshold` failures within `window_seconds`.
    Stays open for `recovery_seconds` before allowing a probe.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        window_seconds: float = 600.0,  # 10 min
        recovery_seconds: float = 300.0,  # 5 min
    ) -> None:
        self._threshold = failure_threshold
        self._window = window_seconds
        self._recovery = recovery_seconds
        self._states: dict[str, CircuitState] = defaultdict(CircuitState)

    def check(self, tribunal_id: str) -> None:
        """Check if requests are allowed. Raises RuntimeError if circuit is open."""
        state = self._states[tribunal_id]
        if state.is_open:
            elapsed = time.monotonic() - state.opened_at
            if elapsed < self._recovery:
                msg = (
                    f"Circuit open for tribunal '{tribunal_id}'. "
                    f"Recovery in {self._recovery - elapsed:.0f}s."
                )
                raise RuntimeError(msg)
            # Recovery window passed — allow probe (half-open)
            state.is_open = False
            state.failures = 0
            logger.info("circuit_half_open", tribunal_id=tribunal_id)

    def record_success(self, tribunal_id: str) -> None:
        """Record a successful call."""
        state = self._states[tribunal_id]
        state.failures = 0
        if state.is_open:
            state.is_open = False
            logger.info("circuit_closed", tribunal_id=tribunal_id)

    def record_failure(self, tribunal_id: str) -> None:
        """Record a failed call. Opens circuit if threshold exceeded."""
        now = time.monotonic()
        state = self._states[tribunal_id]

        # Reset counter if outside the window
        if now - state.last_failure_time > self._window:
            state.failures = 0

        state.failures += 1
        state.last_failure_time = now

        if state.failures >= self._threshold:
            state.is_open = True
            state.opened_at = now
            logger.warning("circuit_opened", tribunal_id=tribunal_id, failures=state.failures)

    def get_state(self, tribunal_id: str) -> CircuitState:
        """Get the current circuit state for a tribunal."""
        return self._states[tribunal_id]


# Global circuit breaker instance
circuit_breaker = CircuitBreaker()
