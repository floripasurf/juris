"""Repository for sync log entries."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from juris.persistence.models import SyncLog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from juris.mni.operations.differential import DiffResult


async def log_sync(
    session: AsyncSession,
    result: DiffResult,
    source: str = "datajud",
    started_at: datetime | None = None,
) -> SyncLog:
    """Log a sync result."""
    now = datetime.now(UTC)
    record = SyncLog(
        numero_cnj=result.numero_cnj,
        tribunal_id=result.tribunal_id,
        source=source,
        started_at=started_at or now,
        finished_at=now,
        success=result.error is None,
        had_changes=result.had_changes,
        new_movimentos=len(result.new_movimentos),
        new_documentos=len(result.new_documento_ids),
        error=result.error,
    )
    session.add(record)
    await session.flush()
    return record


async def get_last_sync(
    session: AsyncSession,
    numero_cnj: str,
) -> SyncLog | None:
    """Get the last successful sync for a processo."""
    stmt = (
        select(SyncLog)
        .where(
            SyncLog.numero_cnj == numero_cnj,
            SyncLog.success.is_(True),
        )
        .order_by(SyncLog.finished_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_sync_history(
    session: AsyncSession,
    numero_cnj: str,
    limit: int = 20,
) -> list[SyncLog]:
    """Get sync history for a processo."""
    stmt = (
        select(SyncLog)
        .where(SyncLog.numero_cnj == numero_cnj)
        .order_by(SyncLog.finished_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
