"""Tests for the Remote MNI read service — split-trust client (ADR-0015, frente B)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter

from juris.api.ws_schemas import AgentRequest, AgentResponse
from juris.mni.operations.intimacoes import AvisosResult
from juris.mni.parsers.processo import Movimento, ProcessoDomain
from juris.mni.remote import RemoteMNIReadService
from juris.mni.tribunais import get_tribunal


class _EchoTransport:
    """Returns a canned AgentResponse, echoing the request_id; records the request."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.sent: AgentRequest | None = None

    def send(self, request: AgentRequest) -> AgentResponse:
        self.sent = request
        return AgentResponse(request_id=request.request_id, success=True, payload=self._payload)


def _processo() -> ProcessoDomain:
    return ProcessoDomain(
        numero_cnj="5082351-40.2017.8.13.0024",
        classe="Apelação Cível",
        movimentos=[Movimento(data_hora=datetime(2026, 1, 2, tzinfo=UTC), tipo="movimentoNacional")],
    )


def test_consultar_processo_round_trips_domain() -> None:
    dumped = TypeAdapter(ProcessoDomain).dump_python(_processo(), mode="json")
    transport = _EchoTransport(dumped)
    service = RemoteMNIReadService(transport)

    result = service.consultar_processo(
        "5082351-40.2017.8.13.0024", get_tribunal("tjmg"), "07671039632", "senha", token_pin="9999"  # noqa: S106
    )

    assert isinstance(result, ProcessoDomain)
    assert result.classe == "Apelação Cível"
    assert result.movimentos[0].tipo == "movimentoNacional"


def test_credentials_never_forwarded_to_cloud() -> None:
    """Split-trust: cpf/senha/PIN are resolved at the agent, never sent."""
    transport = _EchoTransport(TypeAdapter(ProcessoDomain).dump_python(_processo(), mode="json"))
    RemoteMNIReadService(transport).consultar_processo(
        "123", get_tribunal("tjmg"), "07671039632", "senha-pje-secreta", token_pin="pin-9999"  # noqa: S106
    )

    assert transport.sent is not None
    wire = transport.sent.model_dump_json()
    assert "senha-pje-secreta" not in wire
    assert "pin-9999" not in wire
    assert "07671039632" not in wire
    # only the operation params travel
    assert transport.sent.payload["numero_cnj"] == "123"
    assert transport.sent.payload["tribunal_id"] == "tjmg"


def test_consultar_avisos_round_trips() -> None:
    avisos = AvisosResult(sucesso=True, mensagem="ok", avisos=[])
    dumped = TypeAdapter(AvisosResult).dump_python(avisos, mode="json")
    service = RemoteMNIReadService(_EchoTransport(dumped))

    result = service.consultar_avisos(get_tribunal("tjmg"), "07671039632", "senha", token_pin="9999")  # noqa: S106

    assert isinstance(result, AvisosResult)
    assert result.sucesso is True


def test_raises_on_agent_error() -> None:
    class _ErrTransport:
        def send(self, request: AgentRequest) -> AgentResponse:
            return AgentResponse(request_id=request.request_id, success=False, error="token ausente")

    with pytest.raises(RuntimeError, match="token ausente"):
        RemoteMNIReadService(_ErrTransport()).consultar_avisos(
            get_tribunal("tjmg"), "07671039632", "senha", token_pin="9999"  # noqa: S106
        )


# --- agent server-side handler (resolves credentials locally) ---


class _FakeMNI:
    def consultar_processo(self, numero_cnj, tribunal_cfg, cpf, senha, *, token_pin=None, com_documentos=False):  # noqa: ANN001, ANN201
        # credentials must come from the agent's local resolver, not the wire
        assert (cpf, senha, token_pin) == ("local-cpf", "local-senha", "local-pin")
        assert tribunal_cfg.id == "tjmg"
        return _processo()

    def consultar_avisos(self, tribunal_cfg, cpf, senha, *, token_pin=None):  # noqa: ANN001, ANN201
        return AvisosResult(sucesso=True, mensagem="ok", avisos=[])


def _creds() -> tuple[str, str, str]:
    return ("local-cpf", "local-senha", "local-pin")


def test_handle_mni_consultar_processo_resolves_creds_locally() -> None:
    from juris.api.local_agent import handle_mni_request

    req = AgentRequest(
        request_id="r1",
        operation="mni.consultar_processo",
        payload={"numero_cnj": "123", "tribunal_id": "tjmg"},
    )
    resp = handle_mni_request(req, _FakeMNI(), credentials_resolver=_creds, tribunal_resolver=get_tribunal)

    assert resp.success
    assert resp.request_id == "r1"
    assert resp.payload["classe"] == "Apelação Cível"


def test_handle_mni_unknown_operation_errors() -> None:
    from juris.api.local_agent import handle_mni_request

    req = AgentRequest(request_id="r2", operation="mni.bogus", payload={"tribunal_id": "tjmg"})
    resp = handle_mni_request(req, _FakeMNI(), credentials_resolver=_creds, tribunal_resolver=get_tribunal)

    assert resp.success is False
    assert "bogus" in (resp.error or "")


# --- factory + /ws/mni integration ---


def test_factory_inprocess_by_default(monkeypatch) -> None:
    from juris.mni.factory import get_mni_read_service
    from juris.mni.service import InProcessMNIReadService

    monkeypatch.delenv("JURIS_AGENT_MODE", raising=False)
    assert isinstance(get_mni_read_service(), InProcessMNIReadService)


def test_factory_remote_when_configured(monkeypatch) -> None:
    from juris.mni.factory import get_mni_read_service

    monkeypatch.setenv("JURIS_AGENT_MODE", "remote")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_URL", "ws://127.0.0.1:8765")
    monkeypatch.setenv("JURIS_LOCAL_AGENT_TOKEN", "tok")
    assert isinstance(get_mni_read_service(), RemoteMNIReadService)


def test_ws_mni_round_trip_with_testclient(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from juris.api import local_agent

    monkeypatch.setattr(local_agent, "agent_mni_service", lambda: _FakeMNI())
    monkeypatch.setenv("JURIS_AGENT_CPF", "local-cpf")
    monkeypatch.setenv("JURIS_AGENT_SENHA", "local-senha")
    monkeypatch.setenv("JURIS_AGENT_PIN", "local-pin")
    client = TestClient(local_agent.app)
    token = local_agent.get_signing_token()

    with client.websocket_connect(f"/ws/mni?token={token}") as ws:
        req = AgentRequest(
            request_id="m1",
            operation="mni.consultar_processo",
            payload={"numero_cnj": "123", "tribunal_id": "tjmg"},
        )
        ws.send_text(req.model_dump_json())
        resp = AgentResponse.model_validate_json(ws.receive_text())

    assert resp.success
    assert resp.payload["classe"] == "Apelação Cível"


def test_demo_load_processo_mni_routes_through_factory(monkeypatch) -> None:
    """DoD: the demo MNI read goes through get_mni_read_service — config swaps it."""
    from juris.demo import orchestrator
    from juris.demo.orchestrator import SourceMode, load_processo

    used = {"flag": False}

    class _Svc:
        def consultar_processo(self, numero_cnj, tribunal_cfg, cpf, senha, *, token_pin=None, com_documentos=False):  # noqa: ANN001, ANN201
            used["flag"] = True
            return _processo()

        def consultar_avisos(self, *a, **k):  # noqa: ANN002, ANN003, ANN201
            raise AssertionError

    monkeypatch.setattr(orchestrator, "get_mni_read_service", lambda: _Svc())
    result = load_processo(
        "5082351-40.2017.8.13.0024", "tjmg", SourceMode.MNI,
        cpf="07671039632", senha="x", token_pin="9999",  # noqa: S106
    )

    assert used["flag"] is True
    assert result.classe == "Apelação Cível"


def test_tenant_id_is_carried_on_mni_requests() -> None:
    transport = _EchoTransport(TypeAdapter(ProcessoDomain).dump_python(_processo(), mode="json"))
    service = RemoteMNIReadService(transport, tenant_id="escritorio-b")
    service.consultar_processo("123", get_tribunal("tjmg"), "cpf", "senha")
    assert transport.sent is not None
    assert transport.sent.tenant_id == "escritorio-b"
