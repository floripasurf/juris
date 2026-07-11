"""Tests for LGPD/pilot data erasure operations."""

from __future__ import annotations

from pathlib import Path

import pytest

from juris.ops.erasure import build_tenant_erasure_plan, execute_tenant_erasure
from juris.repertory.chunking import DocumentChunk
from juris.repertory.corpus.models import TipoFonte
from juris.repertory.vector_store import LocalFTSStore
from juris.web.connect_jobs import ConnectJobStore


def _write(path: Path, content: str = "data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _chunk(cid: str, text: str) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=cid,
        source_id=cid,
        source_type=TipoFonte.ACORDAO_PUBLICADO,
        text=text,
        metadata={},
        position=0,
    )


def test_tenant_erasure_deletes_only_selected_tenant(tmp_path: Path) -> None:
    home = tmp_path / "home"
    out = tmp_path / "out"
    jobs = home / "connect_jobs.db"
    corpus = home / "repertory.db"
    _write(home / "tenants" / "escritorio-a" / "audit.jsonl", "audit-a")
    _write(home / "tenants" / "escritorio-a" / "filings" / "cnj" / "receipt.json", "receipt-a")
    _write(home / "tenants" / "escritorio-b" / "audit.jsonl", "audit-b")
    _write(out / "tenants" / "escritorio-a" / "case-1" / "draft.md", "draft-a")
    _write(out / "tenants" / "escritorio-b" / "case-2" / "draft.md", "draft-b")

    job_store = ConnectJobStore(jobs)
    job_store.create("job-a", "escritorio-a")
    job_store.create("job-b", "escritorio-b")

    store = LocalFTSStore(corpus)
    try:
        store.upsert([_chunk("pub", "honorários publicos")], [[]], tenant_id=None)
        store.upsert([_chunk("a", "doutrina privada a")], [[]], tenant_id="escritorio-a")
        store.upsert([_chunk("b", "doutrina privada b")], [[]], tenant_id="escritorio-b")
    finally:
        store.close()

    plan = build_tenant_erasure_plan(
        "escritorio-a",
        juris_home_path=home,
        out_root=out,
        repertory_path=corpus,
        connect_jobs_path=jobs,
    )

    assert plan.file_count == 3
    assert plan.connect_jobs == 1
    assert plan.corpus_chunks == 1
    assert plan.confirmation_phrase == "ERASE-escritorio-a"

    result = execute_tenant_erasure(
        plan,
        confirmation="ERASE-escritorio-a",
        juris_home_path=home,
        out_root=out,
        repertory_path=corpus,
        connect_jobs_path=jobs,
    )

    assert result.targets_deleted == 2
    assert result.connect_jobs_deleted == 1
    assert result.corpus_chunks_deleted == 1
    assert not (home / "tenants" / "escritorio-a").exists()
    assert not (out / "tenants" / "escritorio-a").exists()
    assert (home / "tenants" / "escritorio-b" / "audit.jsonl").exists()
    assert (out / "tenants" / "escritorio-b" / "case-2" / "draft.md").exists()
    assert ConnectJobStore(jobs).get("job-a") is None
    assert ConnectJobStore(jobs).get("job-b") is not None
    assert (home / "compliance-erasure.jsonl").exists()

    reopened = LocalFTSStore(corpus)
    try:
        assert reopened.count_by_tenant("escritorio-a") == 0
        assert reopened.count_by_tenant("escritorio-b") == 1
        assert {hit.source_id for hit in reopened.search_text("honorários", tenant_id="escritorio-a")} == {"pub"}
    finally:
        reopened.close()


def test_tenant_erasure_requires_exact_confirmation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    out = tmp_path / "out"
    _write(home / "tenants" / "escritorio-a" / "audit.jsonl", "audit-a")
    plan = build_tenant_erasure_plan("escritorio-a", juris_home_path=home, out_root=out)

    with pytest.raises(ValueError, match="confirmação inválida"):
        execute_tenant_erasure(plan, confirmation="ERASE-wrong", juris_home_path=home, out_root=out)

    assert (home / "tenants" / "escritorio-a" / "audit.jsonl").exists()


def test_public_erasure_requires_explicit_allow_public(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="public"):
        build_tenant_erasure_plan("public", juris_home_path=tmp_path / "home", out_root=tmp_path / "out")

    plan = build_tenant_erasure_plan(
        "public",
        juris_home_path=tmp_path / "home",
        out_root=tmp_path / "out",
        allow_public=True,
    )
    assert plan.tenant_id == "public"
