"""`juris connect` — the unified first-connection / sync flow (process discovery)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from juris.cli.main import _merge_tracked, app
from juris.mni.operations.intimacoes import Aviso, AvisosResult

runner = CliRunner()
_CNJ = "5082351-40.2017.8.13.0024"


class TestMergeTracked:
    def test_dedups_by_tribunal_and_cnj(self) -> None:
        tracked = [{"numero_cnj": "A", "tribunal": "tjmg"}]
        entries = [
            {"numero_cnj": "A", "tribunal": "tjmg"},  # dup
            {"numero_cnj": "B", "tribunal": "tjmg"},  # new
        ]
        merged, added = _merge_tracked(tracked, entries)
        assert added == 1
        assert len(merged) == 2
        assert len(tracked) == 1  # input not mutated


def test_connect_seeds_from_avisos_and_runs_sync() -> None:
    avisos = AvisosResult(
        sucesso=True,
        mensagem="ok",
        avisos=[Aviso(id_aviso="1", tipo_comunicacao="intimacao", numero_processo=_CNJ)],
    )
    stored: dict[str, str] = {}
    captured: dict[str, object] = {}

    async def fake_nightly(processos, **kwargs):
        captured["processos"] = processos
        return MagicMock(succeeded=len(processos), total=len(processos), total_critical_alerts=2)

    with (
        patch("juris.cli.main._mtls_session", return_value=(MagicMock(), "senha", "1234")),
        patch("juris.mni.service.InProcessMNIReadService.consultar_avisos", return_value=avisos),
        patch("juris.cli.main._get_tracked_processos", return_value=[]),
        patch("juris.core.credentials.store_credential", side_effect=lambda k, v: stored.__setitem__(k, v)),
        patch("juris.jobs.nightly.run_nightly", side_effect=fake_nightly),
    ):
        result = runner.invoke(app, ["connect", "--cpf", "07671039632", "--pin", "1234"])

    assert result.exit_code == 0, result.output
    saved = json.loads(stored["tracked_processos"])
    assert {"numero_cnj": _CNJ, "tribunal": "tjmg"} in saved
    # the differential sync ran over the seeded tracked list
    assert any(p["numero_cnj"] == _CNJ for p in captured["processos"])


def test_connect_no_sync_only_updates_list() -> None:
    avisos = AvisosResult(sucesso=True, mensagem="ok", avisos=[])
    stored: dict[str, str] = {}

    with (
        patch("juris.cli.main._mtls_session", return_value=(MagicMock(), "senha", "1234")),
        patch("juris.mni.service.InProcessMNIReadService.consultar_avisos", return_value=avisos),
        patch("juris.cli.main._get_tracked_processos", return_value=[]),
        patch("juris.core.credentials.store_credential", side_effect=lambda k, v: stored.__setitem__(k, v)),
        patch("juris.jobs.nightly.run_nightly", side_effect=AssertionError("sync must not run")),
    ):
        result = runner.invoke(app, ["connect", "--cpf", "07671039632", "--pin", "1234", "--no-sync"])

    assert result.exit_code == 0, result.output
