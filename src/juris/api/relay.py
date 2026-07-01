"""Reverse-channel relay hub (ADR-0015 Phase 2).

The local agent is loopback-only and behind the firm's NAT, so a cloud orchestrator
cannot dial it. Instead the **agent dials out** to the orchestrator and holds a
persistent WebSocket; the orchestrator routes token-operation requests down that
connection and correlates replies by ``request_id``. This sidesteps NAT entirely
without ever exposing the agent to the public network.

``RelayHub`` is the orchestrator-side registry + request/response multiplexer. The
WebSocket endpoint (agent-facing) and the agent's outbound dialer live alongside it.

DEPLOYMENT CONSTRAINT (Phase 2): the hub is an in-process singleton (``_HUB``). The
agent registers on whichever worker terminated its WebSocket, and ``send()`` only
finds it on THAT worker. So a multi-worker / multi-instance orchestrator MUST pin an
agent's reverse-channel connection and its token operations to the same process —
via sticky routing (LB affinity on the agent's tenant) or, at scale, an external
broker (Redis pub/sub keyed by tenant) replacing the in-memory maps. Single-worker
(the pilot) is unaffected. Until one of those is in place, run the reverse channel on
a single worker.
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
        scaling_ok, reason = reverse_channel_scaling_ok()
        if not scaling_ok:
            # Fail LOUDLY under an unsafe multi-worker config instead of silently
            # misrouting a token op (MNI read / filing) to a worker that isn't holding
            # this tenant's agent connection.
            raise RuntimeError(reason)
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


def reverse_channel_scaling_ok() -> tuple[bool, str]:
    """Whether the in-memory reverse channel is safe under the current worker config.

    The hub is per-process: an agent registers on the worker that terminated its
    WebSocket; a request on another worker won't find it. So multi-worker
    (``WEB_CONCURRENCY`` / ``JURIS_WEB_WORKERS`` > 1) WITHOUT an external broker
    (``JURIS_RELAY_BROKER``) is unsafe — :meth:`RelayHub.send` fails-closed rather than
    silently misroute a token op (MNI read / filing). See ``docs/deployment.md``.
    """
    import os

    try:
        workers = int(os.environ.get("WEB_CONCURRENCY") or os.environ.get("JURIS_WEB_WORKERS") or "1")
    except ValueError:
        workers = 1
    if workers > 1 and not os.environ.get("JURIS_RELAY_BROKER"):
        return False, (
            "canal reverso inseguro com múltiplos workers sem broker: a conexão do "
            "agente vive em um worker e a requisição pode cair em outro. Use 1 worker, "
            "sticky sessions por tenant, ou configure JURIS_RELAY_BROKER (docs/deployment.md)."
        )
    return True, ""


def relay_token_ok(tenant_id: str, presented: str | None) -> bool:
    """Whether a dialing agent's token matches what the orchestrator expects for the tenant.

    Fail-closed against reverse-channel hijack: the global shared fallback token
    (``JURIS_LOCAL_AGENT_TOKEN``) authenticates ONLY the single co-located default
    tenant. Any other firm must present its OWN per-tenant token from
    ``JURIS_AGENTS_FILE`` — otherwise a leaked shared secret could register as an
    arbitrary firm and receive that firm's token operations (drafts to sign, filings).
    """
    import secrets

    from juris.api.agent_config import has_dedicated_binding, tenant_agent_binding
    from juris.web.auth import PUBLIC_TENANT_ID

    if presented is None:
        return False
    # A tenant without its own binding may only use the shared token if it IS the
    # single default tenant; for any named firm this would be a shared-secret hijack.
    if not has_dedicated_binding(tenant_id) and tenant_id != PUBLIC_TENANT_ID:
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
