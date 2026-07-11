"""Tests for the reverse-channel relay hub (agent dials out; cloud routes through)."""

from __future__ import annotations

import asyncio
import json

import pytest

from juris.api.relay import MemoryRelayBroker, RelayHub
from juris.api.ws_schemas import AgentRequest, AgentResponse, SignResponse


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


@pytest.mark.asyncio
async def test_broker_routes_request_between_hub_instances() -> None:
    """Worker B can route through the broker to the agent socket held by worker A."""
    broker = MemoryRelayBroker()
    hub_with_agent = RelayHub(broker=broker)
    hub_without_agent = RelayHub(broker=broker)
    sent_to_agent: list[dict[str, object]] = []

    async def fake_send(payload: str) -> None:
        sent_to_agent.append(json.loads(payload))

    hub_with_agent.register("tenant-a", fake_send)
    req = AgentRequest(request_id="r-broker", tenant_id="spoofed", operation="mni", payload={})

    task = asyncio.create_task(hub_without_agent.send("tenant-a", req, timeout=5))
    await asyncio.sleep(0)
    await hub_with_agent.resolve_async(
        "tenant-a",
        AgentResponse(request_id="r-broker", success=True, payload={"via": "broker"}),
    )

    resp = await task
    assert resp.success is True
    assert resp.payload == {"via": "broker"}
    assert sent_to_agent[0]["tenant_id"] == "tenant-a"


@pytest.mark.asyncio
async def test_broker_rejects_duplicate_request_id_across_hubs() -> None:
    broker = MemoryRelayBroker()
    hub_with_agent = RelayHub(broker=broker)
    hub_a = RelayHub(broker=broker)
    hub_b = RelayHub(broker=broker)
    release_send = asyncio.Event()

    async def slow_send(_payload: str) -> None:
        await release_send.wait()

    hub_with_agent.register("tenant-a", slow_send)
    req = AgentRequest(request_id="same-id", tenant_id="tenant-a", operation="mni", payload={})

    first = asyncio.create_task(hub_a.send("tenant-a", req, timeout=5))
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError, match="request_id duplicado"):
        await hub_b.send("tenant-a", req, timeout=5)

    await hub_with_agent.resolve_async(
        "tenant-a", AgentResponse(request_id="same-id", success=True, payload={})
    )
    release_send.set()
    await first


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


def test_run_relay_agent_forever_reconnects_with_backoff(monkeypatch) -> None:
    from juris.api import local_agent

    calls: list[tuple[str, str, str]] = []
    sleeps: list[float] = []

    def fake_run_relay_agent(url, token, tenant_id, *, dispatch=None, on_connected=None):  # noqa: ANN001, ANN202
        calls.append((url, token, tenant_id))
        if len(calls) < 3:
            raise OSError("relay indisponível")
        if on_connected is not None:
            on_connected()

    monkeypatch.setattr(local_agent, "run_relay_agent", fake_run_relay_agent)

    local_agent.run_relay_agent_forever(
        "wss://juris.example/ws/agent-relay",
        "tok",
        "escritorio-a",
        sleep=sleeps.append,
        jitter=lambda d: d,  # identidade: isola a progressão do backoff do jitter
        initial_backoff_seconds=1,
        max_backoff_seconds=5,
        max_attempts=3,
    )

    assert calls == [
        ("wss://juris.example/ws/agent-relay", "tok", "escritorio-a"),
        ("wss://juris.example/ws/agent-relay", "tok", "escritorio-a"),
        ("wss://juris.example/ws/agent-relay", "tok", "escritorio-a"),
    ]
    assert sleeps == [1, 2]
    assert local_agent._RELAY_STATES["escritorio-a"] == "stopped"


def test_run_relay_agent_forever_aplica_jitter_no_backoff(monkeypatch) -> None:
    from juris.api import local_agent

    sleeps: list[float] = []

    def always_down(url, token, tenant_id, *, dispatch=None, on_connected=None):  # noqa: ANN001, ANN202
        raise OSError("relay indisponível")

    monkeypatch.setattr(local_agent, "run_relay_agent", always_down)

    local_agent.run_relay_agent_forever(
        "wss://juris.example/ws/agent-relay",
        "tok",
        "escritorio-a",
        sleep=sleeps.append,
        jitter=lambda d: d * 0.5,  # jitter determinístico: metade do backoff base
        initial_backoff_seconds=2,
        max_backoff_seconds=100,
        max_attempts=3,
    )

    # backoff base 2 → 4; jitter aplicado antes de dormir → 1.0, 2.0
    assert sleeps == [1.0, 2.0]


def test_default_relay_jitter_fica_entre_metade_e_o_delay() -> None:
    from juris.api import local_agent

    for delay in (1.0, 4.0, 30.0):
        wait = local_agent._default_relay_jitter(delay)
        assert delay / 2 <= wait <= delay
    assert local_agent._default_relay_jitter(0.0) == 0.0


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
async def test_dispatch_routes_health_operation(monkeypatch) -> None:
    """A relayed health request returns token readiness from the local agent."""
    from juris.api import local_agent

    monkeypatch.setattr(
        local_agent,
        "agent_health",
        lambda: local_agent.HealthResponse(status="ok", token_connected=True, version="test"),
    )

    req = AgentRequest(request_id="r1", tenant_id="t", operation="health", payload={})
    resp = await local_agent.dispatch_agent_request(req)

    assert resp.success is True
    assert resp.payload and resp.payload["token_connected"] is True


@pytest.mark.asyncio
async def test_dispatch_routes_sign_operation(monkeypatch) -> None:
    """A relayed sign request is converted back to an AgentResponse envelope."""
    from juris.api import local_agent

    def fake_handle_sign(request, service, **kwargs):
        return SignResponse(
            request_id=request.request_id,
            success=True,
            signed_pdf_b64="cGRm",
            signer_name="Advogada",
            signer_cpf="00000000000",
            signed_pdf_hash="abc",
            signed_at="2026-01-01T00:00:00Z",
            cert_valid_until="2027-01-01",
        )

    monkeypatch.setattr(local_agent, "handle_sign_request", fake_handle_sign)
    monkeypatch.setattr(local_agent, "agent_signer", lambda: object())

    req = AgentRequest(
        request_id="r1",
        tenant_id="t",
        operation="sign",
        payload={"pdf_bytes_b64": "cGRm", "field_name": "AdvogadoSignature"},
    )
    resp = await local_agent.dispatch_agent_request(req)

    assert resp.success is True
    assert resp.payload and resp.payload["signed_pdf_b64"] == "cGRm"


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


@pytest.mark.asyncio
async def test_relay_send_sync_from_worker_thread_uses_registered_loop(monkeypatch) -> None:
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    monkeypatch.delenv("JURIS_WEB_WORKERS", raising=False)
    hub = RelayHub()
    sent: list[dict[str, object]] = []

    async def fake_send(payload: str) -> None:
        sent.append(json.loads(payload))
        hub.resolve("t", AgentResponse(request_id="r", success=True, payload={"ok": True}))

    hub.register("t", fake_send)
    req = AgentRequest(request_id="r", tenant_id="spoofed", operation="mni", payload={})

    response = await asyncio.to_thread(hub.send_sync, "t", req, timeout=5)

    assert response.payload == {"ok": True}
    assert sent[0]["tenant_id"] == "t"


def test_reverse_channel_scaling_ok_allows_asserted_sticky_sessions(monkeypatch) -> None:
    """A sticky-session deploy (LB affinity by tenant) is a VALID scaling path — the
    guard must not falsely block it just because there's no broker."""
    from juris.api.relay import reverse_channel_scaling_ok

    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    monkeypatch.delenv("JURIS_RELAY_BROKER", raising=False)
    monkeypatch.delenv("JURIS_RELAY_STICKY", raising=False)
    assert reverse_channel_scaling_ok()[0] is False  # multi-worker, no broker, no sticky assertion

    monkeypatch.setenv("JURIS_RELAY_STICKY", "1")
    assert reverse_channel_scaling_ok()[0] is True  # operator asserts sticky routing → allowed


def test_reverse_channel_scaling_guard_no_silent_bypass(monkeypatch) -> None:
    """Adversarial (agent A): env-parsing must not silently DISARM the guard."""
    from juris.api.relay import reverse_channel_scaling_ok

    for var in ("WEB_CONCURRENCY", "JURIS_WEB_WORKERS", "JURIS_RELAY_BROKER", "JURIS_RELAY_STICKY"):
        monkeypatch.delenv(var, raising=False)

    # (1) malformed WEB_CONCURRENCY must NOT mask a real JURIS_WEB_WORKERS=8.
    monkeypatch.setenv("WEB_CONCURRENCY", "notanint")
    monkeypatch.setenv("JURIS_WEB_WORKERS", "8")
    assert reverse_channel_scaling_ok()[0] is False

    # (2) an unparseable count alone fails CLOSED (can't prove single-worker).
    monkeypatch.delenv("JURIS_WEB_WORKERS", raising=False)
    monkeypatch.setenv("WEB_CONCURRENCY", "4.0")
    assert reverse_channel_scaling_ok()[0] is False

    # (3) whitespace-only broker is NOT a configured broker.
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    monkeypatch.setenv("JURIS_RELAY_BROKER", "   ")
    assert reverse_channel_scaling_ok()[0] is False
