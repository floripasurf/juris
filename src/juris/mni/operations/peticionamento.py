"""Peticionamento — filing petitions via MNI entregarManifestacaoProcessual."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime

from zeep import Client

from juris.core.observability import get_logger
from juris.mni.retry import mni_retry

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class FilingReceipt:
    """Immutable receipt of a filed petition."""

    sucesso: bool
    mensagem: str
    protocolo: str | None = None
    data_recebimento: datetime | None = None
    numero_processo: str | None = None
    pdf_hash: str | None = None


@mni_retry
def entregar_manifestacao(
    client: Client,
    id_manifestante: str,
    senha_manifestante: str,
    numero_processo: str,
    signed_pdf_bytes: bytes,
    tipo_documento: str,
    descricao: str = "Petição protocolada via sistema integrado",
) -> FilingReceipt:
    """File a signed petition via MNI entregarManifestacaoProcessual.

    Args:
        client: Configured zeep Client for the target tribunal.
        id_manifestante: CPF of the filing lawyer.
        senha_manifestante: Password or CPF.
        numero_processo: CNJ case number.
        signed_pdf_bytes: PAdES-signed PDF content.
        tipo_documento: Document type per tribunal vocabulary.
        descricao: Human-readable description.

    Returns:
        FilingReceipt with protocolo if successful.
    """
    pdf_hash = hashlib.sha256(signed_pdf_bytes).hexdigest()
    pdf_b64 = base64.b64encode(signed_pdf_bytes).decode()

    logger.info(
        "entregar_manifestacao",
        numero_processo=numero_processo,
        tipo_documento=tipo_documento,
        pdf_hash=pdf_hash,
        pdf_size=len(signed_pdf_bytes),
    )

    documento = {
        "idDocumentoVinculado": None,
        "tipoDocumento": tipo_documento,
        "descricao": descricao,
        "mimetype": "application/pdf",
        "conteudo": pdf_b64,
        "hash": pdf_hash,
    }

    response = client.service.entregarManifestacaoProcessual(
        idManifestante=id_manifestante,
        senhaManifestante=senha_manifestante,
        numeroProcesso=numero_processo,
        documento=[documento],
        dataEnvio=datetime.now().isoformat(),
    )

    sucesso = getattr(response, "sucesso", False)
    mensagem = str(getattr(response, "mensagem", ""))
    protocolo = str(getattr(response, "protocoloRecebimento", "")) or None
    data_recebimento = getattr(response, "dataOperacao", None)

    if sucesso:
        logger.info(
            "manifestacao_entregue",
            numero_processo=numero_processo,
            protocolo=protocolo,
            pdf_hash=pdf_hash,
        )
    else:
        logger.error(
            "manifestacao_falhou",
            numero_processo=numero_processo,
            mensagem=mensagem,
        )

    return FilingReceipt(
        sucesso=bool(sucesso),
        mensagem=mensagem,
        protocolo=protocolo,
        data_recebimento=data_recebimento,
        numero_processo=numero_processo,
        pdf_hash=pdf_hash,
    )
