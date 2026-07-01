"""consultarProcesso via PKCS#11 mTLS — for tribunals requiring client certificate auth."""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Any
from xml.etree import ElementTree as ET

from juris.core.observability import get_logger
from juris.core.types import NumeroCNJ
from juris.mni.parsers.processo import Documento, Movimento, Parte, ProcessoDomain
from juris.mni.pkcs11_transport import (
    PKCS11Config,
    SOAPResponse,
    extract_soap_body,
    pkcs11_soap_call,
)

logger = get_logger(__name__)

# MNI SOAP namespace versions
_MNI_NAMESPACES = {
    "2.2.2": "http://www.cnj.jus.br/servico-intercomunicacao-2.2.2/",
    "2.2.3": "http://www.cnj.jus.br/servico-intercomunicacao-2.2.3/",
}

_SOAP_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns="{namespace}">
  <soap:Body>
    <ns:consultarProcesso>
      <idConsultante>{id_consultante}</idConsultante>
      <senhaConsultante>{senha_consultante}</senhaConsultante>
      <numeroProcesso>{numero_processo}</numeroProcesso>
      <movimentos>{movimentos}</movimentos>
      <incluirCabecalho>{incluir_cabecalho}</incluirCabecalho>
      <incluirDocumentos>{incluir_documentos}</incluirDocumentos>
    </ns:consultarProcesso>
  </soap:Body>
</soap:Envelope>"""


def consultar_processo_pkcs11(
    host: str,
    path: str,
    pkcs11_config: PKCS11Config,
    id_consultante: str,
    senha_consultante: str,
    numero_cnj: str,
    mni_version: str = "2.2.3",
    com_documentos: bool = False,
) -> ConsultaResult:
    """Call MNI consultarProcesso using PKCS#11 mTLS authentication.

    Args:
        host: Tribunal hostname (e.g., 'pje-consulta-publica.tjmg.jus.br').
        path: SOAP endpoint path (e.g., '/pje/intercomunicacao').
        pkcs11_config: PKCS#11 token configuration.
        id_consultante: CPF of the querying lawyer.
        senha_consultante: Password or CPF.
        numero_cnj: Case number in CNJ format.
        mni_version: MNI namespace version ('2.2.2' or '2.2.3').
        com_documentos: Include full document PDFs.

    Returns:
        ConsultaResult with parsed SOAP response data.
    """
    cnj = NumeroCNJ(numero_cnj)
    namespace = _MNI_NAMESPACES.get(mni_version, _MNI_NAMESPACES["2.2.3"])

    soap_xml = _SOAP_TEMPLATE.format(
        namespace=namespace,
        id_consultante=_xml_escape(id_consultante),
        senha_consultante=_xml_escape(senha_consultante),
        numero_processo=str(cnj),
        movimentos="true",
        incluir_cabecalho="true",
        incluir_documentos="true" if com_documentos else "false",
    )

    logger.info(
        "consultar_processo_pkcs11",
        host=host,
        numero_cnj=str(cnj),
        mni_version=mni_version,
    )

    response = pkcs11_soap_call(
        host=host,
        path=path,
        soap_xml=soap_xml,
        config=pkcs11_config,
        timeout=60,
    )

    return _parse_response(response, str(cnj))


class ConsultaResult:
    """Parsed result from a PKCS#11 consultarProcesso call."""

    def __init__(
        self,
        sucesso: bool,
        mensagem: str,
        processo_xml: ET.Element | None = None,
        raw_xml: bytes = b"",
    ) -> None:
        self.sucesso = sucesso
        self.mensagem = mensagem
        self.processo_xml = processo_xml
        self.raw_xml = raw_xml

        # Parse processo fields if available
        self.numero = ""
        self.classe = ""
        self.assunto = ""
        self.orgao_julgador = ""
        self.valor_causa = 0.0
        self.movimentos: list[dict[str, Any]] = []
        self.partes: list[dict[str, Any]] = []
        self.documentos: list[dict[str, Any]] = []

        if processo_xml is not None and sucesso:
            self._parse_processo(processo_xml)

    def _parse_processo(self, root: ET.Element) -> None:
        """Extract processo fields from the XML response."""
        # MNI response structure varies by tribunal; walk it generically.
        self._extract_fields_recursive(root)

    def _extract_fields_recursive(self, elem: ET.Element) -> None:
        """Walk the XML tree and extract known MNI fields."""
        tag = _local_name(elem.tag)

        if tag == "dadosBasicos":
            self.numero = elem.get("numero", "")
            self.classe = elem.get("classeProcessual", "")
            for child in elem:
                child_tag = _local_name(child.tag)
                if child_tag == "assunto" and not self.assunto:
                    self.assunto = child.get("codigoNacional", "")
                elif child_tag == "orgaoJulgador":
                    self.orgao_julgador = child.get("nomeOrgao", "")
                elif child_tag == "valorCausa":
                    with contextlib.suppress(ValueError):
                        self.valor_causa = float(child.text or "0")

        elif tag == "movimento":
            mov = {
                "data": elem.get("dataHora", ""),
                "id": elem.get("identificadorMovimento", ""),
                "codigo": "",
                "descricao": "",
                "complemento": "",
            }
            for child in elem:
                child_tag = _local_name(child.tag)
                if child_tag == "movimentoNacional":
                    mov["codigo"] = child.get("codigoNacional", "")
                    mov["descricao"] = _tpu_descricao(mov["codigo"])
                elif child_tag == "complemento":
                    # Get all text content
                    mov["complemento"] = _get_text(child)
            self.movimentos.append(mov)

        elif tag == "polo":
            polo_tipo = elem.get("polo", "")
            for parte_elem in elem:
                if _local_name(parte_elem.tag) == "parte":
                    pessoa = parte_elem.find(".//{*}pessoa")
                    if pessoa is None:
                        pessoa = parte_elem
                    # MNI carries name/document as attributes on <pessoa>,
                    # with child elements as a fallback for older schemas.
                    advogados: list[str] = []
                    for adv in parte_elem.findall(".//{*}advogado"):
                        adv_nome = adv.get("nome", "") or _child_text(adv, "nome")
                        if adv_nome:
                            advogados.append(adv_nome)
                    parte: dict[str, Any] = {
                        "tipo": polo_tipo,
                        "nome": pessoa.get("nome", "") or _child_text(pessoa, "nome"),
                        "documento": pessoa.get("numeroDocumentoPrincipal", "")
                        or _child_text(pessoa, "numeroDocumentoPrincipal"),
                        "advogados": advogados,
                    }
                    self.partes.append(parte)

        elif tag == "documento" and elem.get("idDocumento"):
            # Only process documents carry idDocumento; party-identity
            # <documento> elements (OAB, CPF, …) use codigoDocumento and
            # must not be mistaken for case documents.
            doc = {
                "id": elem.get("idDocumento", ""),
                "tipo": elem.get("tipoDocumento", ""),
                "descricao": elem.get("descricao", ""),
                "mimetype": elem.get("mimetype", ""),
            }
            self.documentos.append(doc)

        for child in elem:
            self._extract_fields_recursive(child)

    def to_processo_domain(
        self, tribunal_id: str | None = None, numero_cnj: str = ""
    ) -> ProcessoDomain:
        """Convert this result to a :class:`ProcessoDomain` for the diff pipeline.

        Lets the mTLS (PKCS#11) consulta path feed the same differential,
        analysis and prazo machinery as the zeep/password path.

        Args:
            tribunal_id: Tribunal identifier to stamp on the domain object.
            numero_cnj: Queried CNJ, used when the response omits dadosBasicos.

        Returns:
            A :class:`ProcessoDomain` with parsed movimentos, partes, documentos.
        """
        movimentos = [
            Movimento(
                data_hora=_parse_mni_datetime(m.get("data", "")),
                tipo="nacional" if m.get("codigo") else "local",
                codigo_nacional=int(m["codigo"]) if str(m.get("codigo") or "").isdigit() else None,
                complemento=(m.get("complemento") or None),
                descricao=(m.get("descricao") or None),
                id_movimento=(m.get("id") or None),
            )
            for m in self.movimentos
        ]
        partes = [
            Parte(
                nome=p.get("nome", ""),
                tipo=p.get("tipo", ""),
                documento=(p.get("documento") or None),
                advogados=list(p.get("advogados", [])),
            )
            for p in self.partes
        ]
        documentos = [
            Documento(
                id_documento=d.get("id", ""),
                tipo_documento=d.get("tipo", ""),
                descricao=(d.get("descricao") or None),
                mime_type=(d.get("mimetype") or "application/pdf"),
            )
            for d in self.documentos
        ]
        return ProcessoDomain(
            numero_cnj=self.numero or numero_cnj,
            classe=self.classe or None,
            assunto=self.assunto or None,
            valor_causa=self.valor_causa or None,
            orgao_julgador=self.orgao_julgador or None,
            tribunal=tribunal_id,
            movimentos=sorted(movimentos, key=lambda mv: mv.data_hora.timestamp() if mv.data_hora else 0.0),
            partes=partes,
            documentos=documentos,
        )


def _parse_mni_datetime(raw: str) -> datetime:
    """Parse an MNI timestamp (YYYYMMDDHHMMSS[mmm]) into a datetime.

    Falls back to ``datetime.min`` when the value is missing or malformed,
    matching the zeep parser so downstream sorting/dedup stays consistent.
    """
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) < 8:
        return datetime.min
    try:
        year = int(digits[0:4])
        month = int(digits[4:6])
        day = int(digits[6:8])
        hour = int(digits[8:10]) if len(digits) >= 10 else 0
        minute = int(digits[10:12]) if len(digits) >= 12 else 0
        second = int(digits[12:14]) if len(digits) >= 14 else 0
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return datetime.min


def _parse_response(response: SOAPResponse, numero_cnj: str) -> ConsultaResult:
    """Parse the raw SOAP response into a ConsultaResult."""
    if not response.ok:
        return ConsultaResult(
            sucesso=False,
            mensagem=f"HTTP {response.status_code}",
            raw_xml=response.body,
        )

    xml_body = extract_soap_body(response)

    if not xml_body:
        return ConsultaResult(
            sucesso=False,
            mensagem="Empty response body",
            raw_xml=response.body,
        )

    try:
        root = ET.fromstring(xml_body)  # noqa: S314 — tribunal-controlled SOAP, not arbitrary input
    except ET.ParseError as e:
        logger.error("xml_parse_error", error=str(e), body_preview=xml_body[:200])
        return ConsultaResult(
            sucesso=False,
            mensagem=f"XML parse error: {e}",
            raw_xml=xml_body,
        )

    # Check for SOAP Fault
    fault = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault")
    if fault is not None:
        fault_string = fault.findtext("faultstring", "Unknown SOAP Fault")
        return ConsultaResult(
            sucesso=False,
            mensagem=fault_string,
            raw_xml=xml_body,
        )

    # Check MNI success flag
    sucesso_elem = _find_recursive(root, "sucesso")
    mensagem_elem = _find_recursive(root, "mensagem")

    sucesso_text = sucesso_elem.text if sucesso_elem is not None else "true"
    mensagem_text = mensagem_elem.text if mensagem_elem is not None else ""

    sucesso = sucesso_text.lower() == "true" if sucesso_text else True

    return ConsultaResult(
        sucesso=sucesso,
        mensagem=mensagem_text or "",
        processo_xml=root if sucesso else None,
        raw_xml=xml_body,
    )


def _find_recursive(elem: ET.Element, local_name: str) -> ET.Element | None:
    """Find an element by local name (ignoring namespace)."""
    if _local_name(elem.tag) == local_name:
        return elem
    for child in elem:
        found = _find_recursive(child, local_name)
        if found is not None:
            return found
    return None


def _tpu_descricao(codigo: str) -> str:
    """Map a TPU movement code to its human-readable description (empty if unknown)."""
    if not codigo or not codigo.isdigit():
        return ""
    from juris.mni.tpu import get_entry

    entry = get_entry(int(codigo))
    return entry.descricao if entry else ""


def _child_text(elem: ET.Element, local_name: str) -> str:
    """Return the text of the first direct child with the given local name."""
    for child in elem:
        if _local_name(child.tag) == local_name:
            return child.text or ""
    return ""


def _local_name(tag: str) -> str:
    """Strip namespace from an XML tag."""
    if "}" in tag:
        return tag.split("}")[1]
    return tag


def _get_text(elem: ET.Element) -> str:
    """Get all text content from an element and its children."""
    texts = []
    if elem.text:
        texts.append(elem.text)
    for child in elem:
        texts.append(_get_text(child))
        if child.tail:
            texts.append(child.tail)
    return " ".join(t.strip() for t in texts if t.strip())


def _xml_escape(text: str) -> str:
    """Escape special XML characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
