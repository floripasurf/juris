"""Repository for persisting computed prazos."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select, update

from juris.core.observability import get_logger
from juris.persistence.models import PrazoComputed, Processo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from juris.prazo.engine import Prazo

logger = get_logger(__name__)


async def upsert_prazo(
    session: AsyncSession,
    prazo: Prazo,
    processo_id: str,
) -> PrazoComputed:
    """Insert or update a computed prazo."""
    # Check if this prazo already exists (same processo + rule + data_inicio)
    stmt = select(PrazoComputed).where(
        PrazoComputed.numero_cnj == prazo.numero_cnj,
        PrazoComputed.rule_nome == prazo.rule.nome,
        PrazoComputed.data_inicio == datetime.combine(prazo.data_inicio, datetime.min.time(), tzinfo=UTC),
    )
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing is not None:
        # Update status only (don't duplicate)
        existing.status = prazo.status.value
        existing.urgencia = prazo.urgencia.value
        await session.flush()
        return existing

    record = PrazoComputed(
        processo_id=processo_id,
        numero_cnj=prazo.numero_cnj,
        rule_nome=prazo.rule.nome,
        rule_base_legal=prazo.rule.base_legal,
        tipo_acao=prazo.rule.tipo_acao.value,
        categoria=prazo.categoria.value,
        data_inicio=datetime.combine(prazo.data_inicio, datetime.min.time(), tzinfo=UTC),
        data_limite=datetime.combine(prazo.data_limite, datetime.min.time(), tzinfo=UTC),
        dias_uteis_total=prazo.dias_uteis_total,
        status=prazo.status.value,
        urgencia=prazo.urgencia.value,
    )
    session.add(record)
    await session.flush()
    logger.info("prazo_persisted", numero_cnj=prazo.numero_cnj, rule=prazo.rule.nome)
    return record


async def mark_cumprido(
    session: AsyncSession,
    prazo_id: str,
    cumprido_por: str = "user",
) -> None:
    """Mark a prazo as cumprido (fulfilled)."""
    stmt = (
        update(PrazoComputed)
        .where(PrazoComputed.id == prazo_id)
        .values(
            status="cumprido",
            cumprido_at=datetime.now(UTC),
            cumprido_por=cumprido_por,
        )
    )
    await session.execute(stmt)
    await session.flush()


async def get_prazos_by_processo(
    session: AsyncSession,
    numero_cnj: str,
    status_filter: list[str] | None = None,
) -> list[PrazoComputed]:
    """Get all computed prazos for a processo."""
    stmt = select(PrazoComputed).where(PrazoComputed.numero_cnj == numero_cnj)
    if status_filter:
        stmt = stmt.where(PrazoComputed.status.in_(status_filter))
    stmt = stmt.order_by(PrazoComputed.data_limite)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_all_pending_prazos(
    session: AsyncSession,
) -> list[PrazoComputed]:
    """Get all non-cumprido prazos across all processos, ordered by urgency."""
    stmt = (
        select(PrazoComputed)
        .where(PrazoComputed.status != "cumprido")
        .order_by(PrazoComputed.data_limite)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
