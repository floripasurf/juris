"""Versioned prompt templates for the movement analyzer agent."""

from __future__ import annotations

PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """\
Você é um assistente jurídico especializado em direito processual brasileiro.
Sua tarefa é analisar movimentações processuais e classificá-las.

Regras:
1. Classifique a movimentação em uma das categorias fornecidas.
2. Atribua um nível de urgência: critica, alta, media, baixa, nenhuma.
3. Identifique se requer ação do advogado (prazo, recurso, manifestação).
4. Se houver prazo, estime o prazo em dias úteis com base no CPC/CLT.
5. Resuma a recomendação de ação em até 2 frases.
6. NÃO invente informações. Se não tiver certeza, diga "incerto".
"""

CLASSIFY_PROMPT = """\
Analise a movimentação processual abaixo e retorne um JSON com a classificação.

Processo: {numero_cnj}
Tribunal: {tribunal}
Código TPU: {codigo_tpu}
Descrição: {descricao}
Complemento: {complemento}
Data: {data_hora}

Categorias possíveis: prazo_aberto, decisao_recorrivel, pauta_marcada, \
juntada_documento, sentenca, transito_julgado, citacao, intimacao, recurso, \
acordo, cumprimento, execucao, pericia, tutela, noise, unclassified

Responda APENAS com o JSON no formato:
{{
  "categoria": "<categoria>",
  "urgencia": "<critica|alta|media|baixa|nenhuma>",
  "requer_acao": true/false,
  "prazo_dias_uteis": null ou número,
  "recomendacao": "<ação recomendada em até 2 frases>",
  "confianca": <0.0 a 1.0>
}}
"""

CLASSIFY_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "categoria": {"type": "string"},
        "urgencia": {"type": "string", "enum": ["critica", "alta", "media", "baixa", "nenhuma"]},
        "requer_acao": {"type": "boolean"},
        "prazo_dias_uteis": {"type": ["integer", "null"]},
        "recomendacao": {"type": "string"},
        "confianca": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": ["categoria", "urgencia", "requer_acao", "recomendacao", "confianca"],
}
