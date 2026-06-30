"""Pilot feedback capture and export."""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_FILENAME = "pilot-feedback.jsonl"


def feedback_path(root: Path) -> Path:
    return root / _FILENAME


def append_feedback(root: Path, payload: dict[str, object]) -> dict[str, object]:
    """Append one structured pilot feedback record under the tenant root."""
    root.mkdir(parents=True, exist_ok=True)
    record = {
        "id": uuid.uuid4().hex,
        "created_at": datetime.now(UTC).isoformat(),
        **payload,
    }
    path = feedback_path(root)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record


def list_feedback(root: Path) -> list[dict[str, object]]:
    path = feedback_path(root)
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            records.append(data)
    records.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    return records


def export_feedback_json(root: Path) -> str:
    return json.dumps({"feedback": list_feedback(root)}, ensure_ascii=False, indent=2)


def export_feedback_csv(root: Path) -> str:
    records = list_feedback(root)
    fields = [
        "id",
        "created_at",
        "numero_cnj",
        "output_dir",
        "time_saved_minutes",
        "mode_used",
        "citations_accepted",
        "citations_rejected",
        "missing_source",
        "deadline_or_analysis_error",
        "perceived_utility",
        "corpus_usable",
        "notes",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for record in records:
        writer.writerow(_csv_record(record))
    return buffer.getvalue()


def summarize_feedback(root: Path) -> dict[str, object]:
    """Aggregate pilot feedback into product/commercial signals."""
    records = list_feedback(root)
    total_cases = len(records)
    total_time_saved = sum(_int_value(r.get("time_saved_minutes")) for r in records)
    utility_values = [_int_value(r.get("perceived_utility")) for r in records if r.get("perceived_utility") is not None]
    citations_accepted = sum(_int_value(r.get("citations_accepted")) for r in records)
    citations_rejected = sum(_int_value(r.get("citations_rejected")) for r in records)
    corpus_candidates = [r for r in records if bool(r.get("corpus_usable"))]

    return {
        "total_cases": total_cases,
        "total_time_saved_minutes": total_time_saved,
        "average_time_saved_minutes": round(total_time_saved / total_cases, 1) if total_cases else 0.0,
        "average_utility": round(sum(utility_values) / len(utility_values), 2) if utility_values else 0.0,
        "mode_counts": _counts(records, "mode_used"),
        "citations": {
            "accepted": citations_accepted,
            "rejected": citations_rejected,
            "acceptance_rate": round(citations_accepted / (citations_accepted + citations_rejected), 3)
            if citations_accepted + citations_rejected
            else None,
        },
        "prioritized_gaps": _prioritized_gaps(records),
        "corpus_candidates": [
            {
                "numero_cnj": r.get("numero_cnj"),
                "output_dir": r.get("output_dir"),
                "missing_source": r.get("missing_source"),
                "notes": r.get("notes"),
            }
            for r in corpus_candidates
        ],
    }


def compare_feedback_runs(root: Path) -> dict[str, object]:
    """Compare first vs latest feedback for cases run more than once."""
    grouped: dict[str, list[dict[str, object]]] = {}
    for record in sorted(list_feedback(root), key=lambda r: str(r.get("created_at", ""))):
        cnj = str(record.get("numero_cnj") or "").strip()
        if not cnj:
            continue
        grouped.setdefault(cnj, []).append(record)

    comparisons: list[dict[str, object]] = []
    for cnj, records in grouped.items():
        if len(records) < 2:
            continue
        first = records[0]
        latest = records[-1]
        first_rate = _citation_acceptance(first)
        latest_rate = _citation_acceptance(latest)
        comparisons.append(
            {
                "numero_cnj": cnj,
                "runs": len(records),
                "first_created_at": first.get("created_at"),
                "latest_created_at": latest.get("created_at"),
                "delta_time_saved_minutes": _int_value(latest.get("time_saved_minutes"))
                - _int_value(first.get("time_saved_minutes")),
                "delta_utility": _int_value(latest.get("perceived_utility"))
                - _int_value(first.get("perceived_utility")),
                "delta_citation_acceptance": None
                if first_rate is None or latest_rate is None
                else round(latest_rate - first_rate, 3),
                "remaining_missing_source": latest.get("missing_source"),
                "remaining_error": latest.get("deadline_or_analysis_error"),
            }
        )

    improved = [
        c
        for c in comparisons
        if _int_value(c.get("delta_time_saved_minutes")) > 0
        or _int_value(c.get("delta_utility")) > 0
        or (c.get("delta_citation_acceptance") is not None and float(c["delta_citation_acceptance"]) > 0)
    ]
    return {
        "compared_cases": len(comparisons),
        "improved_cases": len(improved),
        "comparisons": comparisons,
    }


def export_feedback_report_markdown(root: Path) -> str:
    """Markdown report for pilot review and commercial follow-up."""
    summary = summarize_feedback(root)
    citations = summary["citations"]
    assert isinstance(citations, dict)
    gaps = summary["prioritized_gaps"]
    candidates = summary["corpus_candidates"]
    assert isinstance(gaps, list)
    assert isinstance(candidates, list)

    lines = [
        "# Relatório do Piloto Juris",
        "",
        "## Métricas",
        "",
        f"- Casos avaliados: {summary['total_cases']}",
        f"- Tempo economizado total: {summary['total_time_saved_minutes']} min",
        f"- Tempo economizado médio: {summary['average_time_saved_minutes']} min/caso",
        f"- Utilidade média: {summary['average_utility']}/5",
        f"- Citações aceitas/rejeitadas: {citations.get('accepted', 0)}/{citations.get('rejected', 0)}",
    ]
    rate = citations.get("acceptance_rate")
    if rate is not None:
        lines.append(f"- Taxa de aceitação de citações: {round(float(rate) * 100)}%")

    lines.extend(["", "## Lacunas priorizadas", ""])
    if gaps:
        for gap in gaps:
            cases = ", ".join(str(c) for c in gap.get("cases", []) if c)
            suffix = f" ({cases})" if cases else ""
            lines.append(
                f"- [{gap.get('kind')}] {gap.get('label')} — {gap.get('count')} caso(s){suffix}"
            )
    else:
        lines.append("- Nenhuma lacuna registrada.")

    lines.extend(["", "## Casos aproveitáveis para corpus", ""])
    if candidates:
        for candidate in candidates:
            note = candidate.get("missing_source") or candidate.get("notes") or "sem nota"
            lines.append(f"- {candidate.get('numero_cnj')} — {note}")
    else:
        lines.append("- Nenhum caso marcado como aproveitável.")

    lines.extend(
        [
            "",
            "## Próxima decisão",
            "",
            "- Validar se o tempo economizado e a utilidade média sustentam o preço do piloto.",
            "- Priorizar ingestão das lacunas de corpus mais recorrentes.",
            "- Separar problemas de corpus de problemas de UX/análise antes da próxima rodada.",
        ]
    )
    return "\n".join(lines) + "\n"


def _int_value(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _counts(records: list[dict[str, object]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = str(record.get(key) or "").strip()
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _citation_acceptance(record: dict[str, object]) -> float | None:
    accepted = _int_value(record.get("citations_accepted"))
    rejected = _int_value(record.get("citations_rejected"))
    total = accepted + rejected
    if total == 0:
        return None
    return round(accepted / total, 3)


def _prioritized_gaps(records: list[dict[str, object]]) -> list[dict[str, object]]:
    buckets: dict[str, dict[str, object]] = {}
    for record in records:
        for kind, field in (
            ("corpus", "missing_source"),
            ("analysis", "deadline_or_analysis_error"),
        ):
            value = str(record.get(field) or "").strip()
            if not value:
                continue
            key = f"{kind}:{value.lower()}"
            bucket = buckets.setdefault(
                key,
                {"kind": kind, "label": value, "count": 0, "cases": []},
            )
            bucket["count"] = _int_value(bucket["count"]) + 1
            cases = bucket["cases"]
            if isinstance(cases, list):
                cases.append(record.get("numero_cnj"))
    return sorted(
        buckets.values(),
        key=lambda item: (-_int_value(item.get("count")), str(item.get("kind")), str(item.get("label"))),
    )


def _csv_record(record: dict[str, Any]) -> dict[str, object]:
    out = dict(record)
    out["corpus_usable"] = "true" if record.get("corpus_usable") else "false"
    return out
