"""Workbench aggregation for the lawyer's daily console."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from juris.web.jsonutil import ensure_dict, ensure_list
from juris.web.processos_service import PrazoView, ProcessoView

_CRITICAL_URGENCY = {"critica", "crítica", "alta", "urgente"}


def build_workbench(
    *,
    processos: list[ProcessoView],
    prazos: list[PrazoView],
    out_root: Path,
    max_items: int = 5,
) -> dict[str, object]:
    """Build the daily queues shown by the web console."""
    runs = _recent_run_manifests(out_root, max_items=max_items * 4)
    latest_by_cnj = _latest_run_by_cnj(runs)
    return {
        "critical_deadlines": _critical_deadlines(prazos, latest_by_cnj=latest_by_cnj, max_items=max_items),
        "recent_movements": _recent_movements(processos, latest_by_cnj=latest_by_cnj, max_items=max_items),
        "draft_ready": _draft_ready(processos, latest_by_cnj=latest_by_cnj, max_items=max_items),
        "blocked_cases": _blocked_cases(runs, max_items=max_items),
        "recent_artifacts": _recent_artifacts(runs, max_items=max_items),
    }


def _latest_run_by_cnj(runs: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    latest: dict[str, dict[str, object]] = {}
    for run in runs:
        cnj = run.get("numero_cnj")
        if isinstance(cnj, str) and cnj and cnj not in latest:
            latest[cnj] = run
    return latest


def _critical_deadlines(
    prazos: list[PrazoView], *, latest_by_cnj: dict[str, dict[str, object]], max_items: int
) -> list[dict[str, object]]:
    selected = [
        p
        for p in prazos
        if (p.urgencia or "").strip().lower() in _CRITICAL_URGENCY
    ]
    selected.sort(key=lambda p: (p.data_limite is None, p.data_limite or datetime.max))
    return [
        {
            "numero_cnj": p.numero_cnj,
            "data_limite": p.data_limite.isoformat() if p.data_limite else None,
            "urgencia": p.urgencia,
            "rule_nome": p.rule_nome,
            "tipo_acao": p.tipo_acao,
            "latest_run": latest_by_cnj.get(p.numero_cnj),
        }
        for p in selected[:max_items]
    ]


def _recent_movements(
    processos: list[ProcessoView], *, latest_by_cnj: dict[str, dict[str, object]], max_items: int
) -> list[dict[str, object]]:
    selected = [p for p in processos if p.last_sync_at is not None]
    selected.sort(key=lambda p: p.last_sync_at or datetime.min, reverse=True)  # filtered: never None
    return [_processo_payload(p, latest_run=latest_by_cnj.get(p.numero_cnj)) for p in selected[:max_items]]


def _draft_ready(
    processos: list[ProcessoView], *, latest_by_cnj: dict[str, dict[str, object]], max_items: int
) -> list[dict[str, object]]:
    selected = sorted(
        processos,
        key=lambda p: (p.prazos_pendentes, p.proximo_prazo is not None, p.last_sync_at is not None),
        reverse=True,
    )
    return [_processo_payload(p, latest_run=latest_by_cnj.get(p.numero_cnj)) for p in selected[:max_items]]


def _processo_payload(p: ProcessoView, *, latest_run: dict[str, object] | None) -> dict[str, object]:
    return {
        "numero_cnj": p.numero_cnj,
        "tribunal": p.tribunal,
        "classe": p.classe,
        "assunto": p.assunto,
        "last_sync_at": p.last_sync_at.isoformat() if p.last_sync_at else None,
        "prazos_pendentes": p.prazos_pendentes,
        "proximo_prazo": p.proximo_prazo.isoformat() if p.proximo_prazo else None,
        "proximo_prazo_urgencia": p.proximo_prazo_urgencia,
        "latest_run": latest_run,
    }


def _recent_run_manifests(out_root: Path, *, max_items: int) -> list[dict[str, object]]:
    root = out_root.resolve()
    if not root.exists():
        return []
    paths = sorted(
        root.glob("*/run-manifest.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    runs: list[dict[str, object]] = []
    for path in paths[:max_items]:
        if not _is_regular_file_under(path, root):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        runs.append(_run_payload(payload, path.parent))
    return runs


def _run_payload(manifest: dict[str, Any], case_dir: Path) -> dict[str, object]:
    request = ensure_dict(manifest.get("request"))
    draft = ensure_dict(manifest.get("draft"))
    reviewer = ensure_dict(manifest.get("reviewer"))
    case_summary = ensure_dict(manifest.get("case_summary"))
    artifacts = ensure_list(manifest.get("artifacts"))
    return {
        "numero_cnj": request.get("numero_cnj") or case_summary.get("numero_cnj"),
        "tribunal": request.get("tribunal"),
        "source": request.get("source"),
        "output_mode": manifest.get("output_mode"),
        "finished_at": manifest.get("finished_at"),
        "output_dir": str(case_dir),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "grounding_status": draft.get("grounding_status"),
        "grounding_blocked_reason": draft.get("grounding_blocked_reason"),
        "review": {
            "critical": reviewer.get("critical_count", 0),
            "important": reviewer.get("important_count", 0),
            "suggestion": reviewer.get("suggestion_count", 0),
        },
        "succeeded": manifest.get("succeeded"),
        "degraded": manifest.get("degraded"),
    }


def _blocked_cases(runs: list[dict[str, object]], *, max_items: int) -> list[dict[str, object]]:
    selected = [r for r in runs if r.get("grounding_status") == "blocked"]
    return selected[:max_items]


def _recent_artifacts(runs: list[dict[str, object]], *, max_items: int) -> list[dict[str, object]]:
    return runs[:max_items]


def _is_regular_file_under(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return resolved.is_relative_to(root) and resolved.is_file()
