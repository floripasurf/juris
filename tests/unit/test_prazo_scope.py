"""Per-tenant and per-process deadline-regime routing."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from juris.jobs import nightly, pipeline
from juris.jobs.nightly import NightlyResult
from juris.jobs.pipeline import PipelineResult


def test_nightly_process_override_wins_over_tenant_default(monkeypatch) -> None:
    captured: list[str] = []

    async def fake_single(*, numero_cnj, tribunal, parte_representada, **kwargs):  # noqa: ANN001, ANN202
        captured.append(parte_representada)
        return NightlyResult(numero_cnj=numero_cnj, tribunal=tribunal, success=True)

    monkeypatch.setattr(nightly, "run_nightly_single", fake_single)
    processos = [
        {"numero_cnj": "1", "tribunal": "tjmg"},
        {"numero_cnj": "2", "tribunal": "tjmg", "parte_representada": "mp"},
        {"numero_cnj": "3", "tribunal": "tjmg", "parte_representada": ""},
    ]

    asyncio.run(
        nightly.run_nightly(
            processos,
            db=MagicMock(),
            parte_representada="fazenda",
        )
    )

    assert captured == ["fazenda", "mp", ""]


def test_pipeline_process_override_wins_over_tenant_default(monkeypatch) -> None:
    captured: list[str] = []

    async def fake_single(*, numero_cnj, tribunal, parte_representada, **kwargs):  # noqa: ANN001, ANN202
        captured.append(parte_representada)
        return PipelineResult(numero_cnj=numero_cnj, tribunal=tribunal, success=True)

    monkeypatch.setattr(pipeline, "run_pipeline_single", fake_single)
    processos = [
        {"numero_cnj": "1", "tribunal": "tjmg"},
        {"numero_cnj": "2", "tribunal": "tjmg", "parte_representada": "defensoria"},
    ]

    asyncio.run(
        pipeline.run_pipeline(
            processos,
            db=MagicMock(),
            parte_representada="fazenda",
        )
    )

    assert captured == ["fazenda", "defensoria"]
