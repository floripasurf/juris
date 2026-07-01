"""Filing orchestrator — end-to-end pipeline: render → preflight → sign → file → receipt."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from juris.core.observability import get_logger
from juris.core.sanitize import safe_error_text
from juris.mni.operations.peticionamento import FilingReceipt
from juris.persistence.audit import AuditLog
from juris.persistence.filing_receipt import FilingReceiptStore
from juris.signing.pades import CertStatus, PAdESSigner, SigningResult
from juris.signing.pdf_renderer import render_petition_pdf
from juris.signing.preflight import PrazoStatus, PreflightResult, run_preflight

if TYPE_CHECKING:
    from juris.mni.auth import AuthStrategy

logger = get_logger(__name__)

_PUBLIC_RENDER_ERROR = "Render failed: falha operacional ao gerar o PDF."
_PUBLIC_SIGNING_ERROR = "Signing failed: falha operacional ao assinar o PDF."
_PUBLIC_SUBMIT_ERROR = "MNI filing failed: falha operacional ao protocolar no MNI."


@dataclass(frozen=True, slots=True)
class FilingRequest:
    """Input for a filing operation."""

    numero_cnj: str
    tribunal: str
    tipo_documento: str
    draft_markdown: str
    tipo_peticao: str
    cpf: str
    senha: str
    skip_preflight: bool = False
    dry_run: bool = False
    prazo_override: str | None = None


@dataclass(frozen=True, slots=True)
class ChainOfCustody:
    """SHA-256 hashes at each pipeline stage for integrity verification."""

    pdf_hash: str
    signed_pdf_hash: str
    submitted_payload_hash: str
    receipt_hash: str


@dataclass(frozen=True, slots=True)
class ConsentSummary:
    """What was shown to the lawyer before signing. Captured in audit."""

    numero_cnj: str
    tribunal: str
    tipo_documento: str
    prazo_status: PrazoStatus
    prazo_deadline: date | None
    cert_cn: str
    cert_valid_until: date
    page_count: int
    pdf_size_kb: int
    citation_count: int
    full_preview_opened: bool
    consent_elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class FilingResult:
    """Result of a filing operation."""

    success: bool
    receipt: FilingReceipt | None
    signing_result: SigningResult | None
    preflight: PreflightResult | None
    audit_entry_ids: list[str]
    chain_of_custody: ChainOfCustody | None = None
    error: str | None = None


def _sha256_hex(data: bytes | str) -> str:
    """Compute SHA-256 hex digest."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _count_citations(markdown: str) -> int:
    """Count legal citations in draft markdown (heuristic)."""
    import re

    patterns = [
        r"(?:art\.|artigo)\s+\d+",
        r"(?:STF|STJ|TST|TJ\w+)\s*[,\s]+\w+",
        r"Súmula\s+\d+",
        r"RE\s+\d+",
        r"REsp\s+\d+",
        r"ADI\s+\d+",
    ]
    count = 0
    for pat in patterns:
        count += len(re.findall(pat, markdown, re.IGNORECASE))
    return count


def _public_error_for_step(step: str) -> str:
    return {
        "render": _PUBLIC_RENDER_ERROR,
        "sign": _PUBLIC_SIGNING_ERROR,
        "submit": _PUBLIC_SUBMIT_ERROR,
    }[step]


class FilingOrchestrator:
    """Orchestrates the full filing pipeline.

    Pipeline: render → preflight → consent → sign → file → receipt.
    """

    def __init__(
        self,
        signer: PAdESSigner,
        audit: AuditLog,
        receipt_store: FilingReceiptStore,
        mni_client_factory: Callable[[str, AuthStrategy], Any],
        mni_auth: AuthStrategy,
    ) -> None:
        self._signer = signer
        self._audit = audit
        self._receipt_store = receipt_store
        self._mni_client_factory = mni_client_factory
        self._mni_auth = mni_auth

    async def file(self, request: FilingRequest) -> FilingResult:
        """Execute the full filing pipeline.

        Args:
            request: Filing parameters.

        Returns:
            FilingResult with success status, receipt, and audit trail.
        """
        audit_ids: list[str] = []

        # 1. Render Markdown → PDF
        try:
            render_result = render_petition_pdf(
                markdown_text=request.draft_markdown,
                case_number=request.numero_cnj,
                petition_type=request.tipo_peticao,
                metadata={"tribunal": request.tribunal, "tipo_documento": request.tipo_documento},
            )
        except (ValueError, RuntimeError) as exc:
            logger.warning(
                "filing_render_error",
                numero_cnj=request.numero_cnj,
                error=safe_error_text(exc),
                exception_type=exc.__class__.__name__,
            )
            public_error = _public_error_for_step("render")
            entry = self._audit.log(
                "filing.render_error",
                actor="system",
                details={"error": public_error},
                processo_cnj=request.numero_cnj,
            )
            return FilingResult(
                success=False,
                receipt=None,
                signing_result=None,
                preflight=None,
                audit_entry_ids=[entry.entry_id],
                error=public_error,
            )

        entry = self._audit.log(
            "filing.render",
            actor="system",
            details={
                "pdf_hash": render_result.pdf_hash,
                "page_count": render_result.page_count,
                "size_bytes": len(render_result.pdf_bytes),
            },
            processo_cnj=request.numero_cnj,
        )
        audit_ids.append(entry.entry_id)

        # 2. Run preflight checks
        preflight: PreflightResult | None = None
        cert_status: CertStatus | None = None

        if not request.skip_preflight:
            cert_status = self._signer.validate_cert()

            preflight = run_preflight(
                numero_cnj=request.numero_cnj,
                tribunal=request.tribunal,
                tipo_documento=request.tipo_documento,
                pdf_bytes=render_result.pdf_bytes,
                cert_status=cert_status,
                prazo_override=request.prazo_override,
            )

            entry = self._audit.log(
                "filing.preflight",
                actor="system",
                details={
                    "passed": preflight.passed,
                    "blocker_count": len(preflight.blockers),
                    "prazo_status": preflight.prazo_status.value,
                    "checks": [
                        {"name": c.name, "passed": c.passed, "severity": c.severity}
                        for c in preflight.checks
                    ],
                },
                processo_cnj=request.numero_cnj,
            )
            audit_ids.append(entry.entry_id)

            if not preflight.passed:
                blocker_msgs = "; ".join(c.message for c in preflight.blockers)
                return FilingResult(
                    success=False,
                    receipt=None,
                    signing_result=None,
                    preflight=preflight,
                    audit_entry_ids=audit_ids,
                    error=f"Preflight blocked: {blocker_msgs}",
                )

        # 3. Build ConsentSummary
        prazo_status = preflight.prazo_status if preflight else PrazoStatus.UNKNOWN
        prazo_deadline: date | None = None
        consent_start = time.monotonic()

        consent = ConsentSummary(
            numero_cnj=request.numero_cnj,
            tribunal=request.tribunal,
            tipo_documento=request.tipo_documento,
            prazo_status=prazo_status,
            prazo_deadline=prazo_deadline,
            cert_cn=cert_status.cn if cert_status else "",
            cert_valid_until=cert_status.valid_until if cert_status else date.min,
            page_count=render_result.page_count,
            pdf_size_kb=len(render_result.pdf_bytes) // 1024,
            citation_count=_count_citations(request.draft_markdown),
            full_preview_opened=False,
            consent_elapsed_seconds=0.0,
        )

        # Dry-run: stop here
        if request.dry_run:
            entry = self._audit.log(
                "filing.dryrun",
                actor=f"user:{request.cpf}",
                details={
                    "numero_cnj": request.numero_cnj,
                    "tribunal": request.tribunal,
                    "tipo_documento": request.tipo_documento,
                    "prazo_status": prazo_status.value,
                    "page_count": render_result.page_count,
                    "pdf_size_kb": consent.pdf_size_kb,
                    "pdf_hash": render_result.pdf_hash,
                },
                processo_cnj=request.numero_cnj,
            )
            audit_ids.append(entry.entry_id)

            return FilingResult(
                success=True,
                receipt=None,
                signing_result=None,
                preflight=preflight,
                audit_entry_ids=audit_ids,
                error=None,
            )

        # 4. Audit consent
        consent_elapsed = time.monotonic() - consent_start
        consent = ConsentSummary(
            numero_cnj=consent.numero_cnj,
            tribunal=consent.tribunal,
            tipo_documento=consent.tipo_documento,
            prazo_status=consent.prazo_status,
            prazo_deadline=consent.prazo_deadline,
            cert_cn=consent.cert_cn,
            cert_valid_until=consent.cert_valid_until,
            page_count=consent.page_count,
            pdf_size_kb=consent.pdf_size_kb,
            citation_count=consent.citation_count,
            full_preview_opened=consent.full_preview_opened,
            consent_elapsed_seconds=consent_elapsed,
        )

        entry = self._audit.log(
            "filing.consent",
            actor=f"user:{request.cpf}",
            details={
                "numero_cnj": consent.numero_cnj,
                "tribunal": consent.tribunal,
                "tipo_documento": consent.tipo_documento,
                "prazo_status": consent.prazo_status.value,
                "cert_cn": consent.cert_cn,
                "page_count": consent.page_count,
                "pdf_size_kb": consent.pdf_size_kb,
                "citation_count": consent.citation_count,
                "consent_elapsed_seconds": consent.consent_elapsed_seconds,
            },
            processo_cnj=request.numero_cnj,
        )
        audit_ids.append(entry.entry_id)

        # 5. Sign PDF
        try:
            signing_result = self._signer.sign(render_result.pdf_bytes)
        except Exception as exc:
            logger.warning(
                "filing_sign_error",
                numero_cnj=request.numero_cnj,
                error=safe_error_text(exc),
                exception_type=exc.__class__.__name__,
            )
            public_error = _public_error_for_step("sign")
            entry = self._audit.log(
                "filing.sign_error",
                actor=f"user:{request.cpf}",
                details={"error": public_error},
                processo_cnj=request.numero_cnj,
            )
            audit_ids.append(entry.entry_id)
            return FilingResult(
                success=False,
                receipt=None,
                signing_result=None,
                preflight=preflight,
                audit_entry_ids=audit_ids,
                error=public_error,
            )

        entry = self._audit.log(
            "filing.sign",
            actor=f"user:{request.cpf}",
            details={
                "signer_name": signing_result.signer_name,
                "signer_cpf": signing_result.signer_cpf,
                "pdf_hash": signing_result.pdf_hash,
                "signed_pdf_hash": signing_result.signed_pdf_hash,
            },
            processo_cnj=request.numero_cnj,
        )
        audit_ids.append(entry.entry_id)

        # 6. Prepare receipt storage
        pending_path = self._receipt_store.prepare(
            numero_cnj=request.numero_cnj,
            signed_pdf=signing_result.signed_pdf,
            render_hash=render_result.pdf_hash,
        )

        # 7. File via MNI
        try:
            mni_client = self._mni_client_factory(request.tribunal, self._mni_auth)
            from juris.mni.operations.peticionamento import entregar_manifestacao

            # Compute submitted payload hash before sending
            submitted_payload_hash = _sha256_hex(signing_result.signed_pdf)

            receipt = entregar_manifestacao(
                client=mni_client,
                id_manifestante=request.cpf,
                senha_manifestante=request.senha,
                numero_processo=request.numero_cnj,
                signed_pdf_bytes=signing_result.signed_pdf,
                tipo_documento=request.tipo_documento,
            )
        except Exception as exc:
            logger.warning(
                "filing_submit_error",
                numero_cnj=request.numero_cnj,
                tribunal=request.tribunal,
                error=safe_error_text(exc),
                exception_type=exc.__class__.__name__,
            )
            public_error = _public_error_for_step("submit")
            entry = self._audit.log(
                "filing.submit_error",
                actor=f"user:{request.cpf}",
                details={"error": public_error, "pending_receipt": True},
                processo_cnj=request.numero_cnj,
            )
            audit_ids.append(entry.entry_id)
            return FilingResult(
                success=False,
                receipt=None,
                signing_result=signing_result,
                preflight=preflight,
                audit_entry_ids=audit_ids,
                error=public_error,
            )

        entry = self._audit.log(
            "filing.submit",
            actor=f"user:{request.cpf}",
            details={
                "sucesso": receipt.sucesso,
                "protocolo": receipt.protocolo,
                "mensagem": receipt.mensagem,
            },
            processo_cnj=request.numero_cnj,
        )
        audit_ids.append(entry.entry_id)

        if not receipt.sucesso:
            return FilingResult(
                success=False,
                receipt=receipt,
                signing_result=signing_result,
                preflight=preflight,
                audit_entry_ids=audit_ids,
                error=f"MNI rejected: {receipt.mensagem}",
            )

        # 8. Confirm receipt storage
        receipt_id = self._receipt_store.confirm(
            pending_path=pending_path,
            receipt=receipt,
            submitted_payload_hash=submitted_payload_hash,
            tribunal=request.tribunal,
            tipo_documento=request.tipo_documento,
        )

        # Build chain of custody
        receipt_data_json = json.dumps(
            {
                "sucesso": receipt.sucesso,
                "mensagem": receipt.mensagem,
                "protocolo": receipt.protocolo,
                "data_recebimento": (
                    receipt.data_recebimento.isoformat() if receipt.data_recebimento else None
                ),
                "numero_processo": receipt.numero_processo,
                "pdf_hash": receipt.pdf_hash,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        receipt_hash = _sha256_hex(receipt_data_json)

        chain = ChainOfCustody(
            pdf_hash=render_result.pdf_hash,
            signed_pdf_hash=signing_result.signed_pdf_hash,
            submitted_payload_hash=submitted_payload_hash,
            receipt_hash=receipt_hash,
        )

        entry = self._audit.log(
            "filing.receipt",
            actor="system",
            details={
                "receipt_id": receipt_id,
                "protocolo": receipt.protocolo,
                "chain_of_custody": {
                    "pdf_hash": chain.pdf_hash,
                    "signed_pdf_hash": chain.signed_pdf_hash,
                    "submitted_payload_hash": chain.submitted_payload_hash,
                    "receipt_hash": chain.receipt_hash,
                },
            },
            processo_cnj=request.numero_cnj,
        )
        audit_ids.append(entry.entry_id)

        if request.prazo_override:
            self._audit.log(
                "filing.prazo_override",
                actor=f"user:{request.cpf}",
                details={"justificativa": request.prazo_override},
                processo_cnj=request.numero_cnj,
            )

        logger.info(
            "filing_complete",
            numero_cnj=request.numero_cnj,
            protocolo=receipt.protocolo,
            receipt_id=receipt_id,
        )

        return FilingResult(
            success=True,
            receipt=receipt,
            signing_result=signing_result,
            preflight=preflight,
            audit_entry_ids=audit_ids,
            chain_of_custody=chain,
        )
