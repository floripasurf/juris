"""Tests for the shared connect orchestration (run_connect)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from juris.jobs.connect import run_connect
from juris.mni.operations.intimacoes import Aviso, AvisosResult
from juris.mni.tribunais import get_tribunal

_CNJ = "5082351-40.2017.8.13.0024"


class _FakeMNI:
    def __init__(self, avisos: AvisosResult) -> None:
        self._avisos = avisos

    def consultar_avisos(self, tribunal_cfg, cpf, senha, *, token_pin=None):
        return self._avisos


def _run(**kwargs):
    return asyncio.run(run_connect(get_tribunal("tjmg"), "07671039632", "senha", **kwargs))


def test_seeds_avisos_into_tracked_and_syncs() -> None:
    avisos = AvisosResult(
        sucesso=True, mensagem="ok",
        avisos=[Aviso(id_aviso="1", tipo_comunicacao="intimacao", numero_processo=_CNJ)],
    )
    stored: dict[str, list] = {}

    async def fake_nightly(processos, **kwargs):
        return MagicMock(total=len(processos), succeeded=len(processos))

    with (
        patch("juris.jobs.connect.get_tracked", return_value=[]),
        patch("juris.jobs.connect.set_tracked", side_effect=lambda e, db=None: stored.__setitem__("t", e)),
        patch("juris.jobs.connect.run_nightly", side_effect=fake_nightly),
    ):
        result = _run(token_pin="1234", mni_service=_FakeMNI(avisos))  # noqa: S106

    assert result.avisos_added == 1
    assert result.total_tracked == 1
    assert {"numero_cnj": _CNJ, "tribunal": "tjmg"} in stored["t"]
    assert result.sync is not None


def test_no_sync_skips_nightly() -> None:
    avisos = AvisosResult(sucesso=True, mensagem="ok", avisos=[])
    with (
        patch("juris.jobs.connect.get_tracked", return_value=[]),
        patch("juris.jobs.connect.set_tracked"),
        patch("juris.jobs.connect.run_nightly", side_effect=AssertionError("must not sync")),
    ):
        result = _run(token_pin="1234", do_sync=False, mni_service=_FakeMNI(avisos))  # noqa: S106

    assert result.sync is None


def test_seed_text_adds_to_tracked() -> None:
    avisos = AvisosResult(sucesso=True, mensagem="ok", avisos=[])
    stored: dict[str, list] = {}
    with (
        patch("juris.jobs.connect.get_tracked", return_value=[]),
        patch("juris.jobs.connect.set_tracked", side_effect=lambda e, db=None: stored.__setitem__("t", e)),
    ):
        result = _run(token_pin="1234", seed_text=f"{_CNJ}\n", do_sync=False, mni_service=_FakeMNI(avisos))  # noqa: S106

    assert result.seed_added == 1
    assert {"numero_cnj": _CNJ, "tribunal": "tjmg"} in stored["t"]
    assert result.seed_errors == []


def test_invalid_seed_lines_are_surfaced_not_dropped_silently() -> None:
    avisos = AvisosResult(sucesso=True, mensagem="ok", avisos=[])
    with (
        patch("juris.jobs.connect.get_tracked", return_value=[]),
        patch("juris.jobs.connect.set_tracked"),
    ):
        result = _run(
            token_pin="1234",  # noqa: S106
            seed_text=f"{_CNJ}\nnão-é-um-cnj\n",
            do_sync=False,
            mni_service=_FakeMNI(avisos),
        )

    assert result.seed_added == 1  # the valid one
    assert any("não-é-um-cnj" in e for e in result.seed_errors)  # the invalid one surfaced


def test_run_connect_scopes_tracking_to_tenant_db(tmp_path) -> None:
    from juris.persistence.local_db import LocalDB

    avisos = AvisosResult(sucesso=True, mensagem="ok", avisos=[])
    db = LocalDB(tmp_path / "tenant.db")
    result = _run(
        token_pin="1234",  # noqa: S106
        seed_text=f"{_CNJ}\n",
        do_sync=False,
        mni_service=_FakeMNI(avisos),
        db=db,
    )
    assert result.total_tracked == 1
    # the tracked list landed in the tenant's own store, not the global Keychain
    assert db.get_tracked_list() == [{"numero_cnj": _CNJ, "tribunal": "tjmg"}]


def test_run_connect_threads_same_mni_service_to_nightly() -> None:
    avisos = AvisosResult(sucesso=True, mensagem="ok", avisos=[])
    service = _FakeMNI(avisos)
    captured: dict[str, object] = {}

    async def fake_nightly(processos, **kwargs):
        captured["mni_service"] = kwargs.get("mni_service")
        return MagicMock(total=1, succeeded=1)

    with (
        patch("juris.jobs.connect.get_tracked", return_value=[{"numero_cnj": _CNJ, "tribunal": "tjmg"}]),
        patch("juris.jobs.connect.set_tracked", side_effect=lambda e, db=None: None),
        patch("juris.jobs.connect.run_nightly", side_effect=fake_nightly),
    ):
        _run(token_pin="1234", do_sync=True, mni_service=service)  # noqa: S106

    # the exact service used for avisos must reach the nightly sync (split-trust)
    assert captured["mni_service"] is service
