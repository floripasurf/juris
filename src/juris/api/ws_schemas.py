"""Pydantic WebSocket message schemas for the local signing agent."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class ConsentSummarySchema(BaseModel):
    """What was shown to the lawyer before signing."""
    numero_cnj: str
    tribunal: str
    tipo_documento: str
    prazo_status: str  # PrazoStatus value
    prazo_deadline: date | None = None
    cert_cn: str
    cert_valid_until: date
    page_count: int
    pdf_size_kb: int
    citation_count: int = 0
    full_preview_opened: bool = False
    consent_elapsed_seconds: float = 0.0


class SignRequest(BaseModel):
    """Request to sign a PDF. The PIN is NEVER carried — resolved at the agent."""
    request_id: str
    tenant_id: str = "public"
    pdf_bytes_b64: str  # Base64-encoded PDF
    field_name: str = "AdvogadoSignature"
    consent_summary: ConsentSummarySchema | None = None


class SignResponse(BaseModel):
    """Response after signing attempt."""
    request_id: str
    success: bool
    signed_pdf_b64: str | None = None
    signer_name: str | None = None
    signer_cpf: str | None = None
    signed_pdf_hash: str | None = None
    signed_at: datetime | None = None
    cert_valid_until: date | None = None
    error: str | None = None


class AgentRequest(BaseModel):
    """Unified envelope for token operations forwarded to the local agent (ADR-0015).

    ``operation`` is one of ``mni.consultar_processo`` / ``mni.consultar_avisos`` /
    ``mni.consultar_teor``; ``payload`` carries the operation-specific arguments.
    Sensitive material (PIN) is resolved at the agent and never travels in here.
    """
    request_id: str
    tenant_id: str = "public"
    operation: str
    payload: dict[str, object] = {}


class AgentResponse(BaseModel):
    """Reply to an :class:`AgentRequest` — ``payload`` is the serialised result."""
    request_id: str
    success: bool
    payload: dict[str, object] | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    token_connected: bool
    cert_valid_until: date | None = None
    version: str = "0.1.0"


class CompletionRequest(BaseModel):
    """Request relayed to the lawyer's browser LLM session (ADR-0018).

    Carries a (de-identified) prompt across the Native Messaging bridge to the
    Chrome extension driving Claude.ai/ChatGPT.
    """
    request_id: str
    prompt: str
    system: str | None = None
    model: str = "claude.ai (browser session)"


class CompletionResponse(BaseModel):
    """Reply from the browser LLM session."""
    request_id: str
    success: bool
    content: str | None = None
    error: str | None = None
