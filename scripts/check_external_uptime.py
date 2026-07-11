#!/usr/bin/env python3
"""External uptime probe for the public Causia edge.

This script is intentionally stdlib-only so it can run from GitHub Actions or
any outside monitor. It must run outside the Mac Mini: the local launchd
watchdog cannot detect DNS, Cloudflare Tunnel or public routing failures.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

DEFAULT_ROOT_URL = "https://causia.com.br/"
DEFAULT_TIMEOUT_SECONDS = 10.0

StatusOpener = Callable[[str, float], int]


@dataclass(frozen=True, slots=True)
class ProbeResult:
    name: str
    url: str
    expected_statuses: tuple[int, ...]
    status_code: int | None
    ok: bool
    error: str = ""


def _status_from_urlopen(url: str, timeout: float) -> int:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("external uptime probe only accepts https URLs")
    request = Request(url, headers={"User-Agent": "causia-external-uptime/1.0"}, method="GET")  # noqa: S310
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-configured public HTTPS URL.
            return int(response.status)
    except HTTPError as exc:
        return int(exc.code)


def _health_url(root_url: str) -> str:
    return urljoin(root_url.rstrip("/") + "/", "api/health")


def _parse_statuses(value: str) -> tuple[int, ...]:
    statuses: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        statuses.append(int(part))
    if not statuses:
        raise ValueError("expected statuses cannot be empty")
    return tuple(statuses)


def probe_endpoint(
    name: str,
    url: str,
    expected_statuses: tuple[int, ...],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    opener: StatusOpener = _status_from_urlopen,
) -> ProbeResult:
    try:
        status = opener(url, timeout)
    except (TimeoutError, URLError, OSError, ValueError) as exc:
        return ProbeResult(
            name=name,
            url=url,
            expected_statuses=expected_statuses,
            status_code=None,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )
    return ProbeResult(
        name=name,
        url=url,
        expected_statuses=expected_statuses,
        status_code=status,
        ok=status in expected_statuses,
        error="" if status in expected_statuses else f"unexpected HTTP {status}",
    )


def run_checks(
    root_url: str,
    *,
    health_url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    opener: StatusOpener = _status_from_urlopen,
) -> list[ProbeResult]:
    root = root_url.strip() or DEFAULT_ROOT_URL
    health = health_url.strip() if health_url else _health_url(root)
    return [
        probe_endpoint("landing", root, (200,), timeout=timeout, opener=opener),
        probe_endpoint("api_health", health, (200, 401), timeout=timeout, opener=opener),
    ]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe public Causia uptime from outside the Mac Mini.")
    parser.add_argument(
        "--url",
        default=os.environ.get("CAUSIA_UPTIME_URL", DEFAULT_ROOT_URL),
        help=f"Public landing URL to probe (default: {DEFAULT_ROOT_URL}).",
    )
    parser.add_argument(
        "--health-url",
        default=os.environ.get("CAUSIA_UPTIME_HEALTH_URL", ""),
        help="Health URL to probe (default: <url>/api/health).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("CAUSIA_UPTIME_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)),
        help="Per-request timeout in seconds.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    results = run_checks(args.url, health_url=args.health_url or None, timeout=args.timeout)
    ok = all(result.ok for result in results)
    payload = {"ok": ok, "results": [asdict(result) for result in results]}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for result in results:
            status = result.status_code if result.status_code is not None else "ERR"
            expected = ",".join(str(s) for s in result.expected_statuses)
            marker = "OK" if result.ok else "FAIL"
            detail = f" ({result.error})" if result.error else ""
            print(f"{marker} {result.name}: {status} expected={expected} {result.url}{detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
