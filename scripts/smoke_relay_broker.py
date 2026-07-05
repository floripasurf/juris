#!/usr/bin/env python
"""Broker relay smoke — the multi-worker proof (Sprint 8 gate).

The reverse-channel relay is a per-process hub: an agent registers on the worker
that terminated its WebSocket. With >1 worker in remote mode, a token operation
(MNI read / filing) entering a DIFFERENT worker must still reach that agent. The
Redis broker (``JURIS_RELAY_BROKER``) makes that work: worker A's hub subscribes
to the tenant's request channel; worker B publishes the op and awaits the
correlated reply; a ``SET NX`` pending key dedupes an in-flight ``request_id``.

This smoke instantiates TWO independent ``RelayHub(broker=RedisRelayBroker(...))``
instances — "worker A" and "worker B" — that share ONE real Redis and nothing
else, then proves:

  1. cross-worker routing: an agent registered on hub A answers a request that
     enters hub B (Redis pub/sub carries it worker→worker);
  2. request_id dedupe: a concurrent duplicate is rejected by the broker's SET NX.

The WebSocket transport (agent dialer ↔ /ws/agent-relay endpoint) is covered by
unit tests in tests/unit/api/test_relay.py; what needs a REAL Redis + two workers
is exactly this routing/dedupe layer, which unit tests with the in-memory broker
cannot exercise. Run it with:

    docker run -d --name smoke-redis -p 6399:6379 redis:7-alpine
    JURIS_RELAY_BROKER=redis://127.0.0.1:6399/0 uv run python scripts/smoke_relay_broker.py

Exits non-zero if routing or dedupe fails.
"""

from __future__ import annotations

import asyncio
import os
import sys

from juris.api.relay import RedisRelayBroker, RelayHub
from juris.api.ws_schemas import AgentRequest, AgentResponse

_TENANT = "smoke-broker"
# The fake agent holds each request in-flight briefly so the dedupe check can
# collide a second request against the first's still-live SET NX pending key.
_AGENT_DELAY_SECONDS = 0.3


async def _run() -> int:
    broker_url = os.environ.get("JURIS_RELAY_BROKER", "").strip()
    if not broker_url:
        print("[FAIL] defina JURIS_RELAY_BROKER=redis://... antes de rodar o smoke")
        return 2

    # Two workers: two hubs, two broker clients, ONE Redis. They communicate only
    # through Redis — no shared memory — so this is a faithful cross-worker test.
    broker_a = RedisRelayBroker(broker_url)
    broker_b = RedisRelayBroker(broker_url)
    hub_a = RelayHub(broker=broker_a)
    hub_b = RelayHub(broker=broker_b)

    seen: list[str] = []

    async def fake_agent(payload: str) -> None:
        """The token-holding agent: resolves the read with ITS OWN creds (never on the wire)."""
        request = AgentRequest.model_validate_json(payload)
        seen.append(request.request_id)
        await asyncio.sleep(_AGENT_DELAY_SECONDS)
        response = AgentResponse(
            request_id=request.request_id,
            success=True,
            payload={"classe": "Apelação Cível"},
        )
        await hub_a.resolve_async(request.tenant_id, response)

    hub_a.register(_TENANT, fake_agent)

    # Wait until worker B sees the agent's presence via Redis (cross-client),
    # proving the subscription is live before we publish to it.
    for _ in range(100):
        if broker_b.is_connected(_TENANT):
            break
        await asyncio.sleep(0.05)
    else:
        print("[FAIL] presença do agente não propagou pelo Redis (worker B não vê worker A)")
        return 1

    # 1) Cross-worker round-trip: request enters hub B, agent lives on hub A.
    request = AgentRequest(request_id="smoke-1", tenant_id=_TENANT, operation="mni", payload={})
    response: AgentResponse | None = None
    for _ in range(10):
        try:
            response = await hub_b.send(_TENANT, request, timeout=10)
            break
        except RuntimeError as exc:
            if "nenhum agente" in str(exc):
                await asyncio.sleep(0.1)  # absorb subscription-startup race
                continue
            raise
    ok_routing = response is not None and response.payload.get("classe") == "Apelação Cível"
    tag = "OK" if ok_routing else "FAIL"
    print(f"[{tag}] roteamento cross-worker: agente no worker A respondeu request do worker B")

    # 2) Dedupe: a concurrent duplicate request_id is rejected by the broker's SET NX.
    dup = AgentRequest(request_id="smoke-dup", tenant_id=_TENANT, operation="mni", payload={})
    first = asyncio.create_task(hub_b.send(_TENANT, dup, timeout=10))
    await asyncio.sleep(0.05)  # let the first acquire the pending lock
    ok_dedupe = False
    try:
        await hub_b.send(_TENANT, dup, timeout=10)
    except RuntimeError as exc:
        ok_dedupe = "duplicado" in str(exc)
    await first
    print(f"[{'OK' if ok_dedupe else 'FAIL'}] dedupe de request_id: duplicata concorrente rejeitada (SET NX)")

    hub_a.unregister(_TENANT)
    await asyncio.sleep(0.1)

    ok = ok_routing and ok_dedupe
    print("SMOKE BROKER OK" if ok else "SMOKE BROKER FAILED")
    return 0 if ok else 1


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
