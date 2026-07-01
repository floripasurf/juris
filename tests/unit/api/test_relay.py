"""Tests for the reverse-channel relay hub (agent dials out; cloud routes through)."""

from __future__ import annotations

import asyncio
import json

import pytest

from juris.api.relay import RelayHub
from juris.api.ws_schemas import AgentRequest, AgentResponse


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
