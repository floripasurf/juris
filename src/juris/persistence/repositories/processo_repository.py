"""Repository for persisting ProcessoDomain to PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from juris.core.observability import get_logger
from juris.mni.tpu import categorize_movement
from juris.persistence.models import Documento, Movimento, Parte, Processo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from juris.mni.parsers.processo import ProcessoDomain

logger = get_logger(__name__)


async def upsert_processo(session: AsyncSession, domain: ProcessoDomain) -> Processo:
    """Upsert a ProcessoDomain into the database.

    Creates the Processo if it doesn't exist, updates if it does.
    Movimentos are deduplicated by the unique index.
    """
    # Find or create the processo
    stmt = select(Processo).where(Processo.numero_cnj == domain.numero_cnj)
    result = await session.execute(stmt)
    processo = result.scalar_one_or_none()

    if processo is None:
        processo = Processo(
            numero_cnj=domain.numero_cnj,
            tribunal_id=domain.tribunal or "unknown",
            classe=domain.classe,
            assunto=domain.assunto,
            valor_causa=domain.valor_causa,
            orgao_julgador=domain.orgao_julgador,
            data_ajuizamento=domain.data_ajuizamento,
            grau=domain.grau,
            last_sync_at=datetime.now(UTC),
        )
        session.add(processo)
        await session.flush()
        logger.info("processo_created", numero_cnj=domain.numero_cnj)
    else:
        processo.classe = domain.classe or processo.classe
        processo.assunto = domain.assunto or processo.assunto
        processo.valor_causa = domain.valor_causa or processo.valor_causa
        processo.orgao_julgador = domain.orgao_julgador or processo.orgao_julgador
        processo.data_ajuizamento = domain.data_ajuizamento or processo.data_ajuizamento
        processo.grau = domain.grau or processo.grau
        processo.last_sync_at = datetime.now(UTC)
        await session.flush()
        logger.info("processo_updated", numero_cnj=domain.numero_cnj)

    # Upsert movimentos (dedup via ON CONFLICT DO NOTHING on the unique index)
    new_movs = 0
    for mov in domain.movimentos:
        categoria = categorize_movement(mov.codigo_nacional).name if mov.codigo_nacional else None
        stmt_mov = (
            pg_insert(Movimento)
            .values(
                processo_id=processo.id,
                data_hora=mov.data_hora,
                tipo=mov.tipo,
                codigo_nacional=mov.codigo_nacional,
                complemento=mov.complemento,
                descricao=mov.descricao,
                id_movimento=mov.id_movimento,
                categoria_semantica=categoria,
            )
            .on_conflict_do_nothing(
                index_elements=["processo_id", "data_hora", "codigo_nacional", "id_movimento"],
            )
        )
        result = await session.execute(stmt_mov)
        if result.rowcount and result.rowcount > 0:
            new_movs += 1

    if new_movs:
        logger.info("movimentos_inserted", numero_cnj=domain.numero_cnj, count=new_movs)

    # Upsert partes (simple: delete and re-insert)
    existing_partes = await session.execute(
        select(Parte).where(Parte.processo_id == processo.id)
    )
    for p in existing_partes.scalars():
        await session.delete(p)
    await session.flush()

    for parte in domain.partes:
        session.add(
            Parte(
                processo_id=processo.id,
                nome=parte.nome,
                tipo=parte.tipo,
                documento=parte.documento,
                advogados=parte.advogados,
            )
        )

    # Upsert documentos
    for doc in domain.documentos:
        existing_doc = await session.execute(
            select(Documento).where(
                Documento.processo_id == processo.id,
                Documento.id_documento_tribunal == doc.id_documento,
            )
        )
        if existing_doc.scalar_one_or_none() is None:
            session.add(
                Documento(
                    processo_id=processo.id,
                    id_documento_tribunal=doc.id_documento,
                    tipo_documento=doc.tipo_documento,
                    descricao=doc.descricao,
                    data_hora=doc.data_hora,
                    mime_type=doc.mime_type,
                    sha256=doc.hash_sha256,
                )
            )

    await session.flush()
    return processo


async def get_processo_by_cnj(session: AsyncSession, numero_cnj: str) -> Processo | None:
    """Fetch a processo by CNJ number."""
    stmt = select(Processo).where(Processo.numero_cnj == numero_cnj)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_processos_by_tribunal(
    session: AsyncSession,
    tribunal_id: str,
    limit: int = 50,
) -> list[Processo]:
    """List processos for a given tribunal."""
    stmt = (
        select(Processo)
        .where(Processo.tribunal_id == tribunal_id)
        .order_by(Processo.updated_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
