"""Sprint 4: `juris pilot report` turns collected feedback into an evidence report."""

from __future__ import annotations

from typer.testing import CliRunner

from juris.cli.main import app

runner = CliRunner()


def _seed(tmp_path, numero_cnj: str = "5082351-40.2017.8.13.0024"):  # noqa: ANN001, ANN202
    from juris.web.auth import PUBLIC_TENANT_ID, Tenant, tenant_scoped_dir
    from juris.web.pilot_feedback import append_feedback

    root = tenant_scoped_dir(Tenant(PUBLIC_TENANT_ID), tmp_path)
    append_feedback(
        root,
        {
            "numero_cnj": numero_cnj,
            "time_saved_minutes": 45,
            "perceived_utility": 4,
            "citations_accepted": 3,
            "citations_rejected": 1,
            "corpus_usable": True,
            "missing_source": "acórdão STJ sobre honorários",
        },
    )


def test_pilot_report_generates_evidence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JURIS_OUT_ROOT", str(tmp_path))
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    _seed(tmp_path)

    out = tmp_path / "report.md"
    result = runner.invoke(app, ["pilot", "report", "-o", str(out)])

    assert result.exit_code == 0, result.output
    md = out.read_text(encoding="utf-8")
    assert "Tempo economizado" in md  # evidence
    assert "45" in md


def test_pilot_report_without_feedback_exits_nonzero(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JURIS_OUT_ROOT", str(tmp_path))
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))

    result = runner.invoke(app, ["pilot", "report"])

    assert result.exit_code == 1
    assert "Nenhum feedback" in result.output


def test_pilot_gate_fails_before_five_real_cases(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JURIS_OUT_ROOT", str(tmp_path))
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    _seed(tmp_path)

    result = runner.invoke(app, ["pilot", "gate"])

    assert result.exit_code == 1
    assert "Gate de valor bloqueado" in result.output
    assert "Casos reais: 1/5" in result.output


def test_pilot_gate_passes_with_five_distinct_real_cases(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JURIS_OUT_ROOT", str(tmp_path))
    monkeypatch.setenv("JURIS_HOME", str(tmp_path))
    for i in range(5):
        _seed(tmp_path, f"508235{i}-40.2017.8.13.0024")

    result = runner.invoke(app, ["pilot", "gate"])

    assert result.exit_code == 0, result.output
    assert "Gate de valor pronto" in result.output
    assert "Casos reais: 5/5" in result.output
