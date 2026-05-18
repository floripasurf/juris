"""Prompt template for petition structure extraction (v1)."""

from __future__ import annotations

SYSTEM_PROMPT = (
    "You are a Brazilian legal document analyst specializing in procedural law. "
    "You analyze petition texts and extract their structural components, "
    "argumentation patterns, and legal foundations. "
    "Always respond in valid JSON format. "
    "Use Brazilian Portuguese for all field values."
)

EXTRACT_PROMPT = """Analyze the following petition text and extract its structure.

Petition text:
---
{text}
---

Petition type: {tipo_peticao}

Return a JSON object with the following fields:
- "titulo": string — petition title (e.g., "Petição Inicial - Ação de Indenização")
- "ramo_direito": string — area of law (e.g., "direito civil", "direito do trabalho")
- "fase_processual": string — procedural phase (e.g., "conhecimento", "recursal")
- "estrutura": array of objects, each with:
    - "ordem": integer — section order (1, 2, 3...)
    - "titulo": string — section title
    - "proposito": string — purpose of the section
    - "exemplo_resumido": string — brief example text from the petition
- "cadeia_argumentativa": array of strings — reasoning chain steps
- "padroes_argumentacao": array of strings — argumentation patterns identified
- "fundamento_legal": array of strings — legal foundations (articles, statutes)

Respond ONLY with valid JSON, no additional text."""

EXTRACT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "ramo_direito": {"type": "string"},
        "fase_processual": {"type": "string"},
        "estrutura": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ordem": {"type": "integer"},
                    "titulo": {"type": "string"},
                    "proposito": {"type": "string"},
                    "exemplo_resumido": {"type": "string"},
                },
                "required": ["ordem", "titulo", "proposito", "exemplo_resumido"],
            },
        },
        "cadeia_argumentativa": {"type": "array", "items": {"type": "string"}},
        "padroes_argumentacao": {"type": "array", "items": {"type": "string"}},
        "fundamento_legal": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "titulo",
        "ramo_direito",
        "fase_processual",
        "estrutura",
        "cadeia_argumentativa",
        "padroes_argumentacao",
        "fundamento_legal",
    ],
}
