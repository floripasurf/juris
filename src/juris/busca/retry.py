"""Shared circuit breaker for busca channels."""

from __future__ import annotations

from juris.mni.retry import CircuitBreaker

# Separate circuit breaker instance for busca channels.
# Tuned for web scraping: lower threshold, shorter windows.
busca_circuit_breaker = CircuitBreaker(
    failure_threshold=3,
    window_seconds=300.0,
    recovery_seconds=120.0,
)
