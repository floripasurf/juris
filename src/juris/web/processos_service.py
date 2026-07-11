"""Processos listing for the Phase 1 web UI — the lawyer's imported acervo.

Reads the locally-synced processos (``LocalDB``) and joins each with its nearest
pending prazo, producing the rows the "Meus processos" screen renders. Read-only:
populating the acervo is the job of ``juris connect`` / the differential sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from juris.persistence.local_db import LocalDB


@dataclass(frozen=True, slots=True)
class ProcessoView:
    """One row of the processos list."""

    numero_cnj: str
    tribunal: str
    classe: str | None
    assunto: str | None
    last_sync_at: datetime | None
    prazos_pendentes: int
    proximo_prazo: datetime | None
    proximo_prazo_urgencia: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "numero_cnj": self.numero_cnj,
            "tribunal": self.tribunal,
            "classe": self.classe,
            "assunto": self.assunto,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "prazos_pendentes": self.prazos_pendentes,
            "proximo_prazo": self.proximo_prazo.isoformat() if self.proximo_prazo else None,
            "proximo_prazo_urgencia": self.proximo_prazo_urgencia,
        }


@dataclass(frozen=True, slots=True)
class PrazoView:
    """One row of the deadline agenda."""

    numero_cnj: str
    data_limite: datetime | None
    urgencia: str | None
    status: str | None
    rule_nome: str | None
    tipo_acao: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "numero_cnj": self.numero_cnj,
            "data_limite": self.data_limite.isoformat() if self.data_limite else None,
            "urgencia": self.urgencia,
            "status": self.status,
            "rule_nome": self.rule_nome,
            "tipo_acao": self.tipo_acao,
        }


def list_prazos(db: LocalDB | None = None) -> list[PrazoView]:
    """Deadline agenda: pending prazos across the acervo, soonest first."""
    if db is None:
        from juris.persistence.local_db import LocalDB as _LocalDB

        db = _LocalDB()

    return [
        PrazoView(
            numero_cnj=p.numero_cnj,
            data_limite=cast("datetime | None", p.data_limite),
            urgencia=p.urgencia,
            status=cast("str | None", p.status),
            rule_nome=cast("str | None", p.rule_nome),
            tipo_acao=cast("str | None", getattr(p, "tipo_acao", None)),
        )
        for p in db.get_pending_prazos()
    ]


def list_processos(db: LocalDB | None = None) -> list[ProcessoView]:
    """Build the processos list, sorted by the nearest pending prazo first.

    Deterministic order (soonest deadline → no deadline → CNJ) so backend pagination
    (:func:`list_processos_page`) is stable across requests.
    """
    if db is None:
        from juris.persistence.local_db import LocalDB as _LocalDB

        db = _LocalDB()

    # Values are read off SQLAlchemy ORM rows; cast the ProcessoLocal columns to
    # their runtime python types (mypy sees them as Column[...] without the
    # sqlalchemy plugin). Prazo rows flow through Any (dict value type).
    pending_by_cnj: dict[str, list[Any]] = {}
    for prazo in db.get_pending_prazos():
        pending_by_cnj.setdefault(prazo.numero_cnj, []).append(prazo)

    views: list[ProcessoView] = []
    for p in db.get_all_processos():
        cnj = p.numero_cnj
        prazos = pending_by_cnj.get(cnj, [])
        # .timestamp() keeps this tz-mix-safe (see _prazo_key below).
        proximo = min(prazos, key=lambda pr: pr.data_limite.timestamp()) if prazos else None
        views.append(
            ProcessoView(
                numero_cnj=cnj,
                tribunal=p.tribunal_id,
                classe=p.classe,
                assunto=p.assunto,
                last_sync_at=p.last_sync_at,
                prazos_pendentes=len(prazos),
                proximo_prazo=proximo.data_limite if proximo else None,
                proximo_prazo_urgencia=proximo.urgencia if proximo else None,
            )
        )
    # Sort by soonest prazo. Use .timestamp() (a float) rather than comparing datetimes
    # so a mix of tz-aware and naive proximo_prazo can never raise (the SQLite path is
    # always naive, but an injected/alternate db could return tz-aware rows).
    def _prazo_key(v: ProcessoView) -> tuple[bool, float, str]:
        return (v.proximo_prazo is None, v.proximo_prazo.timestamp() if v.proximo_prazo else float("inf"), v.numero_cnj)

    views.sort(key=_prazo_key)
    return views


def list_processos_page(
    db: LocalDB | None = None, *, limit: int = 50, offset: int = 0
) -> tuple[list[ProcessoView], int]:
    """Return one page of processos plus the total count (backend pagination).

    ``limit`` is clamped to [1, 200]; ``offset`` to >= 0. The total lets the UI show
    "page X of N" without fetching everything.
    """
    all_views = list_processos(db)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    return all_views[offset : offset + limit], len(all_views)


@dataclass(frozen=True, slots=True)
class MovimentoView:
    """One movement in a processo's history."""

    data_hora: datetime | None
    descricao: str | None
    tipo: str | None
    categoria: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "data_hora": self.data_hora.isoformat() if self.data_hora else None,
            "descricao": self.descricao,
            "tipo": self.tipo,
            "categoria": self.categoria,
        }


@dataclass(frozen=True, slots=True)
class ProcessoDetailView:
    """Full detail for one processo: metadata + movements + pending prazos."""

    numero_cnj: str
    tribunal: str | None
    classe: str | None
    assunto: str | None
    orgao_julgador: str | None
    valor_causa: float | None
    last_sync_at: datetime | None
    movimentos: list[MovimentoView]
    prazos: list[PrazoView]

    def to_dict(self) -> dict[str, Any]:
        return {
            "numero_cnj": self.numero_cnj,
            "tribunal": self.tribunal,
            "classe": self.classe,
            "assunto": self.assunto,
            "orgao_julgador": self.orgao_julgador,
            "valor_causa": self.valor_causa,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "movimentos": [m.to_dict() for m in self.movimentos],
            "prazos": [p.to_dict() for p in self.prazos],
        }


def get_processo_detail(numero_cnj: str, db: LocalDB | None = None) -> ProcessoDetailView | None:
    """Assemble one processo's detail: metadata + movements + pending prazos."""
    if db is None:
        from juris.persistence.local_db import LocalDB as _LocalDB

        db = _LocalDB()

    proc = db.get_processo_by_cnj(numero_cnj)
    if proc is None:
        return None

    movimentos = [
        MovimentoView(
            data_hora=cast("datetime | None", m.data_hora),
            descricao=m.descricao,
            tipo=m.tipo,
            categoria=cast("str | None", getattr(m, "categoria_semantica", None)),
        )
        for m in db.get_movimentos_by_cnj(numero_cnj)
    ]
    prazos = [
        PrazoView(
            numero_cnj=p.numero_cnj,
            data_limite=cast("datetime | None", p.data_limite),
            urgencia=p.urgencia,
            status=cast("str | None", p.status),
            rule_nome=cast("str | None", p.rule_nome),
            tipo_acao=cast("str | None", getattr(p, "tipo_acao", None)),
        )
        for p in db.get_pending_prazos(numero_cnj=numero_cnj)
    ]
    return ProcessoDetailView(
        numero_cnj=proc.numero_cnj,
        tribunal=cast("str | None", proc.tribunal_id),
        classe=proc.classe,
        assunto=proc.assunto,
        orgao_julgador=cast("str | None", getattr(proc, "orgao_julgador", None)),
        valor_causa=cast("float | None", getattr(proc, "valor_causa", None)),
        last_sync_at=proc.last_sync_at,
        movimentos=movimentos,
        prazos=prazos,
    )
