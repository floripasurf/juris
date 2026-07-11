"""Party search across Brazilian tribunal systems.

Supports:
- ESAJ (e-SAJ): Used by TJSP and other state tribunals. Supports party name
  and CPF/CNPJ search via HTTP GET with session cookies.
- DataJud: CNJ's public API — does NOT index party data, so party search
  is not available through it.
- PJe Consulta Pública: Requires captcha or authentication, not suitable
  for automated search.

The primary search mechanism is ESAJ web scraping, which is the most
reliable automated approach for party search in Brazil.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx

from juris.core.observability import get_logger

logger = get_logger(__name__)

_TIMEOUT = 20


@dataclass(frozen=True, slots=True)
class ProcessoResumo:
    """Summary of a processo found via party search."""

    numero_cnj: str
    tribunal: str
    classe: str
    assunto: str
    orgao_julgador: str
    data_ajuizamento: str
    grau: str
    ultima_atualizacao: str
    polo_ativo: list[str] = field(default_factory=list)
    polo_passivo: list[str] = field(default_factory=list)


# ESAJ base URLs per tribunal
# Format: tribunal_id -> (base_url, system_path)
# cpopg = 1st degree, cposg = 2nd degree
_ESAJ_URLS: dict[str, dict[str, str]] = {
    "tjsp": {
        "base": "https://esaj.tjsp.jus.br",
        "1g": "/cpopg",
        "2g": "/cposg",
    },
    "tjms": {
        "base": "https://esaj.tjms.jus.br",
        "1g": "/cpopg5",
        "2g": "/cposg5",
    },
    "tjal": {
        "base": "https://www2.tjal.jus.br",
        "1g": "/cpopg",
        "2g": "/cposg",
    },
    "tjce": {
        "base": "https://esaj.tjce.jus.br",
        "1g": "/cpopg",
        "2g": "/cposg",
    },
    "tjam": {
        "base": "https://consultasaj.tjam.jus.br",
        "1g": "/cpopg",
        "2g": "/cposg",
    },
    "tjac": {
        "base": "https://esaj.tjac.jus.br",
        "1g": "/cpopg",
    },
}

# Search type codes for ESAJ
_ESAJ_SEARCH_TYPES = {
    "nome": "NMPARTE",
    "cpf": "DOCPARTE",
    "oab": "NUMOAB",
}


def _parse_esaj_results(html: str, tribunal_id: str) -> list[ProcessoResumo]:
    """Parse ESAJ search result HTML into ProcessoResumo list."""
    results: list[ProcessoResumo] = []

    # Split by process entries - each starts with processo.codigo=
    entry_pattern = re.compile(
        r'processo\.codigo=([^&"]+).*?'
        r'([0-9]{7}-[0-9]{2}\.[0-9]{4}\.[0-9]\.[0-9]{2}\.[0-9]{4})',
        re.DOTALL,
    )

    # Find all entries
    entries = entry_pattern.findall(html)
    if not entries:
        return results

    # For each CNJ number found, extract surrounding details
    for _, numero_cnj in entries:
        idx = html.index(numero_cnj)
        # Get a window around the match to extract details
        start = max(0, idx - 200)
        end = min(len(html), idx + 2000)
        block = html[start:end]

        # Extract classe processual
        classe_match = re.search(
            r'classeProcesso["\s>]+([^<]+)', block
        )
        classe = classe_match.group(1).strip() if classe_match else ""

        # Extract assunto
        assunto_match = re.search(
            r'assuntoPrincipalProcesso["\s>]+([^<]+)', block
        )
        assunto = assunto_match.group(1).strip() if assunto_match else ""

        # Extract data/vara (e.g., "24/01/2022 - 35ª Vara Cível")
        data_vara_match = re.search(
            r'dataLocalDistribuicaoProcesso["\s>]+([^<]+)', block
        )
        data_vara = data_vara_match.group(1).strip() if data_vara_match else ""
        data_aj = ""
        orgao = ""
        if " - " in data_vara:
            parts = data_vara.split(" - ", 1)
            data_aj = parts[0].strip()
            orgao = parts[1].strip()
        elif data_vara:
            data_aj = data_vara

        # Extract party name and role
        polo_match = re.search(
            r'tipoDeParticipacao["\s>]+([^<:]+)', block
        )
        polo_tipo = polo_match.group(1).strip().lower() if polo_match else ""

        nome_match = re.search(
            r'nomeParte["\s>]+\s*([^<]+)', block
        )
        nome_parte = nome_match.group(1).strip() if nome_match else ""

        polo_ativo: list[str] = []
        polo_passivo: list[str] = []
        if nome_parte:
            if any(k in polo_tipo for k in ("autor", "requerent", "exequent", "reconvind")):
                polo_ativo.append(nome_parte)
            elif any(k in polo_tipo for k in ("réu", "reu", "requerid", "executad", "reconvint")):
                polo_passivo.append(nome_parte)
            else:
                polo_ativo.append(f"{nome_parte} ({polo_tipo})" if polo_tipo else nome_parte)

        results.append(ProcessoResumo(
            numero_cnj=numero_cnj,
            tribunal=tribunal_id.upper(),
            classe=classe,
            assunto=assunto,
            orgao_julgador=orgao,
            data_ajuizamento=data_aj,
            grau="1",
            ultima_atualizacao="",
            polo_ativo=polo_ativo,
            polo_passivo=polo_passivo,
        ))

    return results


def buscar_por_nome_esaj(
    tribunal_id: str,
    nome: str | None = None,
    cpf: str | None = None,
    grau: str = "1g",
) -> list[ProcessoResumo]:
    """Search an ESAJ tribunal for processos by party name or CPF.

    Args:
        tribunal_id: Tribunal identifier (e.g., 'tjsp').
        nome: Party name to search.
        cpf: CPF/CNPJ document number.
        grau: Degree ('1g' for first, '2g' for second).

    Returns:
        List of ProcessoResumo found.
    """
    config = _ESAJ_URLS.get(tribunal_id.lower())
    if not config:
        return []

    base_url = config["base"]
    path = config.get(grau, config["1g"])

    # Determine search type and value
    if cpf:
        cb_pesquisa = _ESAJ_SEARCH_TYPES["cpf"]
        valor = cpf.replace(".", "").replace("-", "").replace(" ", "")
    elif nome:
        cb_pesquisa = _ESAJ_SEARCH_TYPES["nome"]
        valor = nome
    else:
        return []

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
    }

    logger.debug("esaj_busca_parte", tribunal=tribunal_id, grau=grau)

    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            # Get session cookie
            client.get(f"{base_url}{path}/open.do", headers=headers)

            # Search
            params = {
                "conversationId": "",
                "dadosConsulta.localPesquisa.cdLocal": "-1",
                "cbPesquisa": cb_pesquisa,
                "dadosConsulta.valorConsulta": valor,
                "dadosConsulta.tipoNuProcesso": "UNIFICADO",
            }
            response = client.get(
                f"{base_url}{path}/search.do",
                params=params,
                headers=headers,
            )

            if response.status_code != 200:
                logger.debug("esaj_busca_failed", tribunal=tribunal_id, status=response.status_code)
                return []

            html = response.text

    except (httpx.ConnectError, httpx.TimeoutException, httpx.ConnectTimeout) as e:
        logger.debug("esaj_busca_error", tribunal=tribunal_id, error=str(e))
        return []

    # Check for error messages
    if "Não existem informações disponíveis" in html:
        logger.debug("esaj_no_results", tribunal=tribunal_id)
        return []

    if "Foram encontrados muitos processos" in html:
        logger.warning("esaj_too_many_results", tribunal=tribunal_id)
        return []

    results = _parse_esaj_results(html, tribunal_id)

    # Update grau
    grau_label = "1" if grau == "1g" else "2"
    results = [
        ProcessoResumo(
            numero_cnj=r.numero_cnj,
            tribunal=r.tribunal,
            classe=r.classe,
            assunto=r.assunto,
            orgao_julgador=r.orgao_julgador,
            data_ajuizamento=r.data_ajuizamento,
            grau=grau_label,
            ultima_atualizacao=r.ultima_atualizacao,
            polo_ativo=r.polo_ativo,
            polo_passivo=r.polo_passivo,
        )
        for r in results
    ]

    logger.info("esaj_busca_found", tribunal=tribunal_id, grau=grau, count=len(results))
    return results


def buscar_parte_multi_tribunal(
    nome: str,
    cpf: str | None = None,
    tribunais: list[str] | None = None,
) -> list[ProcessoResumo]:
    """Search for processos by party name across multiple ESAJ tribunals.

    Args:
        nome: Party name.
        cpf: Optional CPF.
        tribunais: Tribunal IDs to search. Defaults to all ESAJ-enabled.

    Returns:
        Combined list of ProcessoResumo, deduplicated by número CNJ.
    """
    if tribunais is None:
        tribunais = list(_ESAJ_URLS.keys())

    all_results: list[ProcessoResumo] = []

    for tribunal_id in tribunais:
        if tribunal_id.lower() not in _ESAJ_URLS:
            logger.debug("esaj_tribunal_not_supported", tribunal=tribunal_id)
            continue

        # Search both degrees
        for grau in ("1g", "2g"):
            # Prefer CPF search if available (more precise)
            if cpf:
                results = buscar_por_nome_esaj(tribunal_id, cpf=cpf, grau=grau)
            else:
                results = buscar_por_nome_esaj(tribunal_id, nome=nome, grau=grau)
            all_results.extend(results)

            # If CPF search returned nothing, try name
            if cpf and not results and nome:
                results = buscar_por_nome_esaj(tribunal_id, nome=nome, grau=grau)
                all_results.extend(results)

    # Dedup by numero_cnj
    seen: set[str] = set()
    unique: list[ProcessoResumo] = []
    for r in all_results:
        if r.numero_cnj not in seen:
            seen.add(r.numero_cnj)
            unique.append(r)

    logger.info(
        "busca_parte_total",
        tribunais=len(tribunais),
        total=len(unique),
    )
    return unique


def list_supported_tribunais() -> list[str]:
    """Return tribunal IDs that support ESAJ party search."""
    return sorted(_ESAJ_URLS.keys())
