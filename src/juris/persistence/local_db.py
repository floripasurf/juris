"""SQLite-based local database for dev/single-user mode.

No PostgreSQL required — stores everything in a local SQLite file.
Uses synchronous SQLAlchemy since SQLite async support is limited.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from juris.core.observability import get_logger
from juris.core.paths import ensure_private_dir, juris_home, restrict_file

logger = get_logger(__name__)


def default_db_path() -> Path:
    """Default local SQLite DB path."""
    return juris_home() / "juris.db"


class LocalBase(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class ProcessoLocal(LocalBase):
    __tablename__ = "processos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    numero_cnj: Mapped[str] = mapped_column(String(25), unique=True, index=True)
    tribunal_id: Mapped[str] = mapped_column(String(20))
    classe: Mapped[str | None] = mapped_column(String(200))
    assunto: Mapped[str | None] = mapped_column(Text)
    valor_causa: Mapped[float | None] = mapped_column(Float)
    orgao_julgador: Mapped[str | None] = mapped_column(String(300))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class MovimentoLocal(LocalBase):
    __tablename__ = "movimentos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    processo_id: Mapped[str] = mapped_column(String(36), index=True)
    data_hora: Mapped[datetime] = mapped_column(DateTime)
    tipo: Mapped[str | None] = mapped_column(String(20))
    codigo_nacional: Mapped[int | None] = mapped_column(Integer)
    complemento: Mapped[str | None] = mapped_column(Text)
    descricao: Mapped[str | None] = mapped_column(Text)
    id_movimento: Mapped[str | None] = mapped_column(String(100))
    categoria_semantica: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PrazoLocal(LocalBase):
    __tablename__ = "prazos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    processo_id: Mapped[str] = mapped_column(String(36), index=True)
    numero_cnj: Mapped[str] = mapped_column(String(25), index=True)
    rule_nome: Mapped[str] = mapped_column(String(200))
    rule_base_legal: Mapped[str | None] = mapped_column(String(200))
    tipo_acao: Mapped[str | None] = mapped_column(String(50))
    categoria: Mapped[str | None] = mapped_column(String(50))
    data_inicio: Mapped[datetime] = mapped_column(DateTime)
    data_limite: Mapped[datetime] = mapped_column(DateTime, index=True)
    dias_uteis_total: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="aberto")
    urgencia: Mapped[str | None] = mapped_column(String(20))
    cumprido_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SyncLogLocal(LocalBase):
    __tablename__ = "sync_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    numero_cnj: Mapped[str] = mapped_column(String(25))
    tribunal_id: Mapped[str] = mapped_column(String(20))
    source: Mapped[str | None] = mapped_column(String(20))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    success: Mapped[int] = mapped_column(Integer, default=0)  # SQLite boolean
    had_changes: Mapped[int] = mapped_column(Integer, default=0)
    new_movimentos: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class SentAlertLocal(LocalBase):
    """Delivery ledger for deduping operational deadline alerts."""

    __tablename__ = "sent_alerts"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    alert_key: Mapped[str] = mapped_column(String(64), index=True)
    channel: Mapped[str] = mapped_column(String(20), index=True)
    numero_cnj: Mapped[str] = mapped_column(String(25), index=True)
    prazo_id: Mapped[str] = mapped_column(String(36), index=True)
    level: Mapped[str] = mapped_column(String(20))
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class JurisprudenciaLocal(LocalBase):
    __tablename__ = "jurisprudencia"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tipo: Mapped[str | None] = mapped_column(String(50))
    numero: Mapped[str | None] = mapped_column(String(50))
    tribunal: Mapped[str | None] = mapped_column(String(20))
    ementa: Mapped[str | None] = mapped_column(Text)
    texto_integral: Mapped[str | None] = mapped_column(Text)
    hierarquia: Mapped[int | None] = mapped_column(Integer)
    temas: Mapped[str | None] = mapped_column(Text)  # JSON string
    base_legal: Mapped[str | None] = mapped_column(Text)  # JSON string
    situacao: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class TrackedProcessoLocal(LocalBase):
    """The list of CNJs this store tracks for nightly sync (per-tenant when scoped)."""

    __tablename__ = "tracked_processos"

    numero_cnj: Mapped[str] = mapped_column(String(25), primary_key=True)
    tribunal_id: Mapped[str] = mapped_column(String(20))


class LocalDB:
    """SQLite-backed local database for single-user mode."""

    def __init__(self, db_path: Path | None = None) -> None:
        uses_default_path = db_path is None
        self._path = db_path or default_db_path()
        ensure_private_dir(self._path.parent, restrict_existing=uses_default_path)
        self._engine = create_engine(f"sqlite:///{self._path}", echo=False)
        LocalBase.metadata.create_all(self._engine)
        self._Session = sessionmaker(bind=self._engine)

        # Create FTS5 virtual table for jurisprudencia full-text search
        with self._engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS jurisprudencia_fts "
                    "USING fts5(ementa, texto_integral, content=jurisprudencia, content_rowid=rowid)"
                )
            )
            conn.commit()
        if self._path.exists():
            restrict_file(self._path)

        logger.debug("local_db_init", path=str(self._path))

    def session(self) -> Session:
        return self._Session()

    def ping(self) -> None:
        """Cheap connectivity probe for readiness checks (raises if the DB is unreachable)."""
        with self._engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    def upsert_processo(
        self,
        numero_cnj: str,
        tribunal_id: str,
        classe: str | None = None,
        assunto: str | None = None,
        valor_causa: float | None = None,
        orgao_julgador: str | None = None,
    ) -> str:
        """Upsert a processo, return its ID."""
        with self.session() as s:
            existing = s.query(ProcessoLocal).filter_by(numero_cnj=numero_cnj).first()
            if existing:
                existing.tribunal_id = tribunal_id
                existing.classe = classe or existing.classe
                existing.assunto = assunto or existing.assunto
                existing.valor_causa = valor_causa or existing.valor_causa
                existing.orgao_julgador = orgao_julgador or existing.orgao_julgador
                existing.last_sync_at = datetime.now(UTC)
                existing.updated_at = datetime.now(UTC)
                s.commit()
                return existing.id
            proc = ProcessoLocal(
                numero_cnj=numero_cnj,
                tribunal_id=tribunal_id,
                classe=classe,
                assunto=assunto,
                valor_causa=valor_causa,
                orgao_julgador=orgao_julgador,
                last_sync_at=datetime.now(UTC),
            )
            s.add(proc)
            s.commit()
            return proc.id

    def insert_movimentos(
        self,
        processo_id: str,
        movimentos: list[dict[str, Any]],
    ) -> int:
        """Insert new movimentos (dedup by data_hora + codigo + id_movimento). Returns count inserted."""
        inserted = 0
        with self.session() as s:
            for mov in movimentos:
                existing = (
                    s.query(MovimentoLocal)
                    .filter_by(
                        processo_id=processo_id,
                        data_hora=mov["data_hora"],
                        codigo_nacional=mov.get("codigo_nacional"),
                        id_movimento=mov.get("id_movimento"),
                    )
                    .first()
                )
                if existing is None:
                    s.add(MovimentoLocal(processo_id=processo_id, **mov))
                    inserted += 1
            s.commit()
        return inserted

    def upsert_prazo(
        self,
        processo_id: str,
        numero_cnj: str,
        rule_nome: str,
        data_inicio: datetime,
        data_limite: datetime,
        **kwargs: Any,
    ) -> str:
        """Upsert a computed prazo."""
        with self.session() as s:
            existing = (
                s.query(PrazoLocal)
                .filter_by(
                    numero_cnj=numero_cnj,
                    rule_nome=rule_nome,
                    data_inicio=data_inicio,
                )
                .first()
            )
            if existing:
                existing.status = kwargs.get("status", existing.status)
                existing.urgencia = kwargs.get("urgencia", existing.urgencia)
                existing.updated_at = datetime.now(UTC)
                s.commit()
                return existing.id
            prazo = PrazoLocal(
                processo_id=processo_id,
                numero_cnj=numero_cnj,
                rule_nome=rule_nome,
                data_inicio=data_inicio,
                data_limite=data_limite,
                **kwargs,
            )
            s.add(prazo)
            s.commit()
            return prazo.id

    def log_sync(
        self,
        numero_cnj: str,
        tribunal_id: str,
        source: str,
        success: bool,
        had_changes: bool = False,
        new_movimentos: int = 0,
        error: str | None = None,
    ) -> None:
        """Log a sync operation."""
        now = datetime.now(UTC)
        with self.session() as s:
            s.add(
                SyncLogLocal(
                    numero_cnj=numero_cnj,
                    tribunal_id=tribunal_id,
                    source=source,
                    started_at=now,
                    finished_at=now,
                    success=1 if success else 0,
                    had_changes=1 if had_changes else 0,
                    new_movimentos=new_movimentos,
                    error=error,
                )
            )
            s.commit()

    def get_last_sync(self, numero_cnj: str) -> datetime | None:
        """Get the last successful sync time for a processo."""
        with self.session() as s:
            row = (
                s.query(SyncLogLocal)
                .filter_by(numero_cnj=numero_cnj, success=1)
                .order_by(SyncLogLocal.finished_at.desc())
                .first()
            )
            return row.finished_at if row else None

    def get_sync_overview(self, *, limit: int = 10) -> dict[str, object]:
        """Operational status of the latest nightly/connect sync runs.

        This is intentionally read-only and tenant-local: callers pass the tenant's
        own SQLite DB, so the web console can show whether the overnight routine ran
        without scanning another office's state.
        """
        with self.session() as s:
            recent = (
                s.query(SyncLogLocal)
                .order_by(SyncLogLocal.finished_at.desc(), SyncLogLocal.started_at.desc())
                .limit(limit)
                .all()
            )
            last_success = (
                s.query(SyncLogLocal)
                .filter_by(success=1)
                .order_by(SyncLogLocal.finished_at.desc(), SyncLogLocal.started_at.desc())
                .first()
            )
            last_failure = (
                s.query(SyncLogLocal)
                .filter_by(success=0)
                .order_by(SyncLogLocal.finished_at.desc(), SyncLogLocal.started_at.desc())
                .first()
            )
            return {
                "last_run": _sync_log_payload(recent[0]) if recent else None,
                "last_success_at": _dt_iso(last_success.finished_at) if last_success else None,
                "last_failure_at": _dt_iso(last_failure.finished_at) if last_failure else None,
                "total_runs": s.query(SyncLogLocal).count(),
                "successful_runs": s.query(SyncLogLocal).filter_by(success=1).count(),
                "failed_runs": s.query(SyncLogLocal).filter_by(success=0).count(),
                "recent_failures": [
                    _sync_log_payload(row)
                    for row in (
                        s.query(SyncLogLocal)
                        .filter_by(success=0)
                        .order_by(SyncLogLocal.finished_at.desc(), SyncLogLocal.started_at.desc())
                        .limit(3)
                        .all()
                    )
                ],
                "recent_runs": [_sync_log_payload(row) for row in recent],
            }

    def get_known_movimento_keys(self, processo_id: str) -> set[tuple[datetime | None, int | None, str | None]]:
        """Get existing movement keys for dedup."""
        with self.session() as s:
            rows = s.query(MovimentoLocal).filter_by(processo_id=processo_id).all()
            return {(r.data_hora, r.codigo_nacional, r.id_movimento) for r in rows}

    def get_all_processos(self) -> list[ProcessoLocal]:
        """Get all processos."""
        with self.session() as s:
            return list(s.query(ProcessoLocal).order_by(ProcessoLocal.updated_at.desc()).all())

    def get_processo_by_cnj(self, numero_cnj: str) -> ProcessoLocal | None:
        """Get a processo by CNJ number."""
        with self.session() as s:
            return s.query(ProcessoLocal).filter_by(numero_cnj=numero_cnj).first()

    def get_movimentos_by_cnj(self, numero_cnj: str) -> list[MovimentoLocal]:
        """Get a processo's movimentos, most recent first."""
        with self.session() as s:
            proc = s.query(ProcessoLocal).filter_by(numero_cnj=numero_cnj).first()
            if proc is None:
                return []
            return list(
                s.query(MovimentoLocal).filter_by(processo_id=proc.id).order_by(MovimentoLocal.data_hora.desc()).all()
            )

    def get_pending_prazos(self, numero_cnj: str | None = None) -> list[PrazoLocal]:
        """Get pending (non-cumprido) prazos."""
        with self.session() as s:
            q = s.query(PrazoLocal).filter(PrazoLocal.status != "cumprido")
            if numero_cnj:
                q = q.filter_by(numero_cnj=numero_cnj)
            return list(q.order_by(PrazoLocal.data_limite).all())

    def get_all_prazos(self, numero_cnj: str | None = None) -> list[PrazoLocal]:
        """Get all prazos."""
        with self.session() as s:
            q = s.query(PrazoLocal)
            if numero_cnj:
                q = q.filter_by(numero_cnj=numero_cnj)
            return list(q.order_by(PrazoLocal.data_limite).all())

    def get_sent_alert_keys(self, alert_keys: set[str], *, channel: str = "email") -> set[str]:
        """Return alert fingerprints already delivered through a channel."""
        if not alert_keys:
            return set()
        with self.session() as s:
            rows = (
                s.query(SentAlertLocal.alert_key)
                .filter(SentAlertLocal.channel == channel)
                .filter(SentAlertLocal.alert_key.in_(alert_keys))
                .all()
            )
            return {str(row[0]) for row in rows}

    def mark_alerts_sent(self, records: list[dict[str, str]], *, channel: str = "email") -> int:
        """Record successfully delivered alert fingerprints.

        Idempotent: repeated records are ignored so a retried bookkeeping write does
        not inflate counts.
        """
        if not records:
            return 0
        inserted = 0
        now = datetime.now(UTC)
        with self.session() as s:
            for record in records:
                alert_key = record["alert_key"]
                ledger_id = f"{channel}:{alert_key}"
                if s.get(SentAlertLocal, ledger_id) is not None:
                    continue
                s.add(
                    SentAlertLocal(
                        id=ledger_id,
                        alert_key=alert_key,
                        channel=channel,
                        numero_cnj=record["numero_cnj"],
                        prazo_id=record["prazo_id"],
                        level=record["level"],
                        sent_at=now,
                    )
                )
                inserted += 1
            s.commit()
        return inserted

    def insert_jurisprudencia(
        self,
        tipo: str,
        numero: str,
        tribunal: str,
        ementa: str,
        texto_integral: str | None = None,
        hierarquia: int = 6,
        temas: list[str] | None = None,
        base_legal: list[str] | None = None,
        situacao: str = "vigente",
    ) -> str:
        """Insert a jurisprudencia record. Returns its ID."""
        import json as _json

        with self.session() as s:
            record = JurisprudenciaLocal(
                tipo=tipo,
                numero=numero,
                tribunal=tribunal,
                ementa=ementa,
                texto_integral=texto_integral,
                hierarquia=hierarquia,
                temas=_json.dumps(temas or [], ensure_ascii=False),
                base_legal=_json.dumps(base_legal or [], ensure_ascii=False),
                situacao=situacao,
            )
            s.add(record)
            s.commit()

            # Sync FTS index
            with self._engine.connect() as conn:
                conn.execute(
                    text(
                        "INSERT INTO jurisprudencia_fts(rowid, ementa, texto_integral) "
                        "SELECT rowid, ementa, COALESCE(texto_integral, '') "
                        "FROM jurisprudencia WHERE id = :id"
                    ),
                    {"id": record.id},
                )
                conn.commit()

            return record.id

    def search_fts(self, query: str, limit: int = 10) -> list[JurisprudenciaLocal]:
        """Full-text search on jurisprudencia using FTS5."""
        safe_query = " ".join(word for word in query.split() if word and not word.startswith(("-", "NOT")))
        if not safe_query:
            return []

        with self.session() as s:
            rows = s.execute(
                text(
                    "SELECT j.* FROM jurisprudencia j "
                    "JOIN jurisprudencia_fts f ON j.rowid = f.rowid "
                    "WHERE jurisprudencia_fts MATCH :query "
                    "ORDER BY rank "
                    "LIMIT :limit"
                ),
                {"query": safe_query, "limit": limit},
            ).fetchall()

            # Map rows back to JurisprudenciaLocal objects
            result: list[JurisprudenciaLocal] = []
            for row in rows:
                obj = s.query(JurisprudenciaLocal).filter_by(id=row[0]).first()
                if obj:
                    result.append(obj)
            return result

    def get_tracked_list(self) -> list[dict[str, str]]:
        """The tracked-processo list (``[{"numero_cnj", "tribunal"}, ...]``)."""
        with self.session() as s:
            rows = s.query(TrackedProcessoLocal).all()
            return [{"numero_cnj": str(r.numero_cnj), "tribunal": str(r.tribunal_id)} for r in rows]

    def set_tracked_list(self, entries: list[dict[str, str]]) -> None:
        """Replace the tracked-processo list (full overwrite, deduped by CNJ)."""
        with self.session() as s:
            s.query(TrackedProcessoLocal).delete()
            seen: set[str] = set()
            for entry in entries:
                cnj = entry["numero_cnj"]
                if cnj in seen:
                    continue
                seen.add(cnj)
                s.add(TrackedProcessoLocal(numero_cnj=cnj, tribunal_id=entry["tribunal"]))
            s.commit()

    @property
    def path(self) -> Path:
        return self._path


def _dt_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _sync_log_payload(row: SyncLogLocal) -> dict[str, object]:
    return {
        "numero_cnj": row.numero_cnj,
        "tribunal": row.tribunal_id,
        "source": row.source,
        "started_at": _dt_iso(row.started_at),
        "finished_at": _dt_iso(row.finished_at),
        "success": bool(row.success),
        "had_changes": bool(row.had_changes),
        "new_movimentos": row.new_movimentos,
        "error": row.error,
    }
