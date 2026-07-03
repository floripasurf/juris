"""Reverse-channel relay hub (ADR-0015 Phase 2).

The local agent is loopback-only and behind the firm's NAT, so a cloud orchestrator
cannot dial it. Instead the **agent dials out** to the orchestrator and holds a
persistent WebSocket; the orchestrator routes token-operation requests down that
connection and correlates replies by ``request_id``. This sidesteps NAT entirely
without ever exposing the agent to the public network.

``RelayHub`` is the orchestrator-side registry + request/response multiplexer. The
WebSocket endpoint (agent-facing) and the agent's outbound dialer live alongside it.

By default, the hub is an in-process singleton (``_HUB``). For multi-worker /
multi-instance remote mode, set ``JURIS_RELAY_BROKER=redis://...`` so requests are
published to the worker holding the agent WebSocket and responses are correlated
through broker reply channels. Sticky routing remains a valid small-deploy option.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import os
import time
import uuid
from asyncio import AbstractEventLoop
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, cast

from juris.api.ws_schemas import AgentRequest, AgentResponse
from juris.core.observability import get_logger

SendJson = Callable[[str], Awaitable[None]]
logger = get_logger(__name__)


class BrokerSubscription(Protocol):
    """A request-channel subscription owned by a local agent connection."""

    def close(self) -> None:
        """Stop receiving brokered requests for this connection."""
        ...


class RelayBroker(Protocol):
    """Cross-worker request/response transport for reverse-channel operations."""

    def subscribe_requests(self, tenant_id: str, handler: SendJson) -> BrokerSubscription:
        """Receive requests for ``tenant_id`` on the worker holding the agent socket."""
        ...

    async def request(
        self,
        tenant_id: str,
        request_id: str,
        payload: str,
        *,
        timeout: float,
    ) -> str:
        """Publish a request and wait for the correlated response payload."""
        ...

    async def publish_response(self, tenant_id: str, request_id: str, payload: str) -> None:
        """Publish an agent response to the correlated reply channel."""
        ...

    def is_connected(self, tenant_id: str) -> bool:
        """Whether any worker currently advertises a connected agent for tenant."""
        ...


class MemoryRelayBroker:
    """In-process broker used by tests to exercise multi-hub routing deterministically."""

    def __init__(self) -> None:
        self._subscribers: dict[str, dict[str, SendJson]] = {}
        self._pending: dict[tuple[str, str], asyncio.Future[str]] = {}

    def subscribe_requests(self, tenant_id: str, handler: SendJson) -> BrokerSubscription:
        subscription_id = uuid.uuid4().hex
        self._subscribers.setdefault(tenant_id, {})[subscription_id] = handler

        broker = self

        class _Subscription:
            def close(self) -> None:
                handlers = broker._subscribers.get(tenant_id)
                if handlers is None:
                    return
                handlers.pop(subscription_id, None)
                if not handlers:
                    broker._subscribers.pop(tenant_id, None)

        return _Subscription()

    async def request(
        self,
        tenant_id: str,
        request_id: str,
        payload: str,
        *,
        timeout: float,
    ) -> str:
        handlers = list(self._subscribers.get(tenant_id, {}).values())
        if not handlers:
            msg = f"nenhum agente conectado para o tenant {tenant_id!r} (broker)"
            raise RuntimeError(msg)
        key = (tenant_id, request_id)
        if key in self._pending:
            msg = f"request_id duplicado em andamento para o tenant {tenant_id!r}: {request_id}"
            raise RuntimeError(msg)
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending[key] = fut
        try:
            for handler in handlers:
                asyncio.ensure_future(handler(payload))
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(key, None)

    async def publish_response(self, tenant_id: str, request_id: str, payload: str) -> None:
        fut = self._pending.get((tenant_id, request_id))
        if fut is not None and not fut.done():
            fut.set_result(payload)

    def is_connected(self, tenant_id: str) -> bool:
        return bool(self._subscribers.get(tenant_id))


class _RedisRelaySubscription:
    def __init__(
        self,
        broker: RedisRelayBroker,
        tenant_id: str,
        handler: SendJson,
        *,
        subscription_id: str,
    ) -> None:
        self._broker = broker
        self._tenant_id = tenant_id
        self._handler = handler
        self._subscription_id = subscription_id
        self._task = asyncio.create_task(self._run())

    def close(self) -> None:
        self._task.cancel()

    async def _heartbeat(self) -> None:
        key = self._broker.presence_key(self._tenant_id)
        while True:
            await self._broker.async_client.set(key, self._subscription_id, ex=self._broker.presence_ttl)
            await asyncio.sleep(max(1, self._broker.presence_ttl // 3))

    async def _run(self) -> None:
        channel = self._broker.request_channel(self._tenant_id)
        key = self._broker.presence_key(self._tenant_id)
        pubsub = self._broker.async_client.pubsub()
        heartbeat = asyncio.create_task(self._heartbeat())
        try:
            await pubsub.subscribe(channel)
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                await self._handler(data.decode("utf-8") if isinstance(data, bytes) else str(data))
        except asyncio.CancelledError:
            pass
        finally:
            heartbeat.cancel()
            try:
                current = await self._broker.async_client.get(key)
                if current == self._subscription_id:
                    await self._broker.async_client.delete(key)
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception:  # noqa: BLE001 — cleanup best effort; connection may already be gone
                logger.warning("relay_redis_subscription_cleanup_failed")


class RedisRelayBroker:
    """Redis pub/sub broker for reverse-channel routing across orchestrator workers."""

    def __init__(
        self,
        redis_url: str,
        *,
        prefix: str = "juris:relay:",
        presence_ttl: int = 45,
    ) -> None:
        import redis
        import redis.asyncio as redis_async

        self._prefix = prefix
        self._sync_client = redis.Redis.from_url(redis_url, decode_responses=True)
        async_from_url = cast(Any, redis_async.from_url)
        self.async_client = async_from_url(redis_url, decode_responses=True)
        self.presence_ttl = presence_ttl

    def request_channel(self, tenant_id: str) -> str:
        return f"{self._prefix}request:{tenant_id}"

    def reply_channel(self, tenant_id: str, request_id: str) -> str:
        digest = hashlib.sha256(f"{tenant_id}\0{request_id}".encode()).hexdigest()
        return f"{self._prefix}reply:{digest}"

    def presence_key(self, tenant_id: str) -> str:
        return f"{self._prefix}agent:{tenant_id}"

    def pending_key(self, tenant_id: str, request_id: str) -> str:
        digest = hashlib.sha256(f"{tenant_id}\0{request_id}".encode()).hexdigest()
        return f"{self._prefix}pending:{digest}"

    def subscribe_requests(self, tenant_id: str, handler: SendJson) -> BrokerSubscription:
        return _RedisRelaySubscription(self, tenant_id, handler, subscription_id=uuid.uuid4().hex)

    async def request(
        self,
        tenant_id: str,
        request_id: str,
        payload: str,
        *,
        timeout: float,
    ) -> str:
        reply_channel = self.reply_channel(tenant_id, request_id)
        pending_key = self.pending_key(tenant_id, request_id)
        acquired = await self.async_client.set(
            pending_key,
            "1",
            nx=True,
            ex=max(1, int(timeout) + 5),
        )
        if not acquired:
            msg = f"request_id duplicado em andamento para o tenant {tenant_id!r}: {request_id}"
            raise RuntimeError(msg)

        pubsub = self.async_client.pubsub()
        try:
            await pubsub.subscribe(reply_channel)
            subscribers = await self.async_client.publish(self.request_channel(tenant_id), payload)
            if int(subscribers) < 1:
                msg = f"nenhum agente conectado para o tenant {tenant_id!r} (broker)"
                raise RuntimeError(msg)

            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=min(0.2, remaining),
                )
                if not message:
                    continue
                data = message.get("data")
                return data.decode("utf-8") if isinstance(data, bytes) else str(data)
        finally:
            await self.async_client.delete(pending_key)
            try:
                await pubsub.unsubscribe(reply_channel)
                await pubsub.aclose()
            except Exception:  # noqa: BLE001 — cleanup best effort; request already completed/failed
                logger.warning("relay_redis_request_cleanup_failed")

    async def publish_response(self, tenant_id: str, request_id: str, payload: str) -> None:
        await self.async_client.publish(self.reply_channel(tenant_id, request_id), payload)

    def is_connected(self, tenant_id: str) -> bool:
        try:
            return bool(self._sync_client.exists(self.presence_key(tenant_id)))
        except Exception:  # noqa: BLE001 — Redis health is surfaced as no connected agent
            logger.warning("relay_redis_presence_check_failed")
            return False


class RelayHub:
    """Routes orchestrator → agent requests over each tenant's dialed-in connection."""

    def __init__(self, *, broker: RelayBroker | None = None) -> None:
        self._agents: dict[str, tuple[int, SendJson, AbstractEventLoop | None]] = {}
        self._pending: dict[tuple[str, str], asyncio.Future[AgentResponse]] = {}
        self._broker = broker
        self._subscriptions: dict[str, tuple[int, BrokerSubscription]] = {}
        self._next_connection_id = 0

    def register(self, tenant_id: str, send_json: SendJson) -> int:
        """Record a connected agent's outbound send function (its WebSocket writer).

        Returns an opaque connection id. When a tenant reconnects, the newest
        connection replaces the previous one; the older connection's eventual
        ``unregister`` call must not remove the newer binding.
        """
        self._next_connection_id += 1
        connection_id = self._next_connection_id
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        self._agents[tenant_id] = (connection_id, send_json, loop)
        if self._broker is not None:
            current = self._subscriptions.pop(tenant_id, None)
            if current is not None:
                current[1].close()
            self._subscriptions[tenant_id] = (
                connection_id,
                self._broker.subscribe_requests(tenant_id, send_json),
            )
        return connection_id

    def unregister(self, tenant_id: str, connection_id: int | None = None) -> None:
        current = self._agents.get(tenant_id)
        if current is None:
            return
        if connection_id is None or current[0] == connection_id:
            self._agents.pop(tenant_id, None)
            subscription = self._subscriptions.pop(tenant_id, None)
            if subscription is not None:
                subscription[1].close()

    def is_connected(self, tenant_id: str) -> bool:
        if tenant_id in self._agents:
            return True
        return self._broker.is_connected(tenant_id) if self._broker is not None else False

    async def send(self, tenant_id: str, request: AgentRequest, *, timeout: float = 30.0) -> AgentResponse:
        """Forward ``request`` to the tenant's agent and await the correlated reply.

        Raises ``RuntimeError`` if no agent is connected and ``TimeoutError`` if the
        agent doesn't answer within ``timeout``.
        """
        routed_request = request.model_copy(update={"tenant_id": tenant_id})
        if self._broker is not None:
            raw = await self._broker.request(
                tenant_id,
                routed_request.request_id,
                routed_request.model_dump_json(),
                timeout=timeout,
            )
            response = AgentResponse.model_validate_json(raw)
            if response.request_id != routed_request.request_id:
                msg = "resposta do relay não correlaciona com o pedido"
                raise RuntimeError(msg)
            return response

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
        _connection_id, send_json, _loop = send_entry

        loop = asyncio.get_event_loop()
        fut: asyncio.Future[AgentResponse] = loop.create_future()
        pending_key = (tenant_id, request.request_id)
        if pending_key in self._pending:
            msg = f"request_id duplicado em andamento para o tenant {tenant_id!r}: {request.request_id}"
            raise RuntimeError(msg)
        self._pending[pending_key] = fut
        try:
            await send_json(routed_request.model_dump_json())
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(pending_key, None)

    def send_sync(self, tenant_id: str, request: AgentRequest, *, timeout: float = 30.0) -> AgentResponse:
        """Synchronous bridge for blocking transports that need the reverse channel.

        Web endpoints run MNI/signing/filing calls in worker threads. When the
        agent WebSocket is held by the ASGI event loop, this schedules ``send`` on
        that loop so the WebSocket writer and pending future stay on their owner
        loop. Broker-backed deployments can run the coroutine in this thread.
        """
        send_entry = self._agents.get(tenant_id)
        if self._broker is None and send_entry is not None and send_entry[2] is not None:
            loop = send_entry[2]
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None
            if running_loop is loop:
                msg = "relay síncrono chamado no event loop; execute em uma thread ou use RelayHub.send."
                raise RuntimeError(msg)
            future = asyncio.run_coroutine_threadsafe(self.send(tenant_id, request, timeout=timeout), loop)
            try:
                return future.result(timeout=timeout + 1)
            except concurrent.futures.TimeoutError as exc:
                future.cancel()
                raise TimeoutError("tempo excedido ao aguardar resposta do relay") from exc

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is not None:
            msg = "relay síncrono chamado no event loop; execute em uma thread ou use RelayHub.send."
            raise RuntimeError(msg)
        return asyncio.run(self.send(tenant_id, request, timeout=timeout))

    def resolve(self, tenant_id: str, response: AgentResponse) -> None:
        """Complete this tenant's pending request whose id matches ``response``."""
        if self._broker is not None:
            asyncio.create_task(self.resolve_async(tenant_id, response))
            return
        fut = self._pending.get((tenant_id, response.request_id))
        if fut is not None and not fut.done():
            fut.set_result(response)

    async def resolve_async(self, tenant_id: str, response: AgentResponse) -> None:
        """Async variant used by the WebSocket endpoint so broker replies are flushed."""
        if self._broker is None:
            self.resolve(tenant_id, response)
            return
        await self._broker.publish_response(tenant_id, response.request_id, response.model_dump_json())


def reverse_channel_scaling_ok() -> tuple[bool, str]:
    """Whether the in-memory reverse channel is safe under the current worker config.

    The hub is per-process: an agent registers on the worker that terminated its
    WebSocket; a request on another worker won't find it. So multi-worker
    (``WEB_CONCURRENCY`` / ``JURIS_WEB_WORKERS`` > 1) WITHOUT an external broker
    (``JURIS_RELAY_BROKER``) is unsafe — :meth:`RelayHub.send` fails-closed rather than
    silently misroute a token op (MNI read / filing). See ``docs/deployment.md``.
    """
    import os

    # Parse each worker-count env INDEPENDENTLY: a malformed WEB_CONCURRENCY must not
    # mask a real JURIS_WEB_WORKERS, and a present-but-unparseable value fails CLOSED
    # (treated as unsafe) rather than silently collapsing to "single worker".
    workers = 1
    unparseable = False
    for name in ("WEB_CONCURRENCY", "JURIS_WEB_WORKERS"):
        raw = os.environ.get(name, "").strip()
        if not raw:
            continue
        try:
            workers = max(workers, int(raw))
        except ValueError:
            unparseable = True

    if workers <= 1 and not unparseable:
        return True, ""
    # Multi-worker (or an unparseable count) is safe only with an external broker OR with
    # sticky routing the operator asserts at the LB. Both are explicit opt-ins so a plain
    # multi-worker misconfig still fails loudly. ``JURIS_RELAY_STICKY`` is an assertion, not
    # a verification — the operator owns the LB affinity (docs/deployment.md).
    broker = bool(os.environ.get("JURIS_RELAY_BROKER", "").strip())
    sticky = os.environ.get("JURIS_RELAY_STICKY", "").strip().lower() in {"1", "true", "yes"}
    if broker or sticky:
        return True, ""
    return False, (
        "canal reverso inseguro com múltiplos workers sem broker nem sticky: a conexão do "
        "agente vive em um worker e a requisição pode cair em outro. Use 1 worker, declare "
        "sticky routing com JURIS_RELAY_STICKY=1, ou configure JURIS_RELAY_BROKER (docs/deployment.md)."
    )


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


# One process-wide hub for the orchestrator. It is rebuilt when tests or process
# configuration change ``JURIS_RELAY_BROKER`` before first use in a worker.
_HUB: RelayHub | None = None
_HUB_BROKER_URL: str | None = None


def get_relay_hub() -> RelayHub:
    global _HUB, _HUB_BROKER_URL  # noqa: PLW0603

    broker_url = os.environ.get("JURIS_RELAY_BROKER", "").strip()
    if _HUB is None or broker_url != _HUB_BROKER_URL:
        broker = RedisRelayBroker(broker_url) if broker_url else None
        _HUB = RelayHub(broker=broker)
        _HUB_BROKER_URL = broker_url
    return _HUB
