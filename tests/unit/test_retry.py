"""Tests for retry logic and circuit breaker."""

import time

from juris.mni.retry import CircuitBreaker


class TestCircuitBreaker:
    def test_initial_state_allows_requests(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        cb.check("trt2")  # Should not raise

    def test_opens_after_threshold(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, window_seconds=60.0, recovery_seconds=1.0)
        for _ in range(3):
            cb.record_failure("trt2")
        import pytest

        with pytest.raises(RuntimeError, match="Circuit open"):
            cb.check("trt2")

    def test_closes_after_recovery(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, window_seconds=60.0, recovery_seconds=0.1)
        cb.record_failure("trt2")
        cb.record_failure("trt2")

        time.sleep(0.15)
        cb.check("trt2")  # Should not raise (half-open)

    def test_success_resets_counter(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure("trt2")
        cb.record_failure("trt2")
        cb.record_success("trt2")
        cb.record_failure("trt2")
        cb.check("trt2")  # Should not raise — counter was reset

    def test_different_tribunals_independent(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, recovery_seconds=1.0)
        cb.record_failure("trt2")
        cb.record_failure("trt2")

        # trt2 is open, but trf3 should be fine
        import pytest

        with pytest.raises(RuntimeError):
            cb.check("trt2")
        cb.check("trf3")  # Should not raise

    def test_failures_outside_window_reset(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, window_seconds=0.1, recovery_seconds=1.0)
        cb.record_failure("trt2")
        cb.record_failure("trt2")
        time.sleep(0.15)
        cb.record_failure("trt2")  # Should reset counter (outside window)
        cb.check("trt2")  # Should not raise
