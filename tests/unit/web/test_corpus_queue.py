"""Tests for pilot-directed corpus queue."""

from __future__ import annotations

from juris.web.corpus_queue import (
    append_accepted_source,
    corpus_candidates,
    coverage_report,
    list_accepted_sources,
    mark_reingested,
)
from juris.web.pilot_feedback import append_feedback


def test_candidates_sources_coverage_and_reingest(tmp_path) -> None:
    append_feedback(
        tmp_path,
        {
            "numero_cnj": "0001234-56.2026.8.13.0001",
            "output_dir": "juris-out/CASE",
            "time_saved_minutes": 20,
            "mode_used": "rascunho",
            "citations_accepted": 1,
            "citations_rejected": 0,
            "missing_source": "inteiro teor STJ",
            "deadline_or_analysis_error": "",
            "perceived_utility": 5,
            "corpus_usable": True,
            "notes": "usar acórdão",
        },
    )

    assert corpus_candidates(tmp_path)[0]["accepted"] is False

    source = append_accepted_source(
        tmp_path,
        {
            "numero_cnj": "0001234-56.2026.8.13.0001",
            "title": "REsp teste",
            "source_url": "https://example.test/acordao",
            "source_date": "2026-06-30",
            "source_type": "acordao_publicado",
            "tribunal": "STJ",
            "area": "civel",
            "tema": "cobranca",
            "status": "vigente",
            "source_text": "inteiro teor aprovado",
            "notes": "",
        },
    )

    sources = list_accepted_sources(tmp_path)
    assert sources[0]["content_sha256"]
    assert sources[0]["reingest_status"] == "pending"
    assert corpus_candidates(tmp_path)[0]["accepted"] is True

    coverage = coverage_report(tmp_path)
    assert coverage["accepted_count"] == 1
    assert coverage["coverage"]["tribunal"]["STJ"] == 1
    assert coverage["pending_reingest"][0]["id"] == source["id"]

    updated = mark_reingested(tmp_path, str(source["id"]))
    assert updated is not None
    assert updated["reingest_status"] == "done"
    assert coverage_report(tmp_path)["pending_reingest"] == []
