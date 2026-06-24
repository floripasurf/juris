"""Tests for the web processos listing service (Phase 1 web)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from juris.web.processos_service import list_processos


def _proc(cnj: str, classe: str = "Procedimento Comum") -> SimpleNamespace:
    return SimpleNamespace(
        numero_cnj=cnj,
        tribunal_id="tjmg",
        classe=classe,
        assunto="Cobrança",
        last_sync_at=datetime(2026, 6, 24, tzinfo=UTC),
    )


def _prazo(cnj: str, data_limite: datetime, urgencia: str) -> SimpleNamespace:
    return SimpleNamespace(numero_cnj=cnj, data_limite=data_limite, urgencia=urgencia)


def test_lists_processos_with_nearest_pending_prazo() -> None:
    proc = _proc("5082351-40.2017.8.13.0024")
    prazos = [
        _prazo("5082351-40.2017.8.13.0024", datetime(2026, 7, 10, tzinfo=UTC), "media"),
        _prazo("5082351-40.2017.8.13.0024", datetime(2026, 7, 1, tzinfo=UTC), "alta"),
    ]
    db = SimpleNamespace(get_all_processos=lambda: [proc], get_pending_prazos=lambda: prazos)

    views = list_processos(db=db)

    assert len(views) == 1
    v = views[0]
    assert v.numero_cnj == "5082351-40.2017.8.13.0024"
    assert v.tribunal == "tjmg"
    assert v.prazos_pendentes == 2
    assert v.proximo_prazo == datetime(2026, 7, 1, tzinfo=UTC)  # the nearest deadline
    assert v.proximo_prazo_urgencia == "alta"


def test_processo_without_prazos_has_none() -> None:
    db = SimpleNamespace(get_all_processos=lambda: [_proc("A")], get_pending_prazos=lambda: [])

    views = list_processos(db=db)

    assert views[0].prazos_pendentes == 0
    assert views[0].proximo_prazo is None


def test_to_dict_serializes_datetimes() -> None:
    db = SimpleNamespace(get_all_processos=lambda: [_proc("A")], get_pending_prazos=lambda: [])
    payload = list_processos(db=db)[0].to_dict()
    assert payload["numero_cnj"] == "A"
    assert payload["last_sync_at"] == "2026-06-24T00:00:00+00:00"
    assert payload["proximo_prazo"] is None
