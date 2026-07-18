"""Tests for the Task 3 grounding gate wiring in `juris file` (CLI).

The orchestrator's gate itself is covered by test_filing_grounding_gate.py —
these tests only pin the CLI's responsibility: resolving evidence from the
run-manifest next to the loaded draft, forwarding --override-grounding/--reason,
and not hiding a block behind the "dry-run, nothing happened" message.
"""

from __future__ import annotations

import hashlib
import json

from typer.testing import CliRunner

from juris.cli.main import app


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _RecordingFilingService:
    def __init__(self, result: object) -> None:
        self._result = result
        self.calls: list[tuple[object, str | None]] = []

    async def file(self, request: object, *, pin: str | None = None) -> object:
        self.calls.append((request, pin))
        return self._result


def _blocked_result(error_code: str, message: str) -> object:
    from juris.signing.filing import FilingResult

    return FilingResult(
        success=False,
        receipt=None,
        signing_result=None,
        preflight=None,
        audit_entry_ids=["a1"],
        error=message,
        error_code=error_code,
    )


def _ok_result() -> object:
    from juris.signing.filing import FilingResult

    return FilingResult(
        success=True,
        receipt=None,
        signing_result=None,
        preflight=None,
        audit_entry_ids=["a1"],
    )


def test_file_resolves_grounding_evidence_from_manifest_next_to_draft(tmp_path, monkeypatch) -> None:
    import juris.signing.filing_service as filing_service

    draft_text = "# Contestação\n\nTexto revisado."
    (tmp_path / "draft.md").write_text(draft_text, encoding="utf-8")
    (tmp_path / "run-manifest.json").write_text(
        json.dumps(
            {
                "draft": {"grounding_status": "verified"},
                "artifacts": [{"name": "draft.md", "sha256": _sha256(draft_text)}],
            }
        ),
        encoding="utf-8",
    )
    service = _RecordingFilingService(_ok_result())
    monkeypatch.setattr(filing_service, "get_filing_service", lambda: service)

    result = CliRunner().invoke(
        app,
        [
            "file",
            "5082351-40.2017.8.13.0024",
            str(tmp_path / "draft.md"),
            "--cpf",
            "07671039632",
            "--skip-preflight",
            "--dry-run",
            "--pin",
            "1234",
            "--senha",
            "senha123",
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(service.calls) == 1
    request, _pin = service.calls[0]
    assert request.grounding is not None
    assert request.grounding.status == "verified"
    assert request.grounding.draft_sha256 == _sha256(draft_text)


def test_file_without_manifest_reports_block_and_hints_override(tmp_path, monkeypatch) -> None:
    import juris.signing.filing_service as filing_service

    (tmp_path / "peca.md").write_text("# Peça externa", encoding="utf-8")
    service = _RecordingFilingService(
        _blocked_result("grounding_required", "Protocolo bloqueado: grounding não verificado.")
    )
    monkeypatch.setattr(filing_service, "get_filing_service", lambda: service)

    result = CliRunner().invoke(
        app,
        [
            "file",
            "5082351-40.2017.8.13.0024",
            str(tmp_path / "peca.md"),
            "--cpf",
            "07671039632",
            "--skip-preflight",
            "--dry-run",
            "--pin",
            "1234",
            "--senha",
            "senha123",
        ],
    )

    request, _pin = service.calls[0]
    assert request.grounding is None
    assert "Protocolo bloqueado" in result.output
    assert "--override-grounding" in result.output
    assert "Nenhuma assinatura ou protocolo realizado" not in result.output


def test_file_forwards_override_flags(tmp_path, monkeypatch) -> None:
    import juris.signing.filing_service as filing_service

    (tmp_path / "peca.md").write_text("# Peça externa", encoding="utf-8")
    service = _RecordingFilingService(_ok_result())
    monkeypatch.setattr(filing_service, "get_filing_service", lambda: service)

    result = CliRunner().invoke(
        app,
        [
            "file",
            "5082351-40.2017.8.13.0024",
            str(tmp_path / "peca.md"),
            "--cpf",
            "07671039632",
            "--skip-preflight",
            "--dry-run",
            "--pin",
            "1234",
            "--senha",
            "senha123",
            "--override-grounding",
            "--reason",
            "Documento externo revisado manualmente pelo advogado.",
        ],
    )

    assert result.exit_code == 0, result.output
    request, _pin = service.calls[0]
    assert request.grounding_override is True
    assert request.grounding_override_reason == "Documento externo revisado manualmente pelo advogado."


def test_file_dry_run_success_still_shows_dry_run_message(tmp_path, monkeypatch) -> None:
    """Regression guard: fixing the block-hiding bug must not break the normal
    (ungated success) dry-run message lawyers already rely on."""
    import juris.signing.filing_service as filing_service

    draft_text = "# Contestação\n\nTexto revisado."
    (tmp_path / "draft.md").write_text(draft_text, encoding="utf-8")
    (tmp_path / "run-manifest.json").write_text(
        json.dumps(
            {
                "draft": {"grounding_status": "verified"},
                "artifacts": [{"name": "draft.md", "sha256": _sha256(draft_text)}],
            }
        ),
        encoding="utf-8",
    )
    service = _RecordingFilingService(_ok_result())
    monkeypatch.setattr(filing_service, "get_filing_service", lambda: service)

    result = CliRunner().invoke(
        app,
        [
            "file",
            "5082351-40.2017.8.13.0024",
            str(tmp_path / "draft.md"),
            "--cpf",
            "07671039632",
            "--skip-preflight",
            "--dry-run",
            "--pin",
            "1234",
            "--senha",
            "senha123",
        ],
    )

    assert "Nenhuma assinatura ou protocolo realizado" in result.output
