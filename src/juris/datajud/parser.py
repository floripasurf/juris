"""Parse DataJud API responses into domain objects."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from juris.mni.parsers.processo import (
    Movimento,
    ProcessoDomain,
)


def parse_datajud_processo(source: dict[str, Any]) -> ProcessoDomain:
    """Parse a DataJud _source dict into a ProcessoDomain.

    Args:
        source: The _source dict from a DataJud search hit.

    Returns:
        Parsed ProcessoDomain.
    """
    numero = source.get("numeroProcesso", "")
    classe = source.get("classe", {})
    assuntos = source.get("assuntos", [])
    tribunal = source.get("tribunal", "")
    grau = source.get("grau", "")

    # Format CNJ number: 50823514020178130024 → 5082351-40.2017.8.13.0024
    numero_fmt = _format_cnj(numero) if len(numero) == 20 else numero

    # Parse assuntos into a single string
    assunto_str = "; ".join(a.get("nome", "") for a in assuntos) if assuntos else None

    # Parse orgao julgador from last movement (DataJud doesn't have a top-level field)
    movimentos_raw = source.get("movimentos", [])
    orgao = ""
    if movimentos_raw:
        last_orgao = movimentos_raw[-1].get("orgaoJulgador", {})
        orgao = last_orgao.get("nome", "")

    # Parse ajuizamento
    data_aj = source.get("dataAjuizamento", "")
    data_ajuizamento = _parse_date(data_aj) if data_aj and data_aj != "19000101000000" else None

    movimentos = [_parse_movimento(m) for m in movimentos_raw]
    movimentos.sort(key=lambda m: m.data_hora or datetime.min)

    return ProcessoDomain(
        numero_cnj=numero_fmt,
        classe=classe.get("nome"),
        assunto=assunto_str,
        orgao_julgador=orgao or None,
        tribunal=tribunal.lower() if tribunal else None,
        grau=grau or None,
        movimentos=movimentos,
        data_ajuizamento=data_ajuizamento,
        raw_response=source,
    )


def _parse_movimento(raw: dict[str, Any]) -> Movimento:
    """Parse a DataJud movement dict."""
    data_hora = _parse_date(raw.get("dataHora", ""))

    complementos = raw.get("complementosTabelados", [])
    complemento_str = "; ".join(
        f"{c.get('descricao', '')}: {c.get('nome', '')}"
        for c in complementos
    ) if complementos else None

    return Movimento(
        data_hora=data_hora,
        tipo="nacional",
        codigo_nacional=raw.get("codigo"),
        descricao=raw.get("nome"),
        complemento=complemento_str,
    )


def _parse_date(date_str: str) -> datetime:
    """Parse various DataJud date formats."""
    if not date_str:
        return datetime.min

    # ISO format: 2017-06-19T13:20:04.000Z
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y%m%d%H%M%S",
    ):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return datetime.min


def _format_cnj(numero: str) -> str:
    """Format raw 20-digit CNJ number: NNNNNNNDDAAAAJTROOOO → NNNNNNN-DD.AAAA.J.TR.OOOO."""
    if len(numero) != 20:
        return numero
    return f"{numero[:7]}-{numero[7:9]}.{numero[9:13]}.{numero[13]}.{numero[14:16]}.{numero[16:]}"
