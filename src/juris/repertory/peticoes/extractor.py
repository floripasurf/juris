"""Petition structure extraction — uses LLM to analyze petition text."""

from __future__ import annotations

import json
import uuid
from typing import Any

from juris.core.observability import get_logger
from juris.prompts.petition_extractor_v1 import (
    EXTRACT_PROMPT,
    EXTRACT_SCHEMA,
    SYSTEM_PROMPT,
)
from juris.repertory.peticoes.models import SecaoPeticao, TemplatePeticao, TipoPeticao

logger = get_logger(__name__)


async def extract_structure(
    text: str,
    tipo_peticao: TipoPeticao,
    llm: Any,
    petition_id: str = "",
) -> TemplatePeticao:
    """Extract petition structure from text using LLM.

    Args:
        text: Full petition text.
        tipo_peticao: Type of the petition.
        llm: LLM backend (Ollama for PII-bearing content).
        petition_id: Optional ID for the resulting template.

    Returns:
        Extracted TemplatePeticao with sections and patterns.
    """
    if not petition_id:
        petition_id = f"tpl_{tipo_peticao.value}_{uuid.uuid4().hex[:8]}"

    if not text.strip():
        logger.warning("extract_structure_empty_text", petition_id=petition_id)
        return _minimal_template(petition_id, tipo_peticao)

    # Truncate very long texts to avoid exceeding context limits
    max_chars = 30_000
    truncated = text[:max_chars] if len(text) > max_chars else text

    prompt = EXTRACT_PROMPT.format(
        text=truncated,
        tipo_peticao=tipo_peticao.value,
    )

    try:
        response = await llm.complete(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            schema=EXTRACT_SCHEMA,
            max_tokens=2048,
            temperature=0.0,
        )
    except Exception as exc:
        from juris.core.sanitize import safe_error_text

        logger.warning("extract_structure_llm_error", petition_id=petition_id, error=safe_error_text(exc))
        return _minimal_template(petition_id, tipo_peticao)

    # Parse structured response
    data = response.structured
    if data is None:
        # Try parsing content directly
        try:
            data = json.loads(response.content)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "extract_structure_parse_error",
                petition_id=petition_id,
                content_preview=response.content[:200],
            )
            return _minimal_template(petition_id, tipo_peticao)

    return _build_template(petition_id, tipo_peticao, data, text)


def _build_template(
    petition_id: str,
    tipo_peticao: TipoPeticao,
    data: dict[str, Any],
    original_text: str,
) -> TemplatePeticao:
    """Build TemplatePeticao from parsed LLM response data.

    Args:
        petition_id: Template identifier.
        tipo_peticao: Petition type.
        data: Parsed JSON from LLM.
        original_text: Original petition text.

    Returns:
        Constructed TemplatePeticao.
    """
    secoes = []
    for s in data.get("estrutura", []):
        try:
            secoes.append(
                SecaoPeticao(
                    ordem=int(s.get("ordem", 0)),
                    titulo=str(s.get("titulo", "")),
                    proposito=str(s.get("proposito", "")),
                    exemplo_resumido=str(s.get("exemplo_resumido", "")),
                )
            )
        except (TypeError, ValueError):
            continue

    return TemplatePeticao(
        id=petition_id,
        tipo=tipo_peticao,
        titulo=str(data.get("titulo", "")),
        ramo_direito=str(data.get("ramo_direito", "")),
        fase_processual=str(data.get("fase_processual", "")),
        estrutura=secoes,
        cadeia_argumentativa=[str(x) for x in data.get("cadeia_argumentativa", [])],
        padroes_argumentacao=[str(x) for x in data.get("padroes_argumentacao", [])],
        fundamento_legal=[str(x) for x in data.get("fundamento_legal", [])],
        texto_integral=original_text,
    )


def _minimal_template(
    petition_id: str,
    tipo_peticao: TipoPeticao,
) -> TemplatePeticao:
    """Create a minimal template when extraction fails.

    Args:
        petition_id: Template identifier.
        tipo_peticao: Petition type.

    Returns:
        TemplatePeticao with only id and type populated.
    """
    return TemplatePeticao(
        id=petition_id,
        tipo=tipo_peticao,
        titulo="",
        ramo_direito="",
        fase_processual="",
    )
