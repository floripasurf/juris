"""Tests for the local agent — signing handler + WebSocket endpoint (ADR-0015)."""
from __future__ import annotations

import base64
import json
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from juris.api import local_agent
from juris.api.local_agent import app, get_signing_token, handle_sign_request, validate_local_agent_host
from juris.api.ws_schemas import HealthResponse, SignRequest, SignResponse
from juris.signing.pades import SigningResult
from juris.signing.service import SigningService


class _FakeSigner(SigningService):
    """Signs deterministically without a real token; records the PIN it saw."""

    def __init__(self) -> None:
        self.seen_pin: str | None = None

    def sign_pdf(self, pdf_bytes, *, pin, token_label=None, field_name="AdvogadoSignature", use_timestamp=False):  # noqa: ANN001, ANN201
        self.seen_pin = pin
        return SigningResult(
            signed_pdf=b"SIGNED:" + pdf_bytes,
            signer_name="Dra. Ana",
            signer_cpf="12345678900",
            timestamp=datetime(2026, 6, 29, tzinfo=UTC),
            pdf_hash="h",
            signed_pdf_hash="sh",
            cert_valid_until=date(2027, 1, 1),
        )


def test_health_endpoint():
    """Health returns ok status."""
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    # Validate against schema
    HealthResponse.model_validate(data)


def test_handle_sign_request_resolves_pin_locally_and_signs() -> None:
    signer = _FakeSigner()
    req = SignRequest(request_id="r1", pdf_bytes_b64=base64.b64encode(b"PDF").decode())

    resp = handle_sign_request(req, signer, pin_resolver=lambda: "1234")

    assert resp.success
    assert base64.b64decode(resp.signed_pdf_b64) == b"SIGNED:PDF"
    assert resp.signed_at is not None
    assert resp.cert_valid_until == date(2027, 1, 1)
    assert signer.seen_pin == "1234"  # PIN came from the local resolver, not the request


def test_handle_sign_request_maps_errors_to_response() -> None:
    class _Boom(SigningService):
        def sign_pdf(self, *a, **k):  # noqa: ANN001, ANN002, ANN003, ANN201
            raise RuntimeError("token ausente")

    req = SignRequest(request_id="r2", pdf_bytes_b64=base64.b64encode(b"PDF").decode())
    resp = handle_sign_request(req, _Boom(), pin_resolver=lambda: "x")

    assert resp.success is False
    assert "token ausente" in (resp.error or "")


def test_ws_sign_round_trip_signs_via_agent(monkeypatch):
    """WebSocket accepts a SignRequest and returns a real signed response."""
    monkeypatch.setattr(local_agent, "agent_signer", lambda: _FakeSigner())
    monkeypatch.setenv("JURIS_AGENT_PIN", "1234")
    client = TestClient(app)
    token = get_signing_token()
    with client.websocket_connect(f"/ws/sign?token={token}") as ws:
        request = SignRequest(request_id="test-001", pdf_bytes_b64=base64.b64encode(b"PDF").decode())
        ws.send_text(request.model_dump_json())
        response = SignResponse.model_validate_json(ws.receive_text())
        assert response.request_id == "test-001"
        assert response.success is True
        assert base64.b64decode(response.signed_pdf_b64) == b"SIGNED:PDF"


def test_ws_sign_handles_invalid_json():
    """WebSocket handles malformed JSON gracefully."""
    client = TestClient(app)
    token = get_signing_token()
    with client.websocket_connect(f"/ws/sign?token={token}") as ws:
        ws.send_text("not valid json")
        data = ws.receive_text()
        response = SignResponse.model_validate_json(data)
        assert response.success is False
        assert response.request_id == "unknown"


def test_ws_sign_handles_missing_fields():
    """WebSocket handles JSON missing required fields."""
    client = TestClient(app)
    token = get_signing_token()
    with client.websocket_connect(f"/ws/sign?token={token}") as ws:
        ws.send_text(json.dumps({"not_a_field": "value"}))
        data = ws.receive_text()
        response = SignResponse.model_validate_json(data)
        assert response.success is False


def test_ws_sign_rejects_missing_token():
    """WebSocket rejects connection when no auth token is provided."""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect("/ws/sign"):
        pass  # should never reach here

    assert exc_info.value.code == 4001


def test_ws_sign_rejects_invalid_token():
    """WebSocket rejects connection when the auth token is invalid."""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect("/ws/sign?token=wrong-token"):
        pass  # should never reach here

    assert exc_info.value.code == 4001


def test_sign_request_schema_validation():
    """SignRequest validates correctly."""
    req = SignRequest(request_id="r1", pdf_bytes_b64="AAAA")
    assert req.field_name == "AdvogadoSignature"


def test_sign_response_schema():
    """SignResponse serializes correctly."""
    resp = SignResponse(request_id="r1", success=True, signed_pdf_b64="BBBB")
    data = json.loads(resp.model_dump_json())
    assert data["request_id"] == "r1"
    assert data["success"] is True


def test_validate_local_agent_host_allows_loopback() -> None:
    """Loopback host is accepted for the local agent."""
    assert validate_local_agent_host("127.0.0.1") == "127.0.0.1"
    assert validate_local_agent_host("localhost") == "127.0.0.1"


def test_validate_local_agent_host_rejects_non_loopback() -> None:
    """Non-loopback host bindings are rejected."""
    with pytest.raises(ValueError, match="must bind to 127.0.0.1"):
        validate_local_agent_host("192.168.1.10")
