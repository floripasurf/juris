"""Tests for the lawyer-side local agent handlers (ADR-0015 Phase 2)."""

from __future__ import annotations

import base64
from datetime import UTC, date, datetime

from juris.api.local_agent import handle_sign_request
from juris.api.ws_schemas import SignRequest
from juris.signing.pades import SigningResult
from juris.signing.service import SigningService


class _FakeSigner(SigningService):
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


def test_handle_sign_request_resolves_pin_locally_and_signs() -> None:
    signer = _FakeSigner()
    req = SignRequest(request_id="r1", pdf_bytes_b64=base64.b64encode(b"PDF").decode())

    resp = handle_sign_request(req, signer, pin_resolver=lambda: "1234")

    assert resp.success
    assert resp.request_id == "r1"
    assert base64.b64decode(resp.signed_pdf_b64) == b"SIGNED:PDF"
    assert resp.signer_name == "Dra. Ana"
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
    assert resp.request_id == "r2"
    assert "token ausente" in (resp.error or "")


def test_ws_sign_round_trip_with_testclient(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from juris.api import local_agent
    from juris.api.ws_schemas import SignResponse

    monkeypatch.setattr(local_agent, "agent_signer", lambda: _FakeSigner())
    monkeypatch.setenv("JURIS_AGENT_PIN", "1234")
    client = TestClient(local_agent.app)
    token = local_agent.get_signing_token()

    with client.websocket_connect(f"/ws/sign?token={token}") as ws:
        req = SignRequest(request_id="r1", pdf_bytes_b64=base64.b64encode(b"PDF").decode())
        ws.send_text(req.model_dump_json())
        resp = SignResponse.model_validate_json(ws.receive_text())

    assert resp.success
    assert resp.request_id == "r1"
    assert base64.b64decode(resp.signed_pdf_b64) == b"SIGNED:PDF"


def test_ws_sign_rejects_bad_token() -> None:
    import pytest
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from juris.api import local_agent

    client = TestClient(local_agent.app)
    with (
        pytest.raises(WebSocketDisconnect),  # closed 4001 before accept
        client.websocket_connect("/ws/sign?token=wrong") as ws,
    ):
        ws.receive_text()
