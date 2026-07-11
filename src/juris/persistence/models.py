"""SQLAlchemy models for the juris domain."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Tribunal(Base):
    __tablename__ = "tribunais"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    nome: Mapped[str] = mapped_column(String(200))
    sistema: Mapped[str] = mapped_column(String(20))
    wsdl_url: Mapped[str] = mapped_column(String(500))
    mni_version: Mapped[str] = mapped_column(String(10), default="2.2.2")
    ativo: Mapped[bool] = mapped_column(default=True)

    processos: Mapped[list[Processo]] = relationship(back_populates="tribunal_rel")


class Processo(Base):
    __tablename__ = "processos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    numero_cnj: Mapped[str] = mapped_column(String(25), unique=True, index=True)
    tribunal_id: Mapped[str] = mapped_column(ForeignKey("tribunais.id"))
    classe: Mapped[str | None] = mapped_column(String(200))
    assunto: Mapped[str | None] = mapped_column(Text)
    valor_causa: Mapped[float | None] = mapped_column(Float)
    orgao_julgador: Mapped[str | None] = mapped_column(String(300))
    data_ajuizamento: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grau: Mapped[str | None] = mapped_column(String(20))
    dados_extras: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tribunal_rel: Mapped[Tribunal] = relationship(back_populates="processos")
    movimentos: Mapped[list[Movimento]] = relationship(back_populates="processo", order_by="Movimento.data_hora")
    documentos: Mapped[list[Documento]] = relationship(back_populates="processo")
    partes: Mapped[list[Parte]] = relationship(back_populates="processo")


class Movimento(Base):
    __tablename__ = "movimentos"
    __table_args__ = (
        Index("ix_movimentos_dedup", "processo_id", "data_hora", "codigo_nacional", "id_movimento", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    processo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("processos.id"))
    data_hora: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tipo: Mapped[str] = mapped_column(String(20))  # 'nacional' | 'local'
    codigo_nacional: Mapped[int | None]
    complemento: Mapped[str | None] = mapped_column(Text)
    descricao: Mapped[str | None] = mapped_column(Text)
    id_movimento: Mapped[str | None] = mapped_column(String(100))
    categoria_semantica: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    processo: Mapped[Processo] = relationship(back_populates="movimentos")


class Documento(Base):
    __tablename__ = "documentos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    processo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("processos.id"))
    id_documento_tribunal: Mapped[str] = mapped_column(String(100))
    tipo_documento: Mapped[str] = mapped_column(String(100))
    descricao: Mapped[str | None] = mapped_column(Text)
    data_hora: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mime_type: Mapped[str] = mapped_column(String(50), default="application/pdf")
    storage_key: Mapped[str | None] = mapped_column(String(500))
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None]
    texto_extraido: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    processo: Mapped[Processo] = relationship(back_populates="documentos")


class Parte(Base):
    __tablename__ = "partes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    processo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("processos.id"))
    nome: Mapped[str] = mapped_column(String(300))
    tipo: Mapped[str] = mapped_column(String(50))  # autor, reu, terceiro
    documento: Mapped[str | None] = mapped_column(String(20))  # CPF/CNPJ
    advogados: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    processo: Mapped[Processo] = relationship(back_populates="partes")


class PrazoComputed(Base):
    """Computed deadlines for a processo movement."""

    __tablename__ = "prazos_computed"
    __table_args__ = (
        Index("ix_prazos_processo_status", "processo_id", "status"),
        Index("ix_prazos_data_limite", "data_limite"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    processo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("processos.id"))
    movimento_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("movimentos.id"))
    numero_cnj: Mapped[str] = mapped_column(String(25), index=True)
    rule_nome: Mapped[str] = mapped_column(String(200))
    rule_base_legal: Mapped[str] = mapped_column(String(200))
    tipo_acao: Mapped[str] = mapped_column(String(50))
    categoria: Mapped[str] = mapped_column(String(50))
    data_inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data_limite: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dias_uteis_total: Mapped[int]
    status: Mapped[str] = mapped_column(String(20), default="aberto")  # aberto, proximo, urgente, vencido, cumprido
    urgencia: Mapped[str] = mapped_column(String(20))
    cumprido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cumprido_por: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    processo: Mapped[Processo] = relationship()


class SyncLog(Base):
    """Log of sync operations (overnight, pull-updates, etc.)."""

    __tablename__ = "sync_logs"
    __table_args__ = (
        Index("ix_sync_logs_processo", "numero_cnj", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    numero_cnj: Mapped[str] = mapped_column(String(25))
    tribunal_id: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20))  # mni, datajud
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    success: Mapped[bool] = mapped_column(default=False)
    had_changes: Mapped[bool] = mapped_column(default=False)
    new_movimentos: Mapped[int] = mapped_column(default=0)
    new_documentos: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, object] | None] = mapped_column(JSONB)


class JurisprudenciaRecord(Base):
    """Jurisprudence records for the corpus hierarchy."""

    __tablename__ = "jurisprudencia"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tipo: Mapped[str] = mapped_column(String(50))
    numero: Mapped[str] = mapped_column(String(50))
    tribunal: Mapped[str] = mapped_column(String(20))
    ementa: Mapped[str] = mapped_column(Text)
    texto_integral: Mapped[str | None] = mapped_column(Text)
    hierarquia: Mapped[int]
    temas: Mapped[list[str] | None] = mapped_column(JSONB)
    base_legal: Mapped[list[str] | None] = mapped_column(JSONB)
    situacao: Mapped[str] = mapped_column(String(20), default="vigente")
    relator: Mapped[str | None] = mapped_column(String(200))
    data_julgamento: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AdvogadoCadastrado(Base):
    """Lawyers registered in the system (for multi-tenant)."""

    __tablename__ = "advogados_cadastrados"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cpf: Mapped[str] = mapped_column(String(11), unique=True)
    nome: Mapped[str] = mapped_column(String(300))
    oab_numero: Mapped[str] = mapped_column(String(20))
    oab_uf: Mapped[str] = mapped_column(String(2))
    ativo: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
