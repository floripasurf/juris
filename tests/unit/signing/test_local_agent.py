"""Tests for the local agent — signing handler + WebSocket endpoint (ADR-0015)."""
from __future__ import annotations

import base64
import json
import threading
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


class _CaptureLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def warning(self, event: str, **kwargs: object) -> None:
        self.events.append((event, kwargs))


def test_health_endpoint():
    """Health returns ok status."""
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    # Validate against schema
    HealthResponse.model_validate(data)


def test_browser_pairing_starts_relay_agent_from_allowed_origin(monkeypatch) -> None:
    """The Causia web app can pair a running loopback agent without terminal usage."""
    seen: dict[str, str] = {}
    called = threading.Event()

    def fake_run_relay_agent(url: str, token: str, tenant_id: str) -> None:
        seen.update({"url": url, "token": token, "tenant_id": tenant_id})
        called.set()

    monkeypatch.setattr(local_agent, "run_relay_agent", fake_run_relay_agent)
    client = TestClient(app, client=("127.0.0.1", 50000))

    response = client.post(
        "/pair-relay",
        headers={"origin": "https://causia.com.br", "host": "127.0.0.1:8765"},
        json={
            "relay_url": "wss://causia.com.br/ws/agent-relay",
            "tenant_id": "trial_abc123",
            "agent_token": "relay-token",
        },
    )

    assert response.status_code == 202
    assert response.headers["access-control-allow-origin"] == "https://causia.com.br"
    assert called.wait(timeout=1)
    assert seen == {
        "url": "wss://causia.com.br/ws/agent-relay",
        "token": "relay-token",
        "tenant_id": "trial_abc123",
    }


def test_browser_pairing_preflight_allows_private_network_request() -> None:
    """Chrome's private-network preflight must pass before the cloud page calls localhost."""
    client = TestClient(app, client=("127.0.0.1", 50000))

    response = client.options(
        "/pair-relay",
        headers={
            "origin": "https://causia.com.br",
            "host": "127.0.0.1:8765",
            "access-control-request-method": "POST",
            "access-control-request-private-network": "true",
        },
    )

    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == "https://causia.com.br"
    assert response.headers["access-control-allow-private-network"] == "true"


def test_browser_pairing_rejects_foreign_origin(monkeypatch) -> None:
    """A random page open in the browser cannot pair itself with the local agent."""
    called = False

    def fake_run_relay_agent(url: str, token: str, tenant_id: str) -> None:  # noqa: ARG001
        nonlocal called
        called = True

    monkeypatch.setattr(local_agent, "run_relay_agent", fake_run_relay_agent)
    client = TestClient(app, client=("127.0.0.1", 50000))

    response = client.post(
        "/pair-relay",
        headers={"origin": "https://evil.example", "host": "127.0.0.1:8765"},
        json={
            "relay_url": "wss://causia.com.br/ws/agent-relay",
            "tenant_id": "trial_abc123",
            "agent_token": "relay-token",
        },
    )

    assert response.status_code == 403
    assert called is False


def test_local_setup_page_is_served_only_on_loopback() -> None:
    client = TestClient(app, client=("127.0.0.1", 50000))

    response = client.get("/setup", headers={"host": "127.0.0.1:8765"})

    assert response.status_code == 200
    assert "credentials-form" in response.text
    assert "não são enviadas ao servidor" in response.text
    assert "Voltar ao Causia" in response.text
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_local_credentials_are_stored_from_causia_page(monkeypatch) -> None:
    import juris.core.credentials as credentials

    stored: dict[str, str] = {}
    monkeypatch.setattr(credentials, "store_credential", lambda key, value: stored.__setitem__(key, value))
    client = TestClient(app, client=("127.0.0.1", 50000))

    response = client.post(
        "/credentials",
        headers={"origin": "https://causia.com.br", "host": "127.0.0.1:8765"},
        json={"cpf": "076.710.396-32", "senha": "senha-pje", "pin": "1234", "tribunal": "TJMG"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://causia.com.br"
    assert response.json()["status"] == "ok"
    assert "senha-pje" not in response.text
    assert "1234" not in response.text
    assert stored == {
        "agent_cpf": "07671039632",
        "agent_tribunal": "tjmg",
        "mni_tjmg_07671039632": "senha-pje",
        "token_pin": "1234",
    }


def test_local_credentials_reject_blank_secrets(monkeypatch) -> None:
    import juris.core.credentials as credentials

    stored: dict[str, str] = {}
    monkeypatch.setattr(credentials, "store_credential", lambda key, value: stored.__setitem__(key, value))
    client = TestClient(app, client=("127.0.0.1", 50000))

    response = client.post(
        "/credentials",
        headers={"origin": "https://causia.com.br", "host": "127.0.0.1:8765"},
        json={"cpf": "076.710.396-32", "senha": "   ", "pin": "1234", "tribunal": "TJMG"},
    )

    assert response.status_code == 400
    assert "Senha PJe" in response.json()["detail"]
    assert stored == {}


def test_local_credentials_preflight_allows_private_network_request() -> None:
    client = TestClient(app, client=("127.0.0.1", 50000))

    response = client.options(
        "/credentials",
        headers={
            "origin": "https://causia.com.br",
            "host": "127.0.0.1:8765",
            "access-control-request-method": "POST",
            "access-control-request-private-network": "true",
        },
    )

    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == "https://causia.com.br"
    assert response.headers["access-control-allow-private-network"] == "true"


def test_local_credentials_status_reports_readiness_without_secrets(monkeypatch) -> None:
    monkeypatch.setattr(local_agent, "local_credentials_configured", lambda: True)
    client = TestClient(app, client=("127.0.0.1", 50000))

    response = client.get(
        "/credentials/status",
        headers={"origin": "https://causia.com.br", "host": "127.0.0.1:8765"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://causia.com.br"
    assert response.json() == {"configured": True}


def test_local_credentials_status_rejects_incomplete_stored_values(monkeypatch) -> None:
    import juris.core.credentials as credentials

    values = {
        "agent_cpf": "07671039632",
        "agent_tribunal": "tjmg",
        "mni_tjmg_07671039632": "   ",
        "token_pin": "1234",
    }
    monkeypatch.delenv("JURIS_AGENT_CPF", raising=False)
    monkeypatch.delenv("JURIS_AGENT_SENHA", raising=False)
    monkeypatch.delenv("JURIS_AGENT_PIN", raising=False)
    monkeypatch.delenv("JURIS_AGENT_TRIBUNAL", raising=False)
    monkeypatch.setattr(credentials, "get_credential", lambda key: values.get(key))
    client = TestClient(app, client=("127.0.0.1", 50000))

    response = client.get(
        "/credentials/status",
        headers={"origin": "https://causia.com.br", "host": "127.0.0.1:8765"},
    )

    assert response.status_code == 200
    assert response.json() == {"configured": False}


def test_local_credentials_reject_foreign_origin(monkeypatch) -> None:
    import juris.core.credentials as credentials

    stored: dict[str, str] = {}
    monkeypatch.setattr(credentials, "store_credential", lambda key, value: stored.__setitem__(key, value))
    client = TestClient(app, client=("127.0.0.1", 50000))

    response = client.post(
        "/credentials",
        headers={"origin": "https://evil.example", "host": "127.0.0.1:8765"},
        json={"cpf": "07671039632", "senha": "senha-pje", "pin": "1234", "tribunal": "tjmg"},
    )

    assert response.status_code == 403
    assert stored == {}


def test_default_credentials_resolver_uses_local_secure_store(monkeypatch) -> None:
    import juris.core.credentials as credentials

    values = {
        "agent_cpf": "07671039632",
        "agent_tribunal": "tjmg",
        "mni_tjmg_07671039632": "senha-pje",
        "token_pin": "1234",
    }
    monkeypatch.delenv("JURIS_AGENT_CPF", raising=False)
    monkeypatch.delenv("JURIS_AGENT_SENHA", raising=False)
    monkeypatch.delenv("JURIS_AGENT_PIN", raising=False)
    monkeypatch.delenv("JURIS_AGENT_TRIBUNAL", raising=False)
    monkeypatch.setattr(credentials, "get_credential", lambda key: values.get(key))

    assert local_agent._default_credentials_resolver() == ("07671039632", "senha-pje", "1234")


def test_default_pin_resolver_uses_local_secure_store(monkeypatch) -> None:
    import juris.core.credentials as credentials

    monkeypatch.delenv("JURIS_AGENT_PIN", raising=False)
    monkeypatch.setattr(credentials, "get_credential", lambda key: "1234" if key == "token_pin" else None)

    assert local_agent._default_pin_resolver() == "1234"


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
    assert "Falha ao assinar" in (resp.error or "")


def test_handle_sign_request_does_not_leak_internal_error() -> None:
    class _Boom(SigningService):
        def sign_pdf(self, *a, **k):  # noqa: ANN001, ANN002, ANN003, ANN201
            raise RuntimeError("pkcs11 /var/private/token token=abc pin=1234")

    req = SignRequest(request_id="r2", pdf_bytes_b64=base64.b64encode(b"PDF").decode())
    resp = handle_sign_request(req, _Boom(), pin_resolver=lambda: "x")

    assert resp.success is False
    assert "token=abc" not in (resp.error or "")
    assert "pin=1234" not in (resp.error or "")
    assert "/var/private/token" not in (resp.error or "")


def test_handle_sign_request_sanitizes_local_agent_log(monkeypatch) -> None:
    capture = _CaptureLogger()
    monkeypatch.setattr(local_agent, "logger", capture)

    class _Boom(SigningService):
        def sign_pdf(self, *a, **k):  # noqa: ANN001, ANN002, ANN003, ANN201
            raise RuntimeError("pkcs11 /var/private/token token=abc pin=1234 cpf=076.710.396-32")

    req = SignRequest(request_id="r-log", pdf_bytes_b64=base64.b64encode(b"PDF").decode())
    resp = handle_sign_request(req, _Boom(), pin_resolver=lambda: "x")

    assert resp.success is False
    assert capture.events
    error = str(capture.events[0][1]["error"])
    assert "token=abc" not in error
    assert "pin=1234" not in error
    assert "076.710.396-32" not in error
    assert "/var/private/token" not in error
    assert "token=<redacted>" in error
    assert "pin=<redacted>" in error
    assert "<local-path>" in error


def test_ws_sign_round_trip_signs_via_agent(monkeypatch):
    """WebSocket accepts a SignRequest and returns a real signed response."""
    monkeypatch.setattr(local_agent, "agent_signer", lambda: _FakeSigner())
    monkeypatch.setenv("JURIS_AGENT_PIN", "1234")
    client = TestClient(app)
    token = get_signing_token()
    with client.websocket_connect("/ws/sign", headers={"x-agent-token": token}) as ws:
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
    with client.websocket_connect("/ws/sign", headers={"x-agent-token": token}) as ws:
        ws.send_text("not valid json")
        data = ws.receive_text()
        response = SignResponse.model_validate_json(data)
        assert response.success is False
        assert response.request_id == "unknown"


def test_ws_sign_handles_missing_fields():
    """WebSocket handles JSON missing required fields."""
    client = TestClient(app)
    token = get_signing_token()
    with client.websocket_connect("/ws/sign", headers={"x-agent-token": token}) as ws:
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
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(
        "/ws/sign", headers={"x-agent-token": "wrong-token"}
    ):
        pass  # should never reach here

    assert exc_info.value.code == 4001


def test_ws_sign_rejects_query_token_by_default(monkeypatch) -> None:
    """Tokens in URLs are rejected unless the temporary migration flag is explicit."""
    monkeypatch.delenv("JURIS_AGENT_ALLOW_QUERY_TOKEN", raising=False)
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(
        f"/ws/sign?token={get_signing_token()}"
    ):
        pass

    assert exc_info.value.code == 4001


def test_ws_sign_accepts_query_token_only_when_legacy_flag_is_enabled(monkeypatch) -> None:
    """Compatibility mode is opt-in and should be removed after old clients migrate."""
    monkeypatch.setenv("JURIS_AGENT_ALLOW_QUERY_TOKEN", "1")
    monkeypatch.setattr(local_agent, "agent_signer", lambda: _FakeSigner())
    monkeypatch.setenv("JURIS_AGENT_PIN", "1234")
    client = TestClient(app)

    with client.websocket_connect(f"/ws/sign?token={get_signing_token()}") as ws:
        request = SignRequest(request_id="legacy-1", pdf_bytes_b64=base64.b64encode(b"PDF").decode())
        ws.send_text(request.model_dump_json())
        response = SignResponse.model_validate_json(ws.receive_text())

    assert response.success is True


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


def test_agent_health_reports_token_readiness() -> None:
    from juris import __version__
    from juris.api.local_agent import TokenStatus, agent_health

    resp = agent_health(token_probe=lambda: TokenStatus(connected=True, cert_valid_until=date(2027, 1, 1)))
    assert resp.status == "ok"
    assert resp.token_connected is True
    assert resp.cert_valid_until == date(2027, 1, 1)
    assert resp.version == __version__  # the real package version, not the schema default


def test_agent_health_degrades_when_token_absent() -> None:
    from juris.api.local_agent import TokenStatus, agent_health

    resp = agent_health(token_probe=lambda: TokenStatus(connected=False, cert_valid_until=None))
    assert resp.token_connected is False
    assert resp.cert_valid_until is None


def test_health_endpoint_uses_agent_health(monkeypatch) -> None:
    from juris.api import local_agent
    from juris.api.local_agent import TokenStatus

    monkeypatch.setattr(
        local_agent, "_default_token_probe", lambda: TokenStatus(connected=True, cert_valid_until=date(2030, 5, 1))
    )
    client = TestClient(local_agent.app)
    data = client.get("/health").json()
    assert data["token_connected"] is True
    assert data["cert_valid_until"] == "2030-05-01"


def test_ws_sign_accepts_token_via_header(monkeypatch):
    """Token in the x-agent-token header (preferred — not in the URL) is accepted."""
    monkeypatch.setattr(local_agent, "agent_signer", lambda: _FakeSigner())
    monkeypatch.setenv("JURIS_AGENT_PIN", "1234")
    client = TestClient(app)
    with client.websocket_connect("/ws/sign", headers={"x-agent-token": get_signing_token()}) as ws:
        req = SignRequest(request_id="h-1", pdf_bytes_b64=base64.b64encode(b"PDF").decode())
        ws.send_text(req.model_dump_json())
        resp = SignResponse.model_validate_json(ws.receive_text())
        assert resp.success is True


def test_ws_sign_rejects_foreign_origin(monkeypatch):
    """A browser page (foreign Origin) can't reach the loopback agent even with the token."""
    client = TestClient(app)
    token = get_signing_token()
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(
        "/ws/sign",
        headers={"origin": "https://evil.example", "host": "127.0.0.1:8765", "x-agent-token": token},
    ):
        pass


def test_ws_sign_allows_loopback_origin(monkeypatch):
    """A same-origin (loopback) request with the token is allowed."""
    monkeypatch.setattr(local_agent, "agent_signer", lambda: _FakeSigner())
    monkeypatch.setenv("JURIS_AGENT_PIN", "1234")
    client = TestClient(app)
    with client.websocket_connect(
        "/ws/sign",
        headers={"origin": "http://127.0.0.1:8765", "host": "127.0.0.1:8765", "x-agent-token": get_signing_token()},
    ) as ws:
        req = SignRequest(request_id="lo-1", pdf_bytes_b64=base64.b64encode(b"PDF").decode())
        ws.send_text(req.model_dump_json())
        assert SignResponse.model_validate_json(ws.receive_text()).success is True
