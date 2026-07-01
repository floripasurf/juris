"""Reverse-channel relay hub (ADR-0015 Phase 2).

The local agent is loopback-only and behind the firm's NAT, so a cloud orchestrator
cannot dial it. Instead the **agent dials out** to the orchestrator and holds a
persistent WebSocket; the orchestrator routes token-operation requests down that
connection and correlates replies by ``request_id``. This sidesteps NAT entirely
without ever exposing the agent to the public network.

``RelayHub`` is the orchestrator-side registry + request/response multiplexer. The
WebSocket endpoint (agent-facing) and the agent's outbound dialer live alongside it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from juris.api.ws_schemas import AgentRequest, AgentResponse

SendJson = Callable[[str], Awaitable[None]]


class RelayHub:
    """Routes orchestrator → agent requests over each tenant's dialed-in connection."""

    def __init__(self) -> None:
        self._agents: dict[str, SendJson] = {}
        self._pending: dict[str, asyncio.Future[AgentResponse]] = {}

    def register(self, tenant_id: str, send_json: SendJson) -> None:
        """Record a connected agent's outbound send function (its WebSocket writer)."""
        self._agents[tenant_id] = send_json

    def unregister(self, tenant_id: str) -> None:
        self._agents.pop(tenant_id, None)

    def is_connected(self, tenant_id: str) -> bool:
        return tenant_id in self._agents

    async def send(self, tenant_id: str, request: AgentRequest, *, timeout: float = 30.0) -> AgentResponse:
        """Forward ``request`` to the tenant's agent and await the correlated reply.

        Raises ``RuntimeError`` if no agent is connected and ``TimeoutError`` if the
        agent doesn't answer within ``timeout``.
        """
        send_json = self._agents.get(tenant_id)
        if send_json is None:
            msg = f"nenhum agente conectado para o tenant {tenant_id!r} (reverse-channel)"
            raise RuntimeError(msg)

        loop = asyncio.get_event_loop()
        fut: asyncio.Future[AgentResponse] = loop.create_future()
        self._pending[request.request_id] = fut
        try:
            await send_json(request.model_dump_json())
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(request.request_id, None)

    def resolve(self, response: AgentResponse) -> None:
        """Complete the pending request whose id matches ``response`` (agent → cloud)."""
        fut = self._pending.get(response.request_id)
        if fut is not None and not fut.done():
            fut.set_result(response)


def relay_token_ok(tenant_id: str, presented: str | None) -> bool:
    """Whether a dialing agent's token matches what the orchestrator expects for the tenant.

    The expected token is the tenant's binding token (``JURIS_AGENTS_FILE``) or the
    global fallback — the same shared secret used to authenticate the other direction.
    """
    import secrets

    from juris.api.agent_config import tenant_agent_binding

    if presented is None:
        return False
    try:
        expected = tenant_agent_binding(tenant_id).token
    except RuntimeError:
        return False
    return secrets.compare_digest(presented, expected)


# One process-wide hub for the orchestrator.
_HUB = RelayHub()


def get_relay_hub() -> RelayHub:
    return _HUB
