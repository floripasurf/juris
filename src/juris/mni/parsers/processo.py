"""Parse MNI consultarProcesso response into domain objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Parte:
    """A party in a legal process."""

    nome: str
    tipo: str  # autor, reu, terceiro, etc.
    documento: str | None = None  # CPF/CNPJ
    advogados: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Movimento:
    """A single movement (event) in a process."""

    data_hora: datetime | None  # None when the MNI payload had no/invalid dataHora
    tipo: str  # movimentoNacional or movimentoLocal
    codigo_nacional: int | None = None
    complemento: str | None = None
    descricao: str | None = None
    id_movimento: str | None = None


@dataclass(frozen=True, slots=True)
class Documento:
    """A document attached to a process or movement."""

    id_documento: str
    tipo_documento: str
    descricao: str | None = None
    data_hora: datetime | None = None
    mime_type: str = "application/pdf"
    conteudo_base64: str | None = None  # Only present when incluirDocumentos=True
    hash_sha256: str | None = None


@dataclass(slots=True)
class ProcessoDomain:
    """Domain model for a Brazilian legal process parsed from MNI response."""

    numero_cnj: str
    classe: str | None = None
    assunto: str | None = None
    valor_causa: float | None = None
    orgao_julgador: str | None = None
    tribunal: str | None = None
    sistema: str | None = None
    partes: list[Parte] = field(default_factory=list)
    movimentos: list[Movimento] = field(default_factory=list)
    documentos: list[Documento] = field(default_factory=list)
    data_ajuizamento: datetime | None = None
    grau: str | None = None  # 1, 2, superior
    raw_response: dict[str, Any] | None = None

    @property
    def ultimo_movimento(self) -> Movimento | None:
        """Most recent movement."""
        if not self.movimentos:
            return None
        return max(self.movimentos, key=_mov_sort_key)


def parse_processo(response: Any, tribunal_id: str | None = None) -> ProcessoDomain:
    """Parse a raw MNI consultarProcesso response into a ProcessoDomain.

    Args:
        response: Raw zeep response from consultarProcesso.
        tribunal_id: Optional tribunal identifier for metadata.

    Returns:
        Parsed ProcessoDomain object.
    """
    processo_data = response if not hasattr(response, "processo") else response.processo

    # Parse basic data
    dados = getattr(processo_data, "dadosBasicos", None)

    movimentos_raw = getattr(processo_data, "movimento", None) or []
    movimentos = [_parse_movimento(m) for m in movimentos_raw]

    documentos_raw = getattr(processo_data, "documento", None) or []
    documentos = [_parse_documento(d) for d in documentos_raw]

    partes_raw = getattr(dados, "polo", None) or [] if dados else []
    partes = _parse_partes(partes_raw)

    return ProcessoDomain(
        numero_cnj=str(getattr(dados, "numero", "") if dados else getattr(processo_data, "numero", "")),
        classe=str(getattr(dados, "classeProcessual", None)) if dados else None,
        assunto=str(getattr(dados, "assuntoLocal", None) or getattr(dados, "assunto", None)) if dados else None,
        valor_causa=float(getattr(dados, "valorCausa", 0)) if dados and getattr(dados, "valorCausa", None) else None,
        orgao_julgador=str(getattr(dados, "orgaoJulgador", None)) if dados else None,
        tribunal=tribunal_id,
        movimentos=sorted(movimentos, key=_mov_sort_key),
        documentos=documentos,
        partes=partes,
        data_ajuizamento=getattr(dados, "dataAjuizamento", None) if dados else None,
    )


_MOV_SORT_MIN = datetime.min.replace(tzinfo=UTC)


def _mov_sort_key(m: Movimento) -> datetime:
    """Sort key that places undated movements (data_hora=None) first."""
    return m.data_hora or _MOV_SORT_MIN


def _parse_movimento(raw: Any) -> Movimento:
    """Parse a single movement from the MNI response."""
    mov_nacional = getattr(raw, "movimentoNacional", None)
    mov_local = getattr(raw, "movimentoLocal", None)

    codigo = None
    descricao = None
    tipo = "local"

    if mov_nacional:
        codigo = int(getattr(mov_nacional, "codigoNacional", 0))
        descricao = str(getattr(mov_nacional, "descricao", ""))
        tipo = "nacional"
    elif mov_local:
        descricao = str(getattr(mov_local, "descricao", ""))

    raw_data = getattr(raw, "dataHora", None)
    return Movimento(
        # Never default to datetime.min — a phantom 0001-01-01 becomes a catastrophic
        # "VENCIDO -508785d" prazo. None routes the movement to manual review instead.
        data_hora=raw_data if isinstance(raw_data, datetime) else None,
        tipo=tipo,
        codigo_nacional=codigo,
        complemento=str(getattr(raw, "complementoNacional", "") or ""),
        descricao=descricao,
        id_movimento=str(getattr(raw, "identificadorMovimento", "") or ""),
    )


def _parse_documento(raw: Any) -> Documento:
    """Parse a single document from the MNI response."""
    return Documento(
        id_documento=str(getattr(raw, "idDocumento", "")),
        tipo_documento=str(getattr(raw, "tipoDocumento", "")),
        descricao=str(getattr(raw, "descricao", "") or ""),
        data_hora=getattr(raw, "dataHora", None),
        mime_type=str(getattr(raw, "mimetype", "application/pdf")),
        conteudo_base64=getattr(raw, "conteudo", None),
        hash_sha256=getattr(raw, "hash", None),
    )


def _parse_partes(polos: Any) -> list[Parte]:
    """Parse parties from polo data."""
    partes: list[Parte] = []
    for polo in polos:
        tipo_polo = str(getattr(polo, "polo", ""))
        pessoas = getattr(polo, "parte", None) or []
        for pessoa in pessoas:
            nome = str(getattr(pessoa, "nome", ""))
            documento = str(getattr(pessoa, "numeroDocumentoPrincipal", "") or "")
            advs = getattr(pessoa, "advogado", None) or []
            advogados = [str(getattr(a, "nome", "")) for a in advs]
            partes.append(Parte(nome=nome, tipo=tipo_polo, documento=documento or None, advogados=advogados))
    return partes
