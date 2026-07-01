"""Sprint 5: ingest a real inteiro-teor file (firm's own doc) with provenance."""

from __future__ import annotations

from typer.testing import CliRunner

from juris.cli.main import app

runner = CliRunner()


def test_ingest_file_adds_searchable_source_with_provenance(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JURIS_OUT_ROOT", str(tmp_path))
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))  # redirects resolve_repertory_path here

    # A dummy inteiro-teor file (clearly test text — no real jurisprudence claimed).
    doc = tmp_path / "decisao.txt"
    doc.write_text(
        "Ementa de teste. Honorários sucumbenciais contra a fazenda pública em execução fiscal.",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "repertory", "ingest-file", str(doc),
            "--data", "2020-05-13",
            "--url", "https://www.stj.jus.br/exemplo",
            "--tribunal", "STJ",
            "--titulo", "REsp teste",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Ingerido com proveniência" in result.output

    # The ingested source is now searchable in the local corpus.
    from juris.repertory.readiness import resolve_repertory_path
    from juris.repertory.vector_store import LocalFTSStore

    store = LocalFTSStore(resolve_repertory_path())
    try:
        hits = store.search_text("honorários fazenda pública", top_k=5)
        assert any("honorários" in h.text.lower() for h in hits)
    finally:
        store.close()


def test_ingest_file_rejects_incomplete_provenance(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JURIS_OUT_ROOT", str(tmp_path))
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    doc = tmp_path / "d.txt"
    doc.write_text("texto", encoding="utf-8")

    # No tribunal AND no publisher → provenance incomplete → refused.
    result = runner.invoke(
        app,
        ["repertory", "ingest-file", str(doc), "--data", "2020-01-01", "--url", "https://x.gov.br/y"],
    )
    assert result.exit_code == 1
    assert "Proveniência incompleta" in result.output
