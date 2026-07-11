"""Tests for the web processos listing service (Phase 1 web)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from juris.web.processos_service import get_processo_detail, list_prazos, list_processos


def _proc(cnj: str, classe: str = "Procedimento Comum") -> SimpleNamespace:
    return SimpleNamespace(
        numero_cnj=cnj,
        tribunal_id="tjmg",
        classe=classe,
        assunto="Cobrança",
        orgao_julgador="3ª Câmara Cível",
        valor_causa=10000.0,
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


def _prazo_local(cnj: str, data_limite: datetime, urgencia: str) -> SimpleNamespace:
    return SimpleNamespace(
        numero_cnj=cnj,
        data_limite=data_limite,
        urgencia=urgencia,
        status="aberto",
        rule_nome="Contestação",
        tipo_acao="contestar",
    )


def test_list_prazos_returns_pending_sorted_by_deadline() -> None:
    prazos = [
        _prazo_local("A", datetime(2026, 7, 10, tzinfo=UTC), "media"),
        _prazo_local("B", datetime(2026, 7, 1, tzinfo=UTC), "alta"),
    ]
    db = SimpleNamespace(get_pending_prazos=lambda: prazos)

    views = list_prazos(db=db)

    assert len(views) == 2
    payload = views[0].to_dict()
    assert payload["numero_cnj"] == "A"
    assert payload["urgencia"] == "media"
    assert payload["data_limite"] == "2026-07-10T00:00:00+00:00"
    assert payload["rule_nome"] == "Contestação"


def _mov(data_hora: datetime, descricao: str) -> SimpleNamespace:
    return SimpleNamespace(
        data_hora=data_hora, descricao=descricao, tipo="movimento", categoria_semantica="decisao"
    )


def test_get_processo_detail_returns_none_when_not_found() -> None:
    db = SimpleNamespace(
        get_processo_by_cnj=lambda cnj: None,
        get_movimentos_by_cnj=lambda cnj: [],
        get_pending_prazos=lambda numero_cnj=None: [],
    )
    assert get_processo_detail("X", db=db) is None


def test_get_processo_detail_assembles_movimentos_and_prazos() -> None:
    proc = _proc("A")
    movs = [_mov(datetime(2021, 6, 1, tzinfo=UTC), "Julgamento")]
    prazos = [_prazo_local("A", datetime(2026, 7, 1, tzinfo=UTC), "alta")]
    db = SimpleNamespace(
        get_processo_by_cnj=lambda cnj: proc if cnj == "A" else None,
        get_movimentos_by_cnj=lambda cnj: movs,
        get_pending_prazos=lambda numero_cnj=None: prazos,
    )

    detail = get_processo_detail("A", db=db)

    assert detail is not None
    payload = detail.to_dict()
    assert payload["numero_cnj"] == "A"
    assert payload["classe"] == "Procedimento Comum"
    assert payload["orgao_julgador"] == "3ª Câmara Cível"
    assert payload["movimentos"][0]["descricao"] == "Julgamento"
    assert payload["prazos"][0]["urgencia"] == "alta"
