"""Tests for the local agent WebSocket skeleton."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from juris.api.local_agent import app, get_signing_token, validate_local_agent_host
from juris.api.ws_schemas import HealthResponse, SignRequest, SignResponse


def test_health_endpoint():
    """Health returns ok status."""
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    # Validate against schema
    HealthResponse.model_validate(data)


def test_ws_sign_accepts_valid_request():
    """WebSocket accepts a valid SignRequest and responds with SignResponse."""
    client = TestClient(app)
    token = get_signing_token()
    with client.websocket_connect(f"/ws/sign?token={token}") as ws:
        request = SignRequest(
            request_id="test-001",
            pdf_bytes_b64="JVBERi0xLjQK",  # minimal base64
            field_name="AdvogadoSignature",
        )
        ws.send_text(request.model_dump_json())
        data = ws.receive_text()
        response = SignResponse.model_validate_json(data)
        assert response.request_id == "test-001"
        assert response.success is False  # skeleton returns not-implemented
        assert "Sprint 11" in (response.error or "")


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
