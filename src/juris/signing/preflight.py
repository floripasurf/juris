"""Pre-flight checks before signing and filing a petition.

Deterministic validation — no LLM calls. Runs checks on PDF validity,
certificate status, tribunal vocabulary, and prazo status before
allowing a signing+filing operation to proceed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

import httpx

from juris.core.observability import get_logger

if TYPE_CHECKING:
    from juris.prazo.engine import PrazoReport

log = get_logger(__name__)

# Maximum PDF size accepted by TJMG/TRT-2 filing systems (10 MB).
_MAX_PDF_BYTES = 10 * 1024 * 1024

# Accepted tipo_documento vocabulary per tribunal.
TRIBUNAL_TIPOS: dict[str, set[str]] = {
    "tjmg": {
        "manifestacao", "contestacao", "recurso", "peticao",
        "inicial", "contrarrazoes", "embargos", "agravo", "apelacao",
    },
    "trt2": {
        "manifestacao", "contestacao", "recurso", "peticao",
        "inicial", "contrarrazoes", "embargos", "agravo",
        "recurso_ordinario", "recurso_revista",
    },
}

# Days threshold for certificate expiry warning.
_CERT_EXPIRY_WARNING_DAYS = 30


class PrazoStatus(StrEnum):
    """Aggregated prazo status for pre-flight decision."""

    SAFE = "safe"           # > 5 days remaining
    URGENT = "urgent"       # 2-5 days remaining
    EXPIRING = "expiring"   # < 2 days remaining
    EXPIRED = "expired"     # past deadline
    UNKNOWN = "unknown"     # no prazo data available



# Re-export CertStatus from pades for convenience.
from juris.signing.pades import CertStatus  # noqa: E402


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    """Result of a single pre-flight check."""

    name: str
    passed: bool
    severity: Literal["blocker", "warning"]
    message: str
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class PreflightResult:
    """Aggregated result of all pre-flight checks."""

    passed: bool
    checks: list[PreflightCheck]
    blockers: list[PreflightCheck]
    prazo_status: PrazoStatus


def _check_pdf_not_empty(pdf_bytes: bytes) -> PreflightCheck:
    """Check that the PDF payload is not empty."""
    if not pdf_bytes:
        return PreflightCheck(
            name="pdf_not_empty",
            passed=False,
            severity="blocker",
            message="PDF vazio — nenhum conteúdo para assinar.",
            retryable=True,
        )
    return PreflightCheck(
        name="pdf_not_empty",
        passed=True,
        severity="blocker",
        message="PDF não vazio.",
    )


def _check_pdf_valid(pdf_bytes: bytes) -> PreflightCheck:
    """Check that the PDF starts with the %PDF magic bytes."""
    if not pdf_bytes.startswith(b"%PDF"):
        return PreflightCheck(
            name="pdf_valid",
            passed=False,
            severity="blocker",
            message="Arquivo não é um PDF válido (header %PDF ausente).",
            retryable=False,
        )
    return PreflightCheck(
        name="pdf_valid",
        passed=True,
        severity="blocker",
        message="PDF com header válido.",
    )


def _check_pdf_size_limit(pdf_bytes: bytes) -> PreflightCheck:
    """Check that the PDF is under the 10 MB tribunal limit."""
    size = len(pdf_bytes)
    if size > _MAX_PDF_BYTES:
        mb = size / (1024 * 1024)
        return PreflightCheck(
            name="pdf_size_limit",
            passed=False,
            severity="blocker",
            message=f"PDF excede limite de 10 MB ({mb:.1f} MB).",
            retryable=False,
        )
    return PreflightCheck(
        name="pdf_size_limit",
        passed=True,
        severity="blocker",
        message=f"PDF dentro do limite ({size} bytes).",
    )


def _check_tipo_documento(
    tipo_documento: str,
    tribunal: str,
) -> PreflightCheck:
    """Check that tipo_documento is in the tribunal's accepted vocabulary."""
    tribunal_lower = tribunal.lower()
    tipos = TRIBUNAL_TIPOS.get(tribunal_lower)

    if tipos is None:
        return PreflightCheck(
            name="tipo_documento_valid",
            passed=True,
            severity="warning",
            message=f"Tribunal '{tribunal}' sem vocabulário cadastrado — tipo não validado.",
        )

    if tipo_documento.lower() not in tipos:
        allowed = ", ".join(sorted(tipos))
        return PreflightCheck(
            name="tipo_documento_valid",
            passed=False,
            severity="blocker",
            message=(
                f"Tipo '{tipo_documento}' não aceito pelo {tribunal}. "
                f"Aceitos: {allowed}."
            ),
        )
    return PreflightCheck(
        name="tipo_documento_valid",
        passed=True,
        severity="blocker",
        message=f"Tipo '{tipo_documento}' válido para {tribunal}.",
    )


def _check_cert_valid(
    cert_status: CertStatus | None,
    today: date,
) -> PreflightCheck | None:
    """Check that the certificate is valid and not expired."""
    if cert_status is None:
        return None

    if not cert_status.valid:
        return PreflightCheck(
            name="cert_valid",
            passed=False,
            severity="blocker",
            message=f"Certificado inválido: {cert_status.error or 'motivo desconhecido'}.",
            retryable=False,
        )

    if cert_status.valid_until < today:
        return PreflightCheck(
            name="cert_valid",
            passed=False,
            severity="blocker",
            message=f"Certificado expirado em {cert_status.valid_until.isoformat()}.",
            retryable=False,
        )

    return PreflightCheck(
        name="cert_valid",
        passed=True,
        severity="blocker",
        message=f"Certificado válido até {cert_status.valid_until.isoformat()}.",
    )


def _check_cert_expiring_soon(
    cert_status: CertStatus | None,
    today: date,
) -> PreflightCheck | None:
    """Warn if the certificate expires within 30 days."""
    if cert_status is None or not cert_status.valid:
        return None

    if cert_status.valid_until < today:
        return None  # Already caught by cert_valid

    days_left = (cert_status.valid_until - today).days
    if days_left <= _CERT_EXPIRY_WARNING_DAYS:
        return PreflightCheck(
            name="cert_expiring_soon",
            passed=True,
            severity="warning",
            message=f"Certificado expira em {days_left} dia(s) ({cert_status.valid_until.isoformat()}).",
        )
    return None


def _compute_prazo_status(prazo_report: Any | None) -> PrazoStatus:
    """Compute aggregated PrazoStatus from a PrazoReport.

    Looks at the most urgent prazo's dias_uteis_restantes.
    """
    if prazo_report is None or not prazo_report.prazos:
        return PrazoStatus.UNKNOWN

    # prazos are already sorted by urgency in the engine
    most_urgent = prazo_report.prazos[0]
    dias = most_urgent.dias_uteis_restantes

    if dias < 0:
        return PrazoStatus.EXPIRED
    if dias < 2:
        return PrazoStatus.EXPIRING
    if dias <= 5:
        return PrazoStatus.URGENT
    return PrazoStatus.SAFE


def _check_prazo(
    prazo_report: Any | None,
    prazo_override: str | None,
    prazo_status: PrazoStatus,
) -> PreflightCheck | None:
    """Check prazo status and emit blocker/warning as appropriate."""
    if prazo_status == PrazoStatus.UNKNOWN or prazo_status == PrazoStatus.SAFE:
        return None

    if prazo_status == PrazoStatus.EXPIRED:
        if prazo_override:
            return PreflightCheck(
                name="prazo_status",
                passed=True,
                severity="warning",
                message=f"Prazo vencido — override aceito: {prazo_override}.",
            )
        return PreflightCheck(
            name="prazo_status",
            passed=False,
            severity="blocker",
            message="Prazo vencido — peticionamento bloqueado.",
            retryable=False,
        )

    if prazo_status == PrazoStatus.EXPIRING:
        return PreflightCheck(
            name="prazo_status",
            passed=True,
            severity="warning",
            message="Prazo expirando em menos de 2 dias úteis.",
        )

    if prazo_status == PrazoStatus.URGENT:
        return PreflightCheck(
            name="prazo_status",
            passed=True,
            severity="warning",
            message="Prazo urgente — entre 2 e 5 dias úteis restantes.",
        )

    return None


# Skew acima disto vira aviso (nunca bloqueio): timestamps PAdES e o cálculo
# "protocolei dentro do prazo?" ficam frágeis se o relógio local derivar demais.
_CLOCK_SKEW_WARN_SECONDS = 120.0


def _check_clock_skew(tribunal_url: str | None = None, *, timeout_seconds: float = 3.0) -> PreflightCheck:
    """Compara o relógio local (UTC) com o header ``Date`` do endpoint do tribunal.

    Warning-only: skew > 120s reprova o check como AVISO, sem bloquear o filing.
    Sem URL ou com tribunal inacessível/sem header ``Date``, degrada para o
    comportamento anterior (passa com aviso de indisponibilidade).

    Args:
        tribunal_url: Endpoint do tribunal para um ``HEAD`` de sondagem.
        timeout_seconds: Timeout do probe HTTP.

    Returns:
        PreflightCheck ``clock_skew`` de severidade ``warning``.
    """
    if not tribunal_url:
        return PreflightCheck(
            name="clock_skew",
            passed=True,
            severity="warning",
            message="Clock skew não verificado (URL do tribunal ausente).",
        )
    try:
        response = httpx.head(tribunal_url, timeout=timeout_seconds, follow_redirects=True)
        server_date = parsedate_to_datetime(response.headers["Date"])
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return PreflightCheck(
            name="clock_skew",
            passed=True,
            severity="warning",
            message="Clock skew indisponível (tribunal não respondeu ao probe).",
        )
    if server_date.tzinfo is None:
        server_date = server_date.replace(tzinfo=UTC)
    skew_seconds = abs((datetime.now(UTC) - server_date).total_seconds())
    if skew_seconds > _CLOCK_SKEW_WARN_SECONDS:
        return PreflightCheck(
            name="clock_skew",
            passed=False,
            severity="warning",
            message=f"Relógio local difere do tribunal em {skew_seconds:.0f}s — verifique NTP antes de protocolar.",
        )
    return PreflightCheck(
        name="clock_skew",
        passed=True,
        severity="warning",
        message=f"Clock skew ok ({skew_seconds:.0f}s).",
    )


def run_preflight(
    numero_cnj: str,
    tribunal: str,
    tipo_documento: str,
    pdf_bytes: bytes,
    cert_status: CertStatus | None = None,
    prazo_report: PrazoReport | None = None,
    prazo_override: str | None = None,
    tribunal_url: str | None = None,
) -> PreflightResult:
    """Run all pre-flight checks before signing and filing.

    Args:
        numero_cnj: CNJ case number.
        tribunal: Tribunal identifier (e.g. "tjmg", "trt2").
        tipo_documento: Document type being filed.
        pdf_bytes: Raw PDF content.
        cert_status: Optional certificate status.
        prazo_report: Optional deadline report from the prazo engine.
        prazo_override: Justificativa to override an expired prazo blocker.
        tribunal_url: Endpoint do tribunal para o probe de clock skew (opcional;
            sem ele o check de skew só avisa que não foi verificado).

    Returns:
        PreflightResult with aggregated pass/fail and individual checks.
    """
    log.info(
        "preflight_start",
        numero_cnj=numero_cnj,
        tribunal=tribunal,
        tipo_documento=tipo_documento,
        pdf_size=len(pdf_bytes),
    )

    checks: list[PreflightCheck] = []

    # PDF checks
    checks.append(_check_pdf_not_empty(pdf_bytes))
    if pdf_bytes:
        checks.append(_check_pdf_valid(pdf_bytes))
        checks.append(_check_pdf_size_limit(pdf_bytes))

    # Tipo documento
    checks.append(_check_tipo_documento(tipo_documento, tribunal))

    # Certificate checks
    today = date.today()
    cert_check = _check_cert_valid(cert_status, today)
    if cert_check is not None:
        checks.append(cert_check)

    cert_expiry_check = _check_cert_expiring_soon(cert_status, today)
    if cert_expiry_check is not None:
        checks.append(cert_expiry_check)

    # Prazo checks
    prazo_st = _compute_prazo_status(prazo_report)
    prazo_check = _check_prazo(prazo_report, prazo_override, prazo_st)
    if prazo_check is not None:
        checks.append(prazo_check)

    # Clock skew (warning-only): probes the tribunal's Date header if a URL is given.
    checks.append(_check_clock_skew(tribunal_url))

    # Aggregate
    blockers = [c for c in checks if not c.passed and c.severity == "blocker"]
    passed = len(blockers) == 0

    log.info(
        "preflight_done",
        passed=passed,
        total_checks=len(checks),
        blockers=len(blockers),
        prazo_status=prazo_st.value,
    )

    return PreflightResult(
        passed=passed,
        checks=checks,
        blockers=blockers,
        prazo_status=prazo_st,
    )
