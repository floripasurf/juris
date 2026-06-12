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


# --- PKCS#11 mTLS variant (tribunals requiring a client certificate) ---

_AVISOS_SOAP_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns="{namespace}">
  <soap:Body>
    <ns:consultarAvisosPendentes>
      <idConsultante>{id_consultante}</idConsultante>
      <senhaConsultante>{senha_consultante}</senhaConsultante>
    </ns:consultarAvisosPendentes>
  </soap:Body>
</soap:Envelope>"""


def consultar_avisos_pendentes_pkcs11(
    host: str,
    path: str,
    pkcs11_config: Any,
    id_consultante: str,
    senha_consultante: str,
    mni_version: str = "2.2.3",
) -> AvisosResult:
    """Fetch pending avisos via PKCS#11 mTLS (e.g. TJMG).

    Mirrors :func:`consultar_avisos_pendentes` but talks to the tribunal
    over the hardware-token mTLS transport instead of zeep.

    Args:
        host: Tribunal hostname.
        path: SOAP endpoint path.
        pkcs11_config: PKCS#11 token configuration.
        id_consultante: Consultant CPF.
        senha_consultante: PJe application password.
        mni_version: MNI namespace version.

    Returns:
        AvisosResult with parsed avisos (sucesso=False on error).
    """
    from xml.etree import ElementTree as ET

    from juris.mni.operations.consulta_pkcs11 import (
        _MNI_NAMESPACES,
        _find_recursive,
        _local_name,
        _xml_escape,
    )
    from juris.mni.pkcs11_transport import extract_soap_body, pkcs11_soap_call

    namespace = _MNI_NAMESPACES.get(mni_version, _MNI_NAMESPACES["2.2.3"])
    soap_xml = _AVISOS_SOAP_TEMPLATE.format(
        namespace=namespace,
        id_consultante=_xml_escape(id_consultante),
        senha_consultante=_xml_escape(senha_consultante),
    )

    logger.info("consultar_avisos_pendentes_pkcs11", host=host, id_consultante=id_consultante)

    try:
        response = pkcs11_soap_call(host=host, path=path, soap_xml=soap_xml, config=pkcs11_config, timeout=60)
    except Exception as e:
        logger.warning("avisos_pkcs11_transport_error", error=str(e))
        return AvisosResult(sucesso=False, mensagem=f"{type(e).__name__}: {e}")

    if not response.ok:
        return AvisosResult(sucesso=False, mensagem=f"HTTP {response.status_code}")

    xml_body = extract_soap_body(response)
    try:
        root = ET.fromstring(xml_body)  # noqa: S314 — tribunal-controlled SOAP
    except ET.ParseError as e:
        return AvisosResult(sucesso=False, mensagem=f"XML parse error: {e}")

    sucesso_elem = _find_recursive(root, "sucesso")
    mensagem_elem = _find_recursive(root, "mensagem")
    sucesso = (sucesso_elem.text or "").strip().lower() == "true" if sucesso_elem is not None else False
    mensagem = (mensagem_elem.text or "") if mensagem_elem is not None else ""

    if not sucesso:
        return AvisosResult(sucesso=False, mensagem=mensagem)

    avisos = [_parse_aviso_xml(e) for e in root.iter() if _local_name(e.tag) == "aviso"]
    logger.info("avisos_pkcs11_ok", count=len(avisos))
    return AvisosResult(sucesso=True, mensagem=mensagem, avisos=avisos)


def _parse_aviso_xml(elem: Any) -> Aviso:
    """Parse an <aviso> element (attributes or child elements) into an Aviso."""
    from juris.mni.operations.consulta_pkcs11 import _local_name

    def _get(name: str) -> str:
        val = elem.get(name)
        if val:
            return str(val)
        for child in elem:
            if _local_name(child.tag) == name:
                return child.text or ""
        return ""

    return Aviso(
        id_aviso=_get("idAviso"),
        tipo_comunicacao=_get("tipoComunicacao"),
        numero_processo=_get("numeroProcesso"),
        orgao_julgador=_get("orgaoJulgador") or None,
    )
