"""CLI tests for DataJud cache controls."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from juris.cli.main import app
from juris.datajud.safety import DataJudCache, DataJudRequestMeta

runner = CliRunner()


def test_datajud_command_passes_no_cache_flag(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("JURIS_DATAJUD_CACHE_DIR", str(tmp_path / "cache"))
    captured: dict[str, object] = {}

    def fake_consultar(numero_cnj: str, tribunal: str, **kwargs: object) -> dict:
        captured.update(kwargs)
        return {
            "numeroProcesso": "00012345620268130001",
            "classe": {"nome": "Procedimento Comum Cível"},
            "tribunal": "TJMG",
            "movimentos": [],
            "assuntos": [],
        }

    with patch("juris.datajud.client.consultar_processo", side_effect=fake_consultar):
        result = runner.invoke(
            app,
            [
                "datajud",
                "0001234-56.2026.8.13.0001",
                "--tribunal",
                "tjmg",
                "--no-cache",
            ],
        )

    assert result.exit_code == 0, result.output
    assert captured["use_cache"] is False


def test_cache_purge_datajud_removes_cached_responses(tmp_path: Path, monkeypatch) -> None:
    cache_dir = tmp_path / "datajud-cache"
    monkeypatch.setenv("JURIS_DATAJUD_CACHE_DIR", str(cache_dir))
    cache = DataJudCache(cache_dir)
    cache.set(
        DataJudRequestMeta(
            cnj="0001234-56.2026.8.13.0001",
            tribunal="tjmg",
            endpoint="/api_publica_tjmg/_search",
            query_hash="hash",
        ),
        {"ok": True},
    )

    result = runner.invoke(app, ["cache", "purge", "--datajud"])

    assert result.exit_code == 0, result.output
    assert "1 arquivo" in result.output
    assert not cache_dir.exists()
