"""Audit tests for CLI-backed cloud LLM demo runs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from juris.agents.drafter import DraftResult
from juris.demo.orchestrator import DemoOrchestrator, DemoRequest, SourceMode
from juris.demo.output_mode import OutputMode
from juris.llm.local_cli import LocalCliLLM
from juris.mni.parsers.processo import Movimento, ProcessoDomain
from juris.persistence.audit import AuditLog
from juris.repertory.peticoes.models import TipoPeticao


def _processo() -> ProcessoDomain:
    return ProcessoDomain(
        numero_cnj="0001234-56.2026.8.13.0001",
        classe="Procedimento Comum Cível",
        tribunal="tjmg",
        movimentos=[
            Movimento(
                data_hora=datetime.now(UTC),
                tipo="movimentoNacional",
                codigo_nacional=12265,
                descricao="Citação realizada (DEMO).",
                id_movimento="m1",
            ),
        ],
    )


@pytest.mark.asyncio
async def test_demo_started_audit_records_cli_cloud_provider(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    llm = LocalCliLLM(provider="claude")
    orchestrator = DemoOrchestrator(
        llm=llm,
        repertory=MagicMock(),
        audit=audit,
    )
    request = DemoRequest(
        numero_cnj="0001234-56.2026.8.13.0001",
        tipo_peticao=TipoPeticao.CONTESTACAO,
        source=SourceMode.FIXTURE,
        use_cloud_llm=True,
        skip_review=True,
        output_mode=OutputMode.RASCUNHO_PESQUISA,
    )

    with (
        patch("juris.demo.orchestrator.analyze_processo", return_value=None),
        patch.object(
            DemoOrchestrator,
            "_run_drafter",
            return_value=DraftResult(draft_markdown="rascunho"),
        ),
    ):
        await orchestrator.run(
            request,
            processo=_processo(),
            out_dir=tmp_path,
            is_demo_mode=True,
        )

    entries = audit.read_all()
    assert entries[0].event_type == "demo.started"
    assert entries[0].details["llm_provider"] == "claude_cli_subscription"
