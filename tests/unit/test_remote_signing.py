"""Tests for the Remote signing service — the split-trust client (ADR-0015)."""

from __future__ import annotations

import base64
from datetime import UTC, date, datetime

import pytest

from juris.api.ws_schemas import SignRequest, SignResponse
from juris.signing.remote import RemoteSigningService


class _FakeTransport:
    """Captures the request and returns a canned response."""

    def __init__(self, response: SignResponse) -> None:
        self.response = response
        self.sent: SignRequest | None = None

    def send(self, request: SignRequest) -> SignResponse:
        self.sent = request
        # echo the request_id as the real agent does
        return self.response.model_copy(update={"request_id": request.request_id})


def _ok_response() -> SignResponse:
    return SignResponse(
        request_id="x",
        success=True,
        signed_pdf_b64=base64.b64encode(b"SIGNED-PDF").decode(),
        signer_name="Dra. Ana Advogada",
        signer_cpf="12345678900",
        signed_pdf_hash="deadbeef",
        signed_at=datetime(2026, 6, 29, 12, 0, tzinfo=UTC),
        cert_valid_until=date(2027, 1, 1),
    )


def test_forwards_pdf_and_maps_response_to_signing_result() -> None:
    transport = _FakeTransport(_ok_response())
    service = RemoteSigningService(transport)

    result = service.sign_pdf(b"UNSIGNED-PDF", pin="9999", field_name="MyField")

    assert result.signed_pdf == b"SIGNED-PDF"
    assert result.signer_name == "Dra. Ana Advogada"
    assert result.signer_cpf == "12345678900"
    assert result.signed_pdf_hash == "deadbeef"
    assert transport.sent is not None
    assert base64.b64decode(transport.sent.pdf_bytes_b64) == b"UNSIGNED-PDF"
    assert transport.sent.field_name == "MyField"


def test_pin_is_never_sent_to_the_cloud() -> None:
    """Split-trust: the A3 PIN is resolved at the agent, never forwarded."""
    transport = _FakeTransport(_ok_response())
    RemoteSigningService(transport).sign_pdf(b"PDF", pin="secret-pin-1234")

    assert transport.sent is not None
    assert "secret-pin-1234" not in transport.sent.model_dump_json()


def test_raises_on_agent_failure() -> None:
    transport = _FakeTransport(SignResponse(request_id="x", success=False, error="token ausente"))
    with pytest.raises(RuntimeError, match="token ausente"):
        RemoteSigningService(transport).sign_pdf(b"PDF", pin="9999")


def test_raises_on_request_id_mismatch() -> None:
    bad = SignResponse(request_id="WRONG", success=True, signed_pdf_b64="")

    class _MismatchTransport:
        def send(self, request: SignRequest) -> SignResponse:
            return bad  # does not echo the request_id

    with pytest.raises(RuntimeError, match="correlaciona"):
        RemoteSigningService(_MismatchTransport()).sign_pdf(b"PDF", pin="9999")
