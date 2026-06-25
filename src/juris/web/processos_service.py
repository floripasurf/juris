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
            numero_cnj=cast(str, p.numero_cnj),
            data_limite=cast("datetime | None", p.data_limite),
            urgencia=cast("str | None", p.urgencia),
            status=cast("str | None", p.status),
            rule_nome=cast("str | None", p.rule_nome),
            tipo_acao=cast("str | None", getattr(p, "tipo_acao", None)),
        )
        for p in db.get_pending_prazos()
    ]


def list_processos(db: LocalDB | None = None) -> list[ProcessoView]:
    """Build the processos list: each imported processo + its nearest pending prazo."""
    if db is None:
        from juris.persistence.local_db import LocalDB as _LocalDB

        db = _LocalDB()

    # Values are read off SQLAlchemy ORM rows; cast the ProcessoLocal columns to
    # their runtime python types (mypy sees them as Column[...] without the
    # sqlalchemy plugin). Prazo rows flow through Any (dict value type).
    pending_by_cnj: dict[str, list[Any]] = {}
    for prazo in db.get_pending_prazos():
        pending_by_cnj.setdefault(cast(str, prazo.numero_cnj), []).append(prazo)

    views: list[ProcessoView] = []
    for p in db.get_all_processos():
        cnj = cast(str, p.numero_cnj)
        prazos = pending_by_cnj.get(cnj, [])
        proximo = min(prazos, key=lambda pr: pr.data_limite) if prazos else None
        views.append(
            ProcessoView(
                numero_cnj=cnj,
                tribunal=cast(str, p.tribunal_id),
                classe=cast("str | None", p.classe),
                assunto=cast("str | None", p.assunto),
                last_sync_at=cast("datetime | None", p.last_sync_at),
                prazos_pendentes=len(prazos),
                proximo_prazo=proximo.data_limite if proximo else None,
                proximo_prazo_urgencia=proximo.urgencia if proximo else None,
            )
        )
    return views
