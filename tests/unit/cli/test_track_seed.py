"""Seed import: bulk-add CNJs to the tracked list (process discovery, option 1)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from juris.cli.main import _parse_cnj_seed, app

runner = CliRunner()
_CNJ = "5082351-40.2017.8.13.0024"


class TestParseCnjSeed:
    def test_parses_valid_cnj_and_derives_tribunal(self) -> None:
        entries, errors = _parse_cnj_seed(_CNJ + "\n", default_tribunal="tjxx")
        assert errors == []
        # tribunal derived from the CNJ (8.13 → tjmg), not the default
        assert entries == [{"numero_cnj": _CNJ, "tribunal": "tjmg"}]

    def test_skips_blanks_and_comments(self) -> None:
        text = f"\n# um comentário\n   \n{_CNJ}\n"
        entries, errors = _parse_cnj_seed(text, default_tribunal="tjmg")
        assert len(entries) == 1
        assert errors == []

    def test_invalid_cnj_goes_to_errors(self) -> None:
        entries, errors = _parse_cnj_seed(f"{_CNJ}\nnao-eh-cnj\n", default_tribunal="tjmg")
        assert len(entries) == 1
        assert any("nao-eh-cnj" in e for e in errors)

    def test_tribunal_falls_back_to_default_when_court_unknown(self) -> None:
        with patch("juris.search.cnj_router.cnj_to_court", return_value=None):
            entries, _errors = _parse_cnj_seed(_CNJ + "\n", default_tribunal="tjmg")
        assert entries[0]["tribunal"] == "tjmg"


def test_track_file_bulk_imports(tmp_path: Path) -> None:
    seed = tmp_path / "acervo.txt"
    seed.write_text(f"# meu acervo\n{_CNJ}\n0001234-56.2024.8.26.0001\n", encoding="utf-8")

    stored: dict[str, str] = {}

    def fake_store(key, value):
        stored[key] = value

    with (
        patch("juris.cli.main._get_tracked_processos", return_value=[]),
        patch("juris.core.credentials.store_credential", side_effect=fake_store),
    ):
        result = runner.invoke(app, ["track", "--file", str(seed)])

    assert result.exit_code == 0, result.output
    import json

    saved = json.loads(stored["tracked_processos"])
    assert {"numero_cnj": _CNJ, "tribunal": "tjmg"} in saved
    assert {"numero_cnj": "0001234-56.2024.8.26.0001", "tribunal": "tjsp"} in saved
