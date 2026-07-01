"""Tests for the reverse-channel relay hub (agent dials out; cloud routes through)."""

from __future__ import annotations

import asyncio

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
    hub.resolve(AgentResponse(request_id="r1", success=True, payload={"ok": 1}))
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
