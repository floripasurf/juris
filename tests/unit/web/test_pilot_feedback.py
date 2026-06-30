"""Tests for structured pilot feedback capture."""

from __future__ import annotations

import json

from juris.web.pilot_feedback import (
    append_feedback,
    export_feedback_csv,
    export_feedback_json,
    export_feedback_report_markdown,
    list_feedback,
    summarize_feedback,
)


def test_append_list_and_export_feedback(tmp_path) -> None:
    record = append_feedback(
        tmp_path,
        {
            "numero_cnj": "0001234-56.2026.8.13.0001",
            "output_dir": "juris-out/CASE",
            "time_saved_minutes": 42,
            "mode_used": "rascunho",
            "citations_accepted": 3,
            "citations_rejected": 1,
            "missing_source": "STJ inteiro teor",
            "deadline_or_analysis_error": "",
            "perceived_utility": 5,
            "corpus_usable": True,
            "notes": "útil",
        },
    )

    records = list_feedback(tmp_path)
    assert records[0]["id"] == record["id"]
    assert records[0]["time_saved_minutes"] == 42

    exported = json.loads(export_feedback_json(tmp_path))
    assert exported["feedback"][0]["numero_cnj"] == "0001234-56.2026.8.13.0001"

    csv_text = export_feedback_csv(tmp_path)
    assert "numero_cnj" in csv_text
    assert "STJ inteiro teor" in csv_text
    report = export_feedback_report_markdown(tmp_path)
    assert "# Relatório do Piloto Juris" in report
    assert "STJ inteiro teor" in report

    summary = summarize_feedback(tmp_path)
    assert summary["total_cases"] == 1
    assert summary["total_time_saved_minutes"] == 42
    assert summary["average_utility"] == 5
    assert summary["citations"]["acceptance_rate"] == 0.75
    assert summary["prioritized_gaps"][0]["label"] == "STJ inteiro teor"
    assert summary["corpus_candidates"][0]["numero_cnj"] == "0001234-56.2026.8.13.0001"
