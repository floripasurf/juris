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
        self._agents: dict[str, tuple[int, SendJson]] = {}
        self._pending: dict[tuple[str, str], asyncio.Future[AgentResponse]] = {}
        self._next_connection_id = 0

    def register(self, tenant_id: str, send_json: SendJson) -> int:
        """Record a connected agent's outbound send function (its WebSocket writer).

        Returns an opaque connection id. When a tenant reconnects, the newest
        connection replaces the previous one; the older connection's eventual
        ``unregister`` call must not remove the newer binding.
        """
        self._next_connection_id += 1
        connection_id = self._next_connection_id
        self._agents[tenant_id] = (connection_id, send_json)
        return connection_id

    def unregister(self, tenant_id: str, connection_id: int | None = None) -> None:
        current = self._agents.get(tenant_id)
        if current is None:
            return
        if connection_id is None or current[0] == connection_id:
            self._agents.pop(tenant_id, None)

    def is_connected(self, tenant_id: str) -> bool:
        return tenant_id in self._agents

    async def send(self, tenant_id: str, request: AgentRequest, *, timeout: float = 30.0) -> AgentResponse:
        """Forward ``request`` to the tenant's agent and await the correlated reply.

        Raises ``RuntimeError`` if no agent is connected and ``TimeoutError`` if the
        agent doesn't answer within ``timeout``.
        """
        send_entry = self._agents.get(tenant_id)
        if send_entry is None:
            msg = f"nenhum agente conectado para o tenant {tenant_id!r} (reverse-channel)"
            raise RuntimeError(msg)
        _connection_id, send_json = send_entry

        loop = asyncio.get_event_loop()
        fut: asyncio.Future[AgentResponse] = loop.create_future()
        pending_key = (tenant_id, request.request_id)
        if pending_key in self._pending:
            msg = f"request_id duplicado em andamento para o tenant {tenant_id!r}: {request.request_id}"
            raise RuntimeError(msg)
        self._pending[pending_key] = fut
        routed_request = request.model_copy(update={"tenant_id": tenant_id})
        try:
            await send_json(routed_request.model_dump_json())
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(pending_key, None)

    def resolve(self, tenant_id: str, response: AgentResponse) -> None:
        """Complete this tenant's pending request whose id matches ``response``."""
        fut = self._pending.get((tenant_id, response.request_id))
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
