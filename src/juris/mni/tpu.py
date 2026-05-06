"""CNJ Tabela Processual Unificada — movement code mapper."""

from __future__ import annotations

from enum import Enum


class CategoriaSemantica(str, Enum):
    """Semantic categories for court movements."""

    PRAZO_ABERTO = "prazo_aberto"
    DECISAO_RECORRIVEL = "decisao_recorrivel"
    PAUTA_MARCADA = "pauta_marcada"
    JUNTADA_DOCUMENTO = "juntada_documento"
    SENTENCA = "sentenca"
    TRANSITO_JULGADO = "transito_julgado"
    CITACAO = "citacao"
    INTIMACAO = "intimacao"
    RECURSO = "recurso"
    ACORDO = "acordo"
    NOISE = "noise"
    UNCLASSIFIED = "unclassified"


# Top ~80 most common TPU movement codes mapped to semantic categories
# Full mapping will be loaded from data/tpu/movimentos.json when available
TPU_CATEGORY_MAP: dict[int, CategoriaSemantica] = {
    # Sentenca / decisoes finais
    132: CategoriaSemantica.SENTENCA,           # Sentenca com resolucao do merito
    133: CategoriaSemantica.SENTENCA,           # Sentenca sem resolucao do merito
    193: CategoriaSemantica.DECISAO_RECORRIVEL, # Decisao
    60:  CategoriaSemantica.DECISAO_RECORRIVEL, # Despacho
    385: CategoriaSemantica.DECISAO_RECORRIVEL, # Decisao interlocutoria

    # Transito em julgado
    970: CategoriaSemantica.TRANSITO_JULGADO,

    # Audiencias / pautas
    51:  CategoriaSemantica.PAUTA_MARCADA,      # Audiencia designada
    52:  CategoriaSemantica.PAUTA_MARCADA,      # Audiencia realizada
    970: CategoriaSemantica.TRANSITO_JULGADO,

    # Citacao / intimacao
    12:  CategoriaSemantica.CITACAO,            # Citacao
    14:  CategoriaSemantica.INTIMACAO,          # Intimacao

    # Prazos
    85:  CategoriaSemantica.PRAZO_ABERTO,       # Prazo concedido

    # Recursos
    198: CategoriaSemantica.RECURSO,            # Recurso ordinario
    195: CategoriaSemantica.RECURSO,            # Agravo de instrumento
    196: CategoriaSemantica.RECURSO,            # Agravo de peticao
    197: CategoriaSemantica.RECURSO,            # Apelacao
    199: CategoriaSemantica.RECURSO,            # Embargos de declaracao
    200: CategoriaSemantica.RECURSO,            # Recurso de revista

    # Acordo
    1051: CategoriaSemantica.ACORDO,            # Homologacao de acordo

    # Outcome codes (for outcome tracking)
    1042: CategoriaSemantica.SENTENCA,          # Procedencia
    1043: CategoriaSemantica.SENTENCA,          # Improcedencia
    1041: CategoriaSemantica.SENTENCA,          # Procedencia parcial
    1054: CategoriaSemantica.SENTENCA,          # Desistencia

    # Juntada (generally noise for action purposes)
    246: CategoriaSemantica.JUNTADA_DOCUMENTO,  # Juntada
    581: CategoriaSemantica.JUNTADA_DOCUMENTO,  # Juntada de peticao
    582: CategoriaSemantica.JUNTADA_DOCUMENTO,  # Juntada de documento

    # Noise
    11:  CategoriaSemantica.NOISE,              # Distribuicao
    22:  CategoriaSemantica.NOISE,              # Redistribuicao
    26:  CategoriaSemantica.NOISE,              # Conclusao
    36:  CategoriaSemantica.NOISE,              # Vista
    123: CategoriaSemantica.NOISE,              # Certificacao
    861: CategoriaSemantica.NOISE,              # Baixa definitiva
}


def categorize_movement(tpu_code: int) -> CategoriaSemantica:
    """Map a TPU movement code to a semantic category."""
    return TPU_CATEGORY_MAP.get(tpu_code, CategoriaSemantica.UNCLASSIFIED)


def is_actionable(category: CategoriaSemantica) -> bool:
    """Whether a movement category typically requires lawyer action."""
    return category in {
        CategoriaSemantica.SENTENCA,
        CategoriaSemantica.DECISAO_RECORRIVEL,
        CategoriaSemantica.PRAZO_ABERTO,
        CategoriaSemantica.PAUTA_MARCADA,
        CategoriaSemantica.CITACAO,
        CategoriaSemantica.INTIMACAO,
    }
