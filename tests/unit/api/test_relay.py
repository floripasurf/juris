"""Tests for the reverse-channel relay hub (agent dials out; cloud routes through)."""

from __future__ import annotations

import asyncio
import json

import pytest

from juris.api.relay import RelayHub
from juris.api.ws_schemas import AgentRequest, AgentResponse


def test_relay_token_rejects_shared_fallback_for_nondefault_tenant(monkeypatch) -> None:
    """A leaked global shared token must NOT authenticate an arbitrary firm's channel.

    Without a per-tenant agents file, tenant_agent_binding() returns the global
    fallback token for ANY tenant — so the reverse channel would accept the same
    secret as 'escritorio-a', letting a leaked token hijack that firm's token ops.
    Fail-closed: only the single co-located default tenant may use the shared token.
    """
    from juris.api.agent_config import _load_agent_bindings
    from juris.api.relay import relay_token_ok

    monkeypatch.delenv("JURIS_AGENTS_FILE", raising=False)
    monkeypatch.delenv("JURIS_REQUIRE_TENANTS", raising=False)
    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://x:1")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_TOKEN", "shared-secret")
    _load_agent_bindings.cache_clear()

    assert relay_token_ok("public", "shared-secret") is True  # single-tenant co-located: OK
    assert relay_token_ok("escritorio-a", "shared-secret") is False  # hijack blocked


def test_relay_token_requires_dedicated_per_tenant_binding(tmp_path, monkeypatch) -> None:
    agents = tmp_path / "agents.json"
    agents.write_text(json.dumps({"escritorio-a": {"url": "ws://a:1", "token": "tok-a"}}))
    monkeypatch.setenv("JURIS_AGENTS_FILE", str(agents))

    from juris.api.agent_config import _load_agent_bindings
    from juris.api.relay import relay_token_ok

    _load_agent_bindings.cache_clear()

    assert relay_token_ok("escritorio-a", "tok-a") is True
    assert relay_token_ok("escritorio-a", "wrong") is False
    assert relay_token_ok("escritorio-b", "tok-a") is False  # no binding → no shared fallback


@pytest.mark.asyncio
async def test_hub_routes_request_to_agent_and_resolves_by_id() -> None:
    hub = RelayHub()
    sent: list[str] = []

    async def fake_send(payload: str) -> None:
        sent.append(payload)

    hub.register("escritorio-a", fake_send)
    req = AgentRequest(request_id="r1", tenant_id="escritorio-a", operation="mni", payload={})

    task = asyncio.create_task(hub.send("escritorio-a", req, timeout=5))
    await asyncio.sleep(0)  # let send register the pending future
    hub.resolve("escritorio-a", AgentResponse(request_id="r1", success=True, payload={"ok": 1}))
    resp = await task

    assert resp.success is True
    assert resp.payload == {"ok": 1}
    assert sent, "request must be forwarded to the connected agent"


@pytest.mark.asyncio
async def test_hub_send_without_connected_agent_raises() -> None:
    hub = RelayHub()
    req = AgentRequest(request_id="r1", tenant_id="nobody", operation="mni", payload={})
    with pytest.raises(RuntimeError, match="nenhum agente"):
        await hub.send("nobody", req, timeout=1)


@pytest.mark.asyncio
async def test_hub_send_times_out_when_no_reply() -> None:
    hub = RelayHub()

    async def fake_send(payload: str) -> None:
        pass

    hub.register("t", fake_send)
    req = AgentRequest(request_id="r1", tenant_id="t", operation="mni", payload={})
    with pytest.raises(TimeoutError):
        await hub.send("t", req, timeout=0.05)


def test_hub_tracks_connection_state() -> None:
    hub = RelayHub()
    assert hub.is_connected("t") is False

    async def fake_send(payload: str) -> None:
        pass

    hub.register("t", fake_send)
    assert hub.is_connected("t") is True
    hub.unregister("t")
    assert hub.is_connected("t") is False


@pytest.mark.asyncio
async def test_hub_correlates_same_request_id_per_tenant() -> None:
    hub = RelayHub()

    async def fake_send(_payload: str) -> None:
        pass

    hub.register("tenant-a", fake_send)
    hub.register("tenant-b", fake_send)
    req_a = AgentRequest(request_id="same-id", tenant_id="tenant-a", operation="mni", payload={})
    req_b = AgentRequest(request_id="same-id", tenant_id="tenant-b", operation="mni", payload={})

    task_a = asyncio.create_task(hub.send("tenant-a", req_a, timeout=5))
    task_b = asyncio.create_task(hub.send("tenant-b", req_b, timeout=5))
    await asyncio.sleep(0)
    hub.resolve("tenant-b", AgentResponse(request_id="same-id", success=True, payload={"tenant": "b"}))
    hub.resolve("tenant-a", AgentResponse(request_id="same-id", success=True, payload={"tenant": "a"}))

    assert (await task_a).payload == {"tenant": "a"}
    assert (await task_b).payload == {"tenant": "b"}


@pytest.mark.asyncio
async def test_hub_rewrites_wire_tenant_to_routed_tenant() -> None:
    hub = RelayHub()
    sent: list[dict[str, object]] = []

    async def fake_send(payload: str) -> None:
        sent.append(json.loads(payload))

    hub.register("tenant-a", fake_send)
    req = AgentRequest(request_id="r1", tenant_id="spoofed", operation="mni", payload={})
    task = asyncio.create_task(hub.send("tenant-a", req, timeout=5))
    await asyncio.sleep(0)
    hub.resolve("tenant-a", AgentResponse(request_id="r1", success=True, payload={}))
    await task

    assert sent[0]["tenant_id"] == "tenant-a"


@pytest.mark.asyncio
async def test_hub_rejects_duplicate_pending_request_id_for_same_tenant() -> None:
    hub = RelayHub()
    first_send_started = asyncio.Event()
    release_first = asyncio.Event()

    async def fake_send(_payload: str) -> None:
        first_send_started.set()
        await release_first.wait()

    hub.register("tenant-a", fake_send)
    req = AgentRequest(request_id="same-id", tenant_id="tenant-a", operation="mni", payload={})

    task = asyncio.create_task(hub.send("tenant-a", req, timeout=5))
    await first_send_started.wait()
    with pytest.raises(RuntimeError, match="request_id duplicado"):
        await hub.send("tenant-a", req, timeout=5)

    hub.resolve("tenant-a", AgentResponse(request_id="same-id", success=True, payload={}))
    release_first.set()
    await task


def test_hub_old_connection_cannot_unregister_new_connection() -> None:
    hub = RelayHub()

    async def old_send(payload: str) -> None:
        del payload

    async def new_send(payload: str) -> None:
        del payload

    old_id = hub.register("tenant-a", old_send)
    new_id = hub.register("tenant-a", new_send)

    hub.unregister("tenant-a", old_id)
    assert hub.is_connected("tenant-a") is True
    hub.unregister("tenant-a", new_id)
    assert hub.is_connected("tenant-a") is False


def test_run_relay_agent_appends_validated_tenant_query(monkeypatch) -> None:
    from juris.api.local_agent import run_relay_agent

    captured: dict[str, object] = {}

    class _FakeWS:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter(())

    def fake_connect(url, *, additional_headers):  # noqa: ANN001, ANN202
        captured["url"] = url
        captured["headers"] = additional_headers
        return _FakeWS()

    monkeypatch.setattr("websockets.sync.client.connect", fake_connect)

    run_relay_agent("wss://juris.example/ws/agent-relay?existing=1", "tok", "escritorio-a")

    assert captured["url"] == "wss://juris.example/ws/agent-relay?existing=1&tenant=escritorio-a"
    assert captured["headers"] == {"x-agent-token": "tok"}


def test_run_relay_agent_rejects_unsafe_tenant_before_connect(monkeypatch) -> None:
    from juris.api.local_agent import run_relay_agent

    called = False

    def fake_connect(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        nonlocal called
        called = True
        raise AssertionError("connect should not be called")

    monkeypatch.setattr("websockets.sync.client.connect", fake_connect)

    with pytest.raises(ValueError, match="tenant_id inválido"):
        run_relay_agent("wss://juris.example/ws/agent-relay", "tok", "../escape")

    assert called is False


@pytest.mark.asyncio
async def test_dispatch_routes_mni_operation(monkeypatch) -> None:
    """A relayed mni request is routed to the local MNI handler (agent side)."""
    from juris.api import local_agent

    captured: dict[str, object] = {}

    def fake_handle_mni(request, service, **kwargs):
        captured["op"] = request.operation
        return AgentResponse(request_id=request.request_id, success=True, payload={"routed": "mni"})

    monkeypatch.setattr(local_agent, "handle_mni_request", fake_handle_mni)
    monkeypatch.setattr(local_agent, "agent_mni_service", lambda: object())

    req = AgentRequest(request_id="r1", tenant_id="t", operation="mni.consultar_processo", payload={})
    resp = await local_agent.dispatch_agent_request(req)

    assert resp.success is True
    assert resp.payload == {"routed": "mni"}
    assert captured["op"] == "mni.consultar_processo"


@pytest.mark.asyncio
async def test_dispatch_rejects_unknown_operation() -> None:
    from juris.api import local_agent

    req = AgentRequest(request_id="r1", tenant_id="t", operation="delete_everything", payload={})
    resp = await local_agent.dispatch_agent_request(req)
    assert resp.success is False
    assert "não suportada" in (resp.error or "")


@pytest.mark.asyncio
async def test_two_tenants_survive_agent_reconnect() -> None:
    """Correctness the sticky-routing/broker must preserve: after a tenant's agent
    reconnects, requests route to the NEW socket, the stale one can't hijack, and the
    other tenant is unaffected."""
    hub = RelayHub()
    sent_a1: list[str] = []
    sent_a2: list[str] = []
    sent_b: list[str] = []

    async def send_a1(p: str) -> None:
        sent_a1.append(p)

    async def send_a2(p: str) -> None:
        sent_a2.append(p)

    async def send_b(p: str) -> None:
        sent_b.append(p)

    id_a1 = hub.register("escritorio-a", send_a1)
    hub.register("escritorio-b", send_b)
    id_a2 = hub.register("escritorio-a", send_a2)  # A's agent reconnects → replaces binding
    assert id_a2 != id_a1

    # A request for A goes to the reconnected socket, never the stale one.
    req_a = AgentRequest(request_id="r", tenant_id="escritorio-a", operation="mni", payload={})
    task = asyncio.create_task(hub.send("escritorio-a", req_a, timeout=5))
    await asyncio.sleep(0)
    hub.resolve("escritorio-a", AgentResponse(request_id="r", success=True, payload={"who": "a2"}))
    assert (await task).payload == {"who": "a2"}
    assert sent_a2 and not sent_a1

    # The stale connection's late unregister must NOT drop the live binding.
    hub.unregister("escritorio-a", id_a1)
    assert hub.is_connected("escritorio-a") is True
    assert hub.is_connected("escritorio-b") is True  # B untouched throughout


def test_reverse_channel_scaling_ok_flags_multiworker_without_broker(monkeypatch) -> None:
    from juris.api.relay import reverse_channel_scaling_ok

    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    monkeypatch.delenv("JURIS_WEB_WORKERS", raising=False)
    monkeypatch.delenv("JURIS_RELAY_BROKER", raising=False)
    assert reverse_channel_scaling_ok()[0] is True  # single worker: safe

    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    assert reverse_channel_scaling_ok()[0] is False  # multi-worker, no broker: unsafe

    monkeypatch.setenv("JURIS_RELAY_BROKER", "redis://localhost:6379")
    assert reverse_channel_scaling_ok()[0] is True  # broker makes it safe again


@pytest.mark.asyncio
async def test_relay_send_fails_closed_under_multiworker(monkeypatch) -> None:
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    monkeypatch.delenv("JURIS_RELAY_BROKER", raising=False)
    hub = RelayHub()

    async def fake_send(_p: str) -> None:
        pass

    hub.register("t", fake_send)
    req = AgentRequest(request_id="r", tenant_id="t", operation="mni", payload={})
    # Fail LOUDLY (protect MNI/filing) instead of silently misrouting to a stale worker.
    with pytest.raises(RuntimeError, match="múltiplos workers"):
        await hub.send("t", req, timeout=1)
