"""consultarProcesso — fetch case data from a tribunal via MNI."""

from __future__ import annotations

from typing import Any

from zeep import Client

from juris.core.observability import get_logger
from juris.core.types import NumeroCNJ
from juris.mni.retry import circuit_breaker, mni_retry

logger = get_logger(__name__)


@mni_retry
def consultar_processo(
    client: Client,
    id_consultante: str,
    senha_consultante: str,
    numero_cnj: str,
    com_documentos: bool = False,
) -> Any:
    """Call MNI consultarProcesso for a given case number.

    Args:
        client: Configured zeep Client for the target tribunal.
        id_consultante: CPF of the querying lawyer.
        senha_consultante: Password or CPF (depending on auth mode).
        numero_cnj: Case number in CNJ format (NNNNNNN-DD.AAAA.J.TR.OOOO).
        com_documentos: If True, include full document PDFs (base64) in response.

    Returns:
        Raw zeep response object matching the MNI XSD.

    Raises:
        ValueError: If the CNJ number format is invalid.
        zeep.exceptions.Fault: On SOAP-level errors.
    """
    # Validate CNJ format
    cnj = NumeroCNJ(numero_cnj)

    logger.info(
        "consultar_processo",
        numero_cnj=str(cnj),
        com_documentos=com_documentos,
    )

    response = client.service.consultarProcesso(
        idConsultante=id_consultante,
        senhaConsultante=senha_consultante,
        numeroProcesso=str(cnj),
        movimentos=True,
        incluirCabecalho=True,
        incluirDocumentos=com_documentos,
    )

    logger.info("consulta_completed", numero_cnj=str(cnj), success=response is not None)
    return response
