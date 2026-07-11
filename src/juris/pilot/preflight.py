"""Pilot preflight — single-command readiness check for a lawyer-facing demo.

Consolidates the manual checklist in `docs/pilot/smoke-test-notes.md` (§0) into
one operator-runnable command. Each check is read-only, deterministic, and
returns one of four states:

- ``PASS`` — verified ready
- ``WARN`` — non-blocking concern (e.g. only one LLM provider available)
- ``FAIL`` — would break a real-source `juris demo` run; abort the session
- ``SKIP`` — check is informational and was not exercised this run

The aggregate exit policy is:

- any ``FAIL`` → command exits non-zero (operator must abort and remediate)
- only ``WARN`` / ``PASS`` → command exits zero

This matches the safety gate inside `juris demo`: anything that would let a
real-source run silently produce a draft without verifiable citations is a
``FAIL``, never a ``WARN``. Non-product checks (Ollama vs. cloud, CNJ format,
disk space) are ``WARN`` so the operator can decide.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from juris.repertory.readiness import (
    detect_legacy_path,
    read_status,
    resolve_repertory_path,
)

FULL_TEXT_SOURCE_TYPES = frozenset({"acordao_publicado", "acordao_landmark", "precedente_local"})
DEFAULT_MIN_FULL_TEXT_CHUNKS = 25
ENV_MIN_FULL_TEXT_CHUNKS = "JURIS_MIN_FULL_TEXT_CHUNKS"


class CheckStatus(StrEnum):
    """Per-check verdict."""

    PASS = "pass"  # noqa: S105 — verdict label, not a credential
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Outcome of a single preflight check."""

    name: str
    status: CheckStatus
    message: str
    remediation: str | None = None
    details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Serializable form for `--json` CLI output."""
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "remediation": self.remediation,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class PreflightReport:
    """Aggregate result of all preflight checks."""

    checks: tuple[CheckResult, ...]

    @property
    def is_ready(self) -> bool:
        """True iff no check ended in ``FAIL``."""
        return not any(c.status is CheckStatus.FAIL for c in self.checks)

    @property
    def has_warnings(self) -> bool:
        """True iff at least one check is ``WARN`` (informational)."""
        return any(c.status is CheckStatus.WARN for c in self.checks)

    def to_dict(self) -> dict[str, object]:
        """Serializable form for `--json` CLI output."""
        return {
            "is_ready": self.is_ready,
            "has_warnings": self.has_warnings,
            "checks": [c.to_dict() for c in self.checks],
        }


# ---------------------------------------------------------------------------
# individual checks
# ---------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def check_repertory(*, real_source_required: bool = True) -> CheckResult:
    """Verify the corpus DB exists and meets readiness thresholds.

    Wraps :func:`juris.repertory.readiness.read_status`. A non-ready corpus is
    a ``FAIL`` when ``real_source_required`` is True (default) — running
    `juris demo --source datajud|mni` against an empty DB silently produces a
    draft with no verifiable citations, the worst lawyer-facing failure mode.

    Also surfaces a legacy-path warning when an alternate repertory exists at
    ``data/repertory.db`` while the canonical path is configured elsewhere.
    """
    canonical = resolve_repertory_path()
    status = read_status(canonical)
    legacy = detect_legacy_path(canonical=canonical)

    details: dict[str, object] = {
        "db_path": str(canonical),
        "exists": status.exists,
        "chunk_count": status.chunk_count,
        "source_count": status.source_count,
        "source_type_count": status.source_type_count,
        "min_chunks": status.min_chunks,
        "min_source_types": status.min_source_types,
        "is_ready": status.is_ready,
    }
    if legacy is not None:
        details["legacy_db_detected"] = str(legacy)

    if status.is_ready:
        msg = f"corpus pronto: {status.chunk_count} chunks em {status.source_type_count} tipos de fonte"
        if legacy is not None:
            return CheckResult(
                name="repertory",
                status=CheckStatus.WARN,
                message=msg + " (banco legado também presente)",
                remediation=(
                    f"banco legado em {legacy} pode confundir comandos antigos; "
                    "remova-o ou defina JURIS_REPERTORY_PATH se o conteúdo for "
                    "o que você quer usar"
                ),
                details=details,
            )
        return CheckResult(
            name="repertory",
            status=CheckStatus.PASS,
            message=msg,
            details=details,
        )

    reason = status.not_ready_reason or "corpus não pronto"
    if real_source_required:
        return CheckResult(
            name="repertory",
            status=CheckStatus.FAIL,
            message=reason,
            remediation=(
                "rode `juris repertory ingest` (ou aponte JURIS_REPERTORY_PATH "
                "para um banco populado) antes da sessão; sem corpus o demo "
                "produziria minuta sem citações verificáveis"
            ),
            details=details,
        )
    return CheckResult(
        name="repertory",
        status=CheckStatus.WARN,
        message=reason + " (modo fixture aceita corpus vazio)",
        details=details,
    )


def check_corpus_depth(*, min_full_text_chunks: int | None = None) -> CheckResult:
    """Warn when the public corpus is ready but still shallow.

    The regular repertory check proves the DB has enough chunks/source types to
    avoid empty retrieval. It does not prove the corpus contains full-text
    acórdãos. This separate check keeps that product limitation visible.
    """
    threshold = (
        min_full_text_chunks
        if min_full_text_chunks is not None
        else _env_int(ENV_MIN_FULL_TEXT_CHUNKS, DEFAULT_MIN_FULL_TEXT_CHUNKS)
    )
    status = read_status(resolve_repertory_path())
    breakdown = dict(status.source_type_breakdown)
    full_text_chunks = sum(count for source_type, count in breakdown.items() if source_type in FULL_TEXT_SOURCE_TYPES)
    details: dict[str, object] = {
        "db_path": str(status.db_path),
        "full_text_source_types": sorted(FULL_TEXT_SOURCE_TYPES),
        "full_text_chunks": full_text_chunks,
        "min_full_text_chunks": threshold,
        "source_type_count": status.source_type_count,
        "source_type_breakdown": breakdown,
    }
    if not status.exists or status.chunk_count == 0:
        return CheckResult(
            name="corpus_depth",
            status=CheckStatus.SKIP,
            message="corpus ausente ou vazio; profundidade não avaliada",
            details=details,
        )
    if full_text_chunks < threshold:
        return CheckResult(
            name="corpus_depth",
            status=CheckStatus.WARN,
            message=(
                f"corpus público raso: {full_text_chunks} chunk(s) de inteiro teor "
                f"(< {threshold})"
            ),
            remediation=(
                "não prometa RAG profundo de acórdãos completos; ingerir mais "
                "acórdãos publicados/landmark ou limitar a copy para súmulas, "
                "temas e teses até a escavação cobrir o domínio"
            ),
            details=details,
        )
    return CheckResult(
        name="corpus_depth",
        status=CheckStatus.PASS,
        message=f"corpus com {full_text_chunks} chunk(s) de inteiro teor",
        details=details,
    )


def _huggingface_cache_root() -> Path:
    """Resolve the active HuggingFace cache root, honoring HF env overrides."""
    explicit = os.environ.get("HF_HOME") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    if explicit:
        root = Path(explicit).expanduser()
        if root.name == "hub":
            return root
        return root / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def check_embeddings_cache(
    model_name: str = "BAAI/bge-m3",
    *,
    required: bool | None = None,
) -> CheckResult:
    """Verify the embedding model is already cached locally.

    Without a warm cache, the first `juris demo` invocation triggers a silent
    ~400MB download — bad UX in a 1h pilot session. In production, embeddings
    are a hard requirement; locally this remains a warning so development can
    exercise FTS-only paths deliberately.
    """
    if required is None:
        from juris.repertory.embeddings import embeddings_required_by_environment

        required = embeddings_required_by_environment()
    missing_status = CheckStatus.FAIL if required else CheckStatus.WARN
    cache_root = _huggingface_cache_root()
    model_dir_name = "models--" + model_name.replace("/", "--")
    model_dir = cache_root / model_dir_name

    details: dict[str, object] = {
        "cache_root": str(cache_root),
        "model_name": model_name,
        "model_dir": str(model_dir),
        "exists": model_dir.exists(),
    }

    if not model_dir.exists():
        return CheckResult(
            name="embeddings_cache",
            status=missing_status,
            message=f"modelo {model_name} não está em cache",
            remediation=(
                f'pré-aquecer com `python -c "from sentence_transformers '
                f"import SentenceTransformer; SentenceTransformer('{model_name}')\"` "
                "antes da sessão (~400MB); em produção o retrieval semântico "
                "falha fechado para não operar só com palavras-chave"
            ),
            details=details,
        )

    snapshots = model_dir / "snapshots"
    if snapshots.exists():
        revs = [p for p in snapshots.iterdir() if p.is_dir()]
        details["snapshots"] = len(revs)
        if not revs:
            return CheckResult(
                name="embeddings_cache",
                status=missing_status,
                message=f"diretório do modelo {model_name} existe mas sem snapshot",
                remediation="re-executar o pré-aquecimento (cache parcial)",
                details=details,
            )
    return CheckResult(
        name="embeddings_cache",
        status=CheckStatus.PASS,
        message=f"modelo {model_name} em cache",
        details=details,
    )


def check_ner_model(*, probe: bool = False, model_name: str | None = None) -> CheckResult:
    """Verify the LeNER-Br de-id NER model is cached (cloud-de-id path, ADR-0016).

    SKIP unless probed — only the cloud/browser de-id path needs it. Absent, the
    cloud path fails closed (won't leak names), so this is a WARN with a pre-warm
    hint rather than a hard FAIL.
    """
    if not probe:
        return CheckResult(
            name="ner_model",
            status=CheckStatus.SKIP,
            message="probe do modelo NER não solicitado (use --live para a sessão cloud)",
        )
    if model_name is None:
        from juris.core.ner import LegalNER

        model_name = LegalNER.DEFAULT_MODEL

    cache_root = _huggingface_cache_root()
    model_dir = cache_root / ("models--" + model_name.replace("/", "--"))
    snapshots = model_dir / "snapshots"
    cached = model_dir.exists() and snapshots.exists() and any(p.is_dir() for p in snapshots.iterdir())
    details: dict[str, object] = {"model_name": model_name, "model_dir": str(model_dir), "cached": cached}

    if cached:
        return CheckResult(
            name="ner_model",
            status=CheckStatus.PASS,
            message=f"modelo NER {model_name} em cache",
            details=details,
        )
    return CheckResult(
        name="ner_model",
        status=CheckStatus.WARN,
        message=f"modelo NER {model_name} não está em cache",
        remediation=(
            "pré-baixar: `uv run python -c \"from juris.core.ner import LegalNER; "
            "LegalNER().redact_entities('x')\"`. Sem ele, o caminho cloud falha "
            "fechado (não envia nomes)."
        ),
        details=details,
    )


def _ollama_reachable(url: str, *, timeout: float = 1.5) -> bool:
    """Probe Ollama ``/api/tags`` over HTTP. Returns False on any error."""
    try:
        from urllib.error import URLError
        from urllib.request import Request, urlopen

        req = Request(url.rstrip("/") + "/api/tags")  # noqa: S310 — local URL
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 — local URL
            return 200 <= int(resp.status) < 300
    except (URLError, OSError, ValueError, TimeoutError):
        return False


def check_llm_availability(
    *,
    ollama_url: str | None = None,
    anthropic_env_var: str = "ANTHROPIC_API_KEY",
    cli_cloud_provider: str | None = None,
    probe_ollama: bool = True,
) -> CheckResult:
    """Verify at least one LLM provider is reachable.

    Drafter/analyzer default to Ollama for PII; researcher uses Claude. The
    pilot needs at least one provider live. ``FAIL`` only if **neither** is
    available, since a single provider can complete a degraded but useful
    session. ``WARN`` when only one is up.
    """
    url = ollama_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")
    anthropic_key = bool(os.environ.get(anthropic_env_var))
    ollama_up = _ollama_reachable(url) if probe_ollama else False
    cli_cloud_available = bool(cli_cloud_provider and shutil.which(cli_cloud_provider))
    cloud_available = anthropic_key or cli_cloud_available

    details: dict[str, object] = {
        "ollama_url": url,
        "ollama_reachable": ollama_up,
        "anthropic_key_present": anthropic_key,
        "cli_cloud_provider": cli_cloud_provider,
        "cli_cloud_available": cli_cloud_available,
    }

    if ollama_up and cloud_available:
        return CheckResult(
            name="llm_availability",
            status=CheckStatus.PASS,
            message="Ollama acessível e provedor cloud presente",
            details=details,
        )
    if ollama_up:
        return CheckResult(
            name="llm_availability",
            status=CheckStatus.WARN,
            message="Ollama acessível; Anthropic não configurado",
            remediation=(
                "tarefas de pesquisa (não-PII) cairão no Ollama; carregue "
                f"{anthropic_env_var} se quiser respostas de pesquisa em Claude"
            ),
            details=details,
        )
    if anthropic_key:
        return CheckResult(
            name="llm_availability",
            status=CheckStatus.WARN,
            message="ANTHROPIC_API_KEY presente; Ollama indisponível",
            remediation=(
                "use cloud apenas para fixture, pesquisa pública ou contexto anonimizado; "
                "casos com PII ficam bloqueados até haver anonimização/consentimento "
                "ou backend local forte o bastante"
            ),
            details=details,
        )
    if cli_cloud_available:
        return CheckResult(
            name="llm_availability",
            status=CheckStatus.WARN,
            message=f"CLI cloud {cli_cloud_provider} disponível; Ollama indisponível",
            remediation=(
                "use apenas em sessão fixture/rascunho sem PII; casos com PII "
                "ficam bloqueados até haver anonimização/consentimento ou backend "
                "local forte o bastante"
            ),
            details=details,
        )
    return CheckResult(
        name="llm_availability",
        status=CheckStatus.FAIL,
        message="nenhum provedor de LLM disponível",
        remediation=(
            "rode `ollama serve` (PII) e/ou exporte "
            f"{anthropic_env_var} (pesquisa) ou informe --cli-cloud claude|codex "
            "(fixture sem PII) — a sessão não pode continuar sem ao menos um provedor"
        ),
        details=details,
    )


def check_output_dir_clean(out_root: Path | None) -> CheckResult:
    """Verify the per-case output directory will not collide with stale runs.

    When the operator passes ``--out``, we check that re-running the demo for
    the same CNJ would not append to a previous `audit.jsonl` (a known L3
    limitation in the runbook). ``SKIP`` when no path is given.
    """
    if out_root is None:
        return CheckResult(
            name="output_dir",
            status=CheckStatus.SKIP,
            message="caminho de saída não fornecido (informativo)",
        )
    expanded = out_root.expanduser()
    details: dict[str, object] = {"out_root": str(expanded)}

    if not expanded.exists():
        return CheckResult(
            name="output_dir",
            status=CheckStatus.PASS,
            message=f"{expanded} ainda não existe — primeiro uso",
            details=details,
        )
    try:
        children = list(expanded.iterdir())
    except OSError as exc:
        return CheckResult(
            name="output_dir",
            status=CheckStatus.WARN,
            message=f"não foi possível listar {expanded}: {exc}",
            details=details,
        )
    case_dirs = [p for p in children if p.is_dir()]
    details["existing_case_dirs"] = [p.name for p in case_dirs]
    if case_dirs:
        return CheckResult(
            name="output_dir",
            status=CheckStatus.WARN,
            message=(
                f"{expanded} já contém {len(case_dirs)} diretório(s) de caso; audit.jsonl pode acumular eventos antigos"
            ),
            remediation=(
                f"limpe `{expanded}/<numero_cnj>` ou use um --out novo antes "
                "da sessão para evitar mistura de logs de auditoria"
            ),
            details=details,
        )
    return CheckResult(
        name="output_dir",
        status=CheckStatus.PASS,
        message=f"{expanded} existe e está vazio",
        details=details,
    )


def check_disk_space(
    path: Path | None = None,
    *,
    min_free_mb: int = 500,
) -> CheckResult:
    """Verify enough free space to write demo artifacts and cache spillover."""
    target = (path or Path.cwd()).expanduser()
    while not target.exists() and target != target.parent:
        target = target.parent
    try:
        usage = shutil.disk_usage(target)
    except OSError as exc:
        return CheckResult(
            name="disk_space",
            status=CheckStatus.WARN,
            message=f"não foi possível medir espaço livre em {target}: {exc}",
        )
    free_mb = usage.free // (1024 * 1024)
    details: dict[str, object] = {
        "path": str(target),
        "free_mb": free_mb,
        "min_free_mb": min_free_mb,
    }
    if free_mb < min_free_mb:
        return CheckResult(
            name="disk_space",
            status=CheckStatus.WARN,
            message=f"espaço livre baixo: {free_mb}MB < {min_free_mb}MB",
            remediation="libere espaço antes da sessão",
            details=details,
        )
    return CheckResult(
        name="disk_space",
        status=CheckStatus.PASS,
        message=f"{free_mb}MB livres",
        details=details,
    )


# ---------------------------------------------------------------------------
# check_token (A3) — only exercised for a live MNI session
# ---------------------------------------------------------------------------


class _TokenCert(Protocol):
    @property
    def token_label(self) -> str: ...

    @property
    def not_valid_after(self) -> str: ...


def _default_token_reader() -> _TokenCert:
    # No PIN: certificates are public objects on the token.
    from juris.config import get_settings
    from juris.mni.token import extract_token_material

    return extract_token_material(get_settings().pkcs11_module)


def check_token(
    *,
    probe: bool = False,
    reader: Callable[[], _TokenCert] | None = None,
    today: date | None = None,
) -> CheckResult:
    """Verify the A3 token is connected and its certificate is valid (live MNI).

    Read-only and PIN-free. ``SKIP`` unless ``probe`` (the demo/draft pipeline
    doesn't need the token; a live ``juris connect`` does). A missing token or an
    expired certificate is ``FAIL``; expiring-soon is ``WARN``.
    """
    if not probe:
        return CheckResult(
            name="token_a3",
            status=CheckStatus.SKIP,
            message="probe do token A3 não solicitado (use --live para a sessão real)",
        )
    read = reader or _default_token_reader
    try:
        material = read()
    except Exception as exc:  # noqa: BLE001 — any failure means the token isn't ready
        from juris.core.observability import get_logger
        from juris.core.sanitize import safe_error_text

        get_logger("juris.pilot.preflight").warning(
            "preflight_token_probe_failed",
            error=safe_error_text(exc),
            exception_type=exc.__class__.__name__,
        )
        return CheckResult(
            name="token_a3",
            status=CheckStatus.FAIL,
            message="token A3 não detectado",
            remediation="Conecte o e-CPF A3 e confira o módulo PKCS#11.",
            details={"error": "token_unavailable"},
        )
    ref = today or date.today()
    try:
        expiry = date.fromisoformat(str(material.not_valid_after))
    except ValueError:
        return CheckResult(
            name="token_a3",
            status=CheckStatus.WARN,
            message=f"validade do certificado ilegível: {material.not_valid_after}",
        )
    dias = (expiry - ref).days
    if dias < 0:
        return CheckResult(
            name="token_a3",
            status=CheckStatus.FAIL,
            message=f"certificado EXPIRADO em {expiry.isoformat()}",
            remediation="Renove o e-CPF A3 antes da sessão.",
        )
    if dias < 30:
        return CheckResult(
            name="token_a3",
            status=CheckStatus.WARN,
            message=f"certificado '{material.token_label}' expira em {dias} dias ({expiry.isoformat()})",
        )
    return CheckResult(
        name="token_a3",
        status=CheckStatus.PASS,
        message=f"token '{material.token_label}' detectado, certificado válido até {expiry.isoformat()}",
    )


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------


def run_preflight(
    *,
    out_root: Path | None = None,
    real_source_required: bool = True,
    embedding_model: str = "BAAI/bge-m3",
    cli_cloud_provider: str | None = None,
    probe_ollama: bool = True,
    probe_token: bool = False,
    probe_ner: bool = False,
    embeddings_required: bool | None = None,
) -> PreflightReport:
    """Run all preflight checks and aggregate into a report.

    Args:
        out_root: Optional `--out` path to validate against stale case dirs.
        real_source_required: When True, an empty/missing corpus is ``FAIL``.
            Set False for fixture-only sessions.
        embedding_model: HuggingFace model name to look up in the cache.
        probe_ollama: Set False to skip the network probe (e.g. in tests).
        embeddings_required: Override whether missing embedding cache is a
            failure. ``None`` follows ENVIRONMENT/JURIS_REQUIRE_EMBEDDINGS.
    """
    checks = (
        check_repertory(real_source_required=real_source_required),
        check_corpus_depth(),
        check_embeddings_cache(model_name=embedding_model, required=embeddings_required),
        check_llm_availability(probe_ollama=probe_ollama, cli_cloud_provider=cli_cloud_provider),
        check_token(probe=probe_token),
        check_ner_model(probe=probe_ner),
        check_output_dir_clean(out_root),
        check_disk_space(out_root),
    )
    return PreflightReport(checks=checks)
