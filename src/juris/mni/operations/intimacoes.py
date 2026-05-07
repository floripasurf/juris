"""Intimacoes operations — pending notices and full content retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from zeep import Client

from juris.core.observability import get_logger
from juris.mni.retry import mni_retry

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Aviso:
    """A pending court notice (intimação/citação)."""

    id_aviso: str
    tipo_comunicacao: str  # intimacao, citacao
    numero_processo: str
    data_disponibilizacao: datetime | None = None
    data_limite_ciencia: datetime | None = None
    orgao_julgador: str | None = None
    teor: str | None = None  # Populated by consultarTeorComunicacao


@dataclass(slots=True)
class AvisosResult:
    """Result of consultarAvisosPendentes."""

    sucesso: bool
    mensagem: str
    avisos: list[Aviso] = field(default_factory=list)


@mni_retry
def consultar_avisos_pendentes(
    client: Client,
    id_consultante: str,
    senha_consultante: str,
) -> AvisosResult:
    """Fetch all pending avisos (intimações/citações) for the authenticated user.

    Args:
        client: Configured zeep Client for the target tribunal.
        id_consultante: CPF of the querying lawyer.
        senha_consultante: Password or CPF.

    Returns:
        AvisosResult with parsed avisos.
    """
    logger.info("consultar_avisos_pendentes", id_consultante=id_consultante)

    response = client.service.consultarAvisosPendentes(
        idConsultante=id_consultante,
        senhaConsultante=senha_consultante,
    )

    sucesso = getattr(response, "sucesso", False)
    mensagem = str(getattr(response, "mensagem", ""))

    if not sucesso:
        logger.warning("avisos_pendentes_failed", mensagem=mensagem)
        return AvisosResult(sucesso=False, mensagem=mensagem)

    raw_avisos = getattr(response, "aviso", None) or []
    avisos = [_parse_aviso(a) for a in raw_avisos]

    logger.info("avisos_pendentes_ok", count=len(avisos))
    return AvisosResult(sucesso=True, mensagem=mensagem, avisos=avisos)


@mni_retry
def consultar_teor_comunicacao(
    client: Client,
    id_consultante: str,
    senha_consultante: str,
    id_aviso: str,
) -> str | None:
    """Fetch the full content of a specific court notice.

    Args:
        client: Configured zeep Client.
        id_consultante: CPF.
        senha_consultante: Password.
        id_aviso: The aviso ID from consultarAvisosPendentes.

    Returns:
        The full text content of the notice, or None on failure.
    """
    logger.info("consultar_teor_comunicacao", id_aviso=id_aviso)

    response = client.service.consultarTeorComunicacao(
        idConsultante=id_consultante,
        senhaConsultante=senha_consultante,
        idAviso=id_aviso,
    )

    sucesso = getattr(response, "sucesso", False)
    if not sucesso:
        mensagem = str(getattr(response, "mensagem", ""))
        logger.warning("teor_comunicacao_failed", id_aviso=id_aviso, mensagem=mensagem)
        return None

    teor = getattr(response, "comunicacao", None)
    conteudo = str(getattr(teor, "conteudo", "")) if teor else None

    logger.info("teor_comunicacao_ok", id_aviso=id_aviso)
    return conteudo


@mni_retry
def confirmar_recebimento(
    client: Client,
    id_consultante: str,
    senha_consultante: str,
    id_aviso: str,
) -> bool:
    """Confirm receipt (ciência) of a court notice.

    Args:
        client: Configured zeep Client.
        id_consultante: CPF.
        senha_consultante: Password.
        id_aviso: The aviso ID to confirm.

    Returns:
        True if confirmation was accepted.
    """
    logger.info("confirmar_recebimento", id_aviso=id_aviso)

    response = client.service.confirmarRecebimento(
        idConsultante=id_consultante,
        senhaConsultante=senha_consultante,
        idAviso=id_aviso,
    )

    sucesso = getattr(response, "sucesso", False)
    if not sucesso:
        mensagem = str(getattr(response, "mensagem", ""))
        logger.warning("confirmar_recebimento_failed", id_aviso=id_aviso, mensagem=mensagem)

    return bool(sucesso)


def _parse_aviso(raw: Any) -> Aviso:
    """Parse a single aviso from the MNI response."""
    return Aviso(
        id_aviso=str(getattr(raw, "idAviso", "")),
        tipo_comunicacao=str(getattr(raw, "tipoComunicacao", "")),
        numero_processo=str(getattr(raw, "numeroProcesso", "")),
        data_disponibilizacao=getattr(raw, "dataDisponibilizacao", None),
        data_limite_ciencia=getattr(raw, "dataLimiteCiencia", None),
        orgao_julgador=str(getattr(raw, "orgaoJulgador", "")) or None,
    )
