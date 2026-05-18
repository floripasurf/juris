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
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from juris.repertory.readiness import (
    detect_legacy_path,
    read_status,
    resolve_repertory_path,
)


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
) -> CheckResult:
    """Verify the embedding model is already cached locally.

    Without a warm cache, the first `juris demo` invocation triggers a silent
    ~400MB download — bad UX in a 1h pilot session. This check is a ``WARN``,
    not a ``FAIL``: the run will succeed eventually, but the operator should
    pre-warm the cache before the lawyer arrives.
    """
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
            status=CheckStatus.WARN,
            message=f"modelo {model_name} não está em cache",
            remediation=(
                f'pré-aquecer com `python -c "from sentence_transformers '
                f"import SentenceTransformer; SentenceTransformer('{model_name}')\"` "
                "antes da sessão (~400MB); senão o primeiro `juris demo` baixa "
                "o modelo silenciosamente"
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
                status=CheckStatus.WARN,
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
                "tarefas com PII falharão sem Ollama local; rode `ollama serve` "
                "e confirme que o modelo padrão está baixado (`ollama pull qwen3`)"
            ),
            details=details,
        )
    if cli_cloud_available:
        return CheckResult(
            name="llm_availability",
            status=CheckStatus.WARN,
            message=f"CLI cloud {cli_cloud_provider} disponível; Ollama indisponível",
            remediation=(
                "use apenas em sessão fixture/rascunho sem PII; tarefas com PII "
                "seguem exigindo Ollama local"
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
# orchestrator
# ---------------------------------------------------------------------------


def run_preflight(
    *,
    out_root: Path | None = None,
    real_source_required: bool = True,
    embedding_model: str = "BAAI/bge-m3",
    cli_cloud_provider: str | None = None,
    probe_ollama: bool = True,
) -> PreflightReport:
    """Run all preflight checks and aggregate into a report.

    Args:
        out_root: Optional `--out` path to validate against stale case dirs.
        real_source_required: When True, an empty/missing corpus is ``FAIL``.
            Set False for fixture-only sessions.
        embedding_model: HuggingFace model name to look up in the cache.
        probe_ollama: Set False to skip the network probe (e.g. in tests).
    """
    checks = (
        check_repertory(real_source_required=real_source_required),
        check_embeddings_cache(model_name=embedding_model),
        check_llm_availability(probe_ollama=probe_ollama, cli_cloud_provider=cli_cloud_provider),
        check_output_dir_clean(out_root),
        check_disk_space(out_root),
    )
    return PreflightReport(checks=checks)
