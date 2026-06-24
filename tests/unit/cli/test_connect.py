"""`juris connect` CLI — resolves credentials at the edge and delegates to run_connect."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from juris.cli.main import _merge_tracked, app
from juris.jobs.connect import ConnectResult

runner = CliRunner()


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


def _result(*, sync) -> ConnectResult:
    return ConnectResult(avisos_added=1, seed_added=0, total_tracked=1, first_time=True, sync=sync)


def test_connect_resolves_creds_and_runs_full_sync() -> None:
    captured: dict[str, object] = {}

    async def fake_run_connect(tribunal_cfg, cpf, senha, **kwargs):
        captured.update(kwargs)
        captured["cpf"] = cpf
        return _result(sync=MagicMock(succeeded=1, total=1, total_critical_alerts=2))

    with (
        patch("juris.cli.main._mtls_session", return_value=(MagicMock(), "senha", "1234")),
        patch("juris.jobs.connect.run_connect", side_effect=fake_run_connect),
    ):
        result = runner.invoke(app, ["connect", "--cpf", "07671039632", "--pin", "1234"])

    assert result.exit_code == 0, result.output
    assert captured["cpf"] == "07671039632"
    assert captured["token_pin"] == "1234"
    assert captured["do_sync"] is True


def test_connect_no_sync_passes_do_sync_false() -> None:
    captured: dict[str, object] = {}

    async def fake_run_connect(tribunal_cfg, cpf, senha, **kwargs):
        captured.update(kwargs)
        return _result(sync=None)

    with (
        patch("juris.cli.main._mtls_session", return_value=(MagicMock(), "senha", "1234")),
        patch("juris.jobs.connect.run_connect", side_effect=fake_run_connect),
    ):
        result = runner.invoke(app, ["connect", "--cpf", "07671039632", "--pin", "1234", "--no-sync"])

    assert result.exit_code == 0, result.output
    assert captured["do_sync"] is False
