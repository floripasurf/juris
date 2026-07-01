"""Tests for pilot-directed corpus queue."""

from __future__ import annotations

import hashlib
import stat

from juris.web.corpus_queue import (
    append_accepted_source,
    corpus_candidates,
    coverage_report,
    list_accepted_sources,
    mark_reingested,
    reingest_pending_sources,
)
from juris.web.pilot_feedback import append_feedback


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


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
    assert _mode(tmp_path / "corpus-sources.jsonl") == 0o600
    assert _mode(tmp_path / "corpus-source-text") == 0o700
    assert _mode(tmp_path / str(sources[0]["source_text_path"])) == 0o600
    assert corpus_candidates(tmp_path)[0]["accepted"] is True

    coverage = coverage_report(tmp_path)
    assert coverage["accepted_count"] == 1
    assert coverage["coverage"]["tribunal"]["STJ"] == 1
    assert coverage["pending_reingest"][0]["id"] == source["id"]

    updated = mark_reingested(tmp_path, str(source["id"]))
    assert updated is not None
    assert updated["reingest_status"] == "done"
    assert coverage_report(tmp_path)["pending_reingest"] == []


def test_append_source_rejects_malformed_explicit_hash(tmp_path) -> None:
    try:
        append_accepted_source(
            tmp_path,
            {
                "numero_cnj": "0001234",
                "title": "Fonte",
                "source_url": "https://example.test",
                "source_date": "2026-06-30",
                "source_type": "acordao_publicado",
                "tribunal": "STJ",
                "area": "civel",
                "tema": "cobranca",
                "content_sha256": "not-a-hash",
            },
        )
    except ValueError as exc:
        assert "SHA-256" in str(exc)
    else:
        raise AssertionError("hash explícito malformado deveria falhar")


def test_append_source_rejects_hash_that_does_not_match_text(tmp_path) -> None:
    try:
        append_accepted_source(
            tmp_path,
            {
                "numero_cnj": "0001234",
                "title": "Fonte",
                "source_url": "https://example.test",
                "source_date": "2026-06-30",
                "source_type": "acordao_publicado",
                "tribunal": "STJ",
                "area": "civel",
                "tema": "cobranca",
                "content_sha256": "0" * 64,
                "source_text": "texto aprovado",
            },
        )
    except ValueError as exc:
        assert "não confere" in str(exc)
    else:
        raise AssertionError("hash divergente deveria falhar")


def test_append_source_rejects_duplicate_content_hash(tmp_path) -> None:
    text = "texto aprovado"
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    payload = {
        "numero_cnj": "0001234",
        "title": "Fonte",
        "source_url": "https://example.test",
        "source_date": "2026-06-30",
        "source_type": "acordao_publicado",
        "tribunal": "STJ",
        "area": "civel",
        "tema": "cobranca",
        "source_text": text,
    }

    append_accepted_source(tmp_path, payload)

    try:
        append_accepted_source(tmp_path, {**payload, "title": "Fonte duplicada", "content_sha256": content_hash})
    except ValueError as exc:
        assert "mesmo content_sha256" in str(exc)
    else:
        raise AssertionError("fonte duplicada deveria falhar")


def test_append_source_sanitizes_system_metadata_and_url_fragment(tmp_path) -> None:
    source = append_accepted_source(
        tmp_path,
        {
            "id": "attacker-id",
            "created_at": "1900-01-01T00:00:00+00:00",
            "content_sha256": "",
            "reingest_status": "done",
            "reingested_at": "1900-01-01T00:00:00+00:00",
            "source_text_path": "../../escape.txt",
            "numero_cnj": "0001234",
            "title": "Fonte",
            "source_url": "https://example.test/acordao#local-fragment",
            "source_date": "2026-06-30",
            "source_type": "acordao_publicado",
            "tribunal": "STJ",
            "area": "civel",
            "tema": "cobranca",
            "source_text": "texto aprovado",
        },
    )

    assert source["id"] != "attacker-id"
    assert source["created_at"] != "1900-01-01T00:00:00+00:00"
    assert source["reingest_status"] == "pending"
    assert "reingested_at" not in source
    assert source["source_text_path"] != "../../escape.txt"
    assert source["source_url"] == "https://example.test/acordao"


def test_append_source_rejects_local_or_credentialed_source_url(tmp_path) -> None:
    payload = {
        "numero_cnj": "0001234",
        "title": "Fonte",
        "source_date": "2026-06-30",
        "source_type": "acordao_publicado",
        "tribunal": "STJ",
        "area": "civel",
        "tema": "cobranca",
        "source_text": "texto aprovado",
    }

    for source_url in ("file:///Users/advogado/acordao.pdf", "https://user:secret@example.test/acordao"):
        try:
            append_accepted_source(tmp_path, {**payload, "source_url": source_url})
        except ValueError as exc:
            assert "source_url" in str(exc)
        else:
            raise AssertionError("source_url local ou com credencial deveria falhar")


def test_reingest_pending_sources_writes_repertory_chunks(tmp_path) -> None:
    source = append_accepted_source(
        tmp_path,
        {
            "numero_cnj": "0001234-56.2026.8.13.0001",
            "title": "Acórdão aprovado",
            "source_url": "https://example.test/acordao",
            "source_date": "2026-06-30",
            "source_type": "acordao_publicado",
            "tribunal": "STJ",
            "area": "civel",
            "tema": "cobranca",
            "status": "vigente",
            "source_text": "EMENTA. Cobrança. Prova documental. VOTO. Recurso provido.",
            "notes": "",
        },
    )
    repertory = tmp_path / "repertory.db"

    report = reingest_pending_sources(tmp_path, repertory)

    assert report.processed == 1
    assert report.chunks >= 1
    assert report.errors == []
    assert coverage_report(tmp_path)["pending_reingest"] == []

    import sqlite3

    with sqlite3.connect(repertory) as conn:
        row = conn.execute("SELECT source_id, metadata FROM chunks LIMIT 1").fetchone()
    assert row[0] == f"pilot-{source['id']}"
    assert "content_sha256" in row[1]


def test_reingest_pending_sources_sanitizes_internal_errors(tmp_path, monkeypatch) -> None:
    append_accepted_source(
        tmp_path,
        {
            "numero_cnj": "0001234-56.2026.8.13.0001",
            "title": "Acórdão aprovado",
            "source_url": "https://example.test/acordao",
            "source_date": "2026-06-30",
            "source_type": "acordao_publicado",
            "tribunal": "STJ",
            "area": "civel",
            "tema": "cobranca",
            "status": "vigente",
            "source_text": "EMENTA. Cobrança. VOTO.",
        },
    )

    import juris.repertory.chunking as chunking

    def _boom(_fonte):
        raise RuntimeError("sqlite /var/private/repertory.db token=abc pin=1234")

    monkeypatch.setattr(chunking, "chunk_fonte", _boom)

    report = reingest_pending_sources(tmp_path, tmp_path / "repertory.db")

    assert report.processed == 0
    assert report.errors
    assert "Falha ao reingerir" in report.errors[0]["error"]
    assert "token=abc" not in report.errors[0]["error"]
    assert "pin=1234" not in report.errors[0]["error"]
    assert "/var/private/repertory.db" not in report.errors[0]["error"]
