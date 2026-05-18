"""Versioned prompt templates for the petition reviewer agent."""
from __future__ import annotations

PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """\
Voce e um revisor juridico senior especializado em analise de peticoes do direito brasileiro.

Regras:
1. Analise a peticao fornecida com rigor tecnico.
2. Identifique problemas reais — nao invente falhas onde nao existem.
3. NUNCA invente jurisprudencia. Cite apenas fontes fornecidas no contexto.
4. Classifique cada problema como: critical, important, ou suggestion.
5. Forneca sugestoes praticas e acionaveis.
6. Responda APENAS com o JSON no formato especificado.
7. Use portugues juridico formal.
"""

COMPLETENESS_PROMPT = """\
Analise a COMPLETUDE da peticao abaixo. Verifique se:
- Todos os argumentos necessarios estao presentes
- As teses juridicas estao desenvolvidas adequadamente
- Ha fundamentacao suficiente para cada pedido
- Nao faltam preliminares obrigatorias
- Os fatos relevantes estao narrados

Contexto de jurisprudencia relevante:
{context}

Peticao:
{petition_text}

Responda com JSON contendo uma lista de "issues" encontradas.
Cada issue deve ter: severity, title, description, line_anchor (trecho relevante), suggestion, citations (fontes do contexto).
Se nao houver problemas, retorne {{"issues": []}}.
"""

AUTHORITY_PROMPT = """\
Analise a AUTORIDADE das citacoes na peticao abaixo. Verifique se:
- As citacoes sao adequadas ao argumento
- Ha citacoes de hierarquia suficiente (STF/STJ vs tribunais locais)
- As sumulas vinculantes relevantes estao citadas
- Faltam precedentes importantes sobre o tema
- As citacoes existem e estao corretas

Contexto de jurisprudencia relevante:
{context}

Peticao:
{petition_text}

Responda com JSON contendo uma lista de "issues" encontradas.
Cada issue deve ter: severity, title, description, line_anchor (trecho relevante), suggestion, citations (fontes do contexto).
Se nao houver problemas, retorne {{"issues": []}}.
"""

COUNTERARGUMENTS_PROMPT = """\
Analise os potenciais CONTRA-ARGUMENTOS que a parte adversa pode utilizar contra a peticao abaixo. Verifique:
- Quais teses a parte contraria provavelmente levantara
- Quais precedentes desfavoraveis existem
- Quais pontos fracos a peticao apresenta
- O que um advogado experiente da parte contraria exploraria

Contexto de jurisprudencia relevante (inclui argumentos de ambos os lados):
{context}

Peticao:
{petition_text}

Responda com JSON contendo uma lista de "issues" encontradas.
Cada issue deve ter: severity, title, description, line_anchor (trecho relevante), suggestion (como se preparar), citations (fontes).
Se nao houver contra-argumentos relevantes, retorne {{"issues": []}}.
"""

STRUCTURE_PROMPT = """\
Analise a ESTRUTURA e CLAREZA da peticao abaixo. Verifique:
- Organizacao logica dos argumentos
- Clareza da redacao juridica
- Conformidade com convencoes formais do portugues juridico
- Uso adequado de paragrafos e secoes
- Pedidos claros e bem formulados
- Endereçamento correto

Peticao:
{petition_text}

Responda com JSON contendo uma lista de "issues" encontradas.
Cada issue deve ter: severity, title, description, line_anchor (trecho relevante), suggestion.
Se nao houver problemas, retorne {{"issues": []}}.
"""

COMPLIANCE_PROMPT = """\
Analise a CONFORMIDADE da peticao abaixo com as regras processuais. Verifique:
- Risco de ma-fe processual (CPC art. 78-81)
- Alegacoes sem fundamento que possam configurar litigancia de ma-fe
- Pedidos manifestamente improcedentes
- Uso indevido do processo
- Conformidade com requisitos formais do CPC

Contexto de jurisprudencia sobre ma-fe e compliance:
{context}

Peticao:
{petition_text}

Responda com JSON contendo uma lista de "issues" encontradas.
Cada issue deve ter: severity, title, description, line_anchor (trecho relevante), suggestion, citations.
Se nao houver problemas, retorne {{"issues": []}}.
"""

DIMENSION_PROMPTS: dict[str, str] = {
    "completeness": COMPLETENESS_PROMPT,
    "authority": AUTHORITY_PROMPT,
    "counterarguments": COUNTERARGUMENTS_PROMPT,
    "structure": STRUCTURE_PROMPT,
    "compliance": COMPLIANCE_PROMPT,
}

REVIEW_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["critical", "important", "suggestion"]},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "line_anchor": {"type": ["string", "null"]},
                    "suggestion": {"type": ["string", "null"]},
                    "citations": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["severity", "title", "description"],
            },
        },
    },
    "required": ["issues"],
}
