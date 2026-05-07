"""CNJ Tabela Processual Unificada — movement code mapper."""

from __future__ import annotations

from dataclasses import dataclass
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
    CUMPRIMENTO = "cumprimento"
    EXECUCAO = "execucao"
    PERICIA = "pericia"
    TUTELA = "tutela"
    NOISE = "noise"
    UNCLASSIFIED = "unclassified"


class Urgencia(str, Enum):
    """Urgency level for a classified movement."""

    CRITICA = "critica"    # Prazo fatal, sentenca, tutela
    ALTA = "alta"          # Decisao recorrivel, intimacao, citacao
    MEDIA = "media"        # Audiencia, pericia, recurso
    BAIXA = "baixa"        # Juntada, cumprimento
    NENHUMA = "nenhuma"    # Noise


@dataclass(frozen=True, slots=True)
class TPUEntry:
    """A TPU code entry with category, urgency, and description."""

    codigo: int
    categoria: CategoriaSemantica
    urgencia: Urgencia
    descricao: str
    requer_acao: bool


# ~150 most common TPU movement codes
_TPU_ENTRIES: list[TPUEntry] = [
    # === Sentenca / decisoes finais ===
    TPUEntry(132, CategoriaSemantica.SENTENCA, Urgencia.CRITICA, "Sentença com resolução do mérito", True),
    TPUEntry(133, CategoriaSemantica.SENTENCA, Urgencia.CRITICA, "Sentença sem resolução do mérito", True),
    TPUEntry(134, CategoriaSemantica.SENTENCA, Urgencia.CRITICA, "Sentença de mérito (procedência)", True),
    TPUEntry(135, CategoriaSemantica.SENTENCA, Urgencia.CRITICA, "Sentença de mérito (improcedência)", True),
    TPUEntry(456, CategoriaSemantica.SENTENCA, Urgencia.CRITICA, "Sentença homologatória", True),
    TPUEntry(871, CategoriaSemantica.SENTENCA, Urgencia.CRITICA, "Sentença estrangeira homologada", True),

    # === Decisao recorrivel ===
    TPUEntry(193, CategoriaSemantica.DECISAO_RECORRIVEL, Urgencia.ALTA, "Decisão", True),
    TPUEntry(60, CategoriaSemantica.DECISAO_RECORRIVEL, Urgencia.ALTA, "Despacho", True),
    TPUEntry(385, CategoriaSemantica.DECISAO_RECORRIVEL, Urgencia.ALTA, "Decisão interlocutória", True),
    TPUEntry(386, CategoriaSemantica.DECISAO_RECORRIVEL, Urgencia.ALTA, "Despacho de mero expediente", False),
    TPUEntry(458, CategoriaSemantica.DECISAO_RECORRIVEL, Urgencia.ALTA, "Decisão monocrática", True),
    TPUEntry(459, CategoriaSemantica.DECISAO_RECORRIVEL, Urgencia.ALTA, "Decisão colegiada", True),

    # === Tutela de urgência ===
    TPUEntry(334, CategoriaSemantica.TUTELA, Urgencia.CRITICA, "Tutela antecipada concedida", True),
    TPUEntry(335, CategoriaSemantica.TUTELA, Urgencia.ALTA, "Tutela antecipada revogada", True),
    TPUEntry(336, CategoriaSemantica.TUTELA, Urgencia.CRITICA, "Liminar concedida", True),
    TPUEntry(337, CategoriaSemantica.TUTELA, Urgencia.ALTA, "Liminar revogada", True),
    TPUEntry(338, CategoriaSemantica.TUTELA, Urgencia.CRITICA, "Tutela cautelar concedida", True),

    # === Trânsito em julgado ===
    TPUEntry(970, CategoriaSemantica.TRANSITO_JULGADO, Urgencia.CRITICA, "Trânsito em julgado", True),
    TPUEntry(22001, CategoriaSemantica.TRANSITO_JULGADO, Urgencia.CRITICA, "Certidão de trânsito em julgado", True),

    # === Audiências / pautas ===
    TPUEntry(51, CategoriaSemantica.PAUTA_MARCADA, Urgencia.MEDIA, "Audiência designada", True),
    TPUEntry(52, CategoriaSemantica.PAUTA_MARCADA, Urgencia.BAIXA, "Audiência realizada", False),
    TPUEntry(53, CategoriaSemantica.PAUTA_MARCADA, Urgencia.MEDIA, "Audiência de conciliação designada", True),
    TPUEntry(54, CategoriaSemantica.PAUTA_MARCADA, Urgencia.MEDIA, "Audiência de instrução designada", True),
    TPUEntry(55, CategoriaSemantica.PAUTA_MARCADA, Urgencia.MEDIA, "Audiência de julgamento designada", True),
    TPUEntry(56, CategoriaSemantica.PAUTA_MARCADA, Urgencia.BAIXA, "Audiência redesignada", True),
    TPUEntry(57, CategoriaSemantica.PAUTA_MARCADA, Urgencia.BAIXA, "Audiência cancelada", False),
    TPUEntry(981, CategoriaSemantica.PAUTA_MARCADA, Urgencia.MEDIA, "Pauta de julgamento", True),

    # === Citação ===
    TPUEntry(12, CategoriaSemantica.CITACAO, Urgencia.ALTA, "Citação", True),
    TPUEntry(13, CategoriaSemantica.CITACAO, Urgencia.ALTA, "Citação por edital", True),
    TPUEntry(15, CategoriaSemantica.CITACAO, Urgencia.ALTA, "Citação por mandado", True),
    TPUEntry(16, CategoriaSemantica.CITACAO, Urgencia.ALTA, "Citação por AR", True),
    TPUEntry(17, CategoriaSemantica.CITACAO, Urgencia.ALTA, "Citação eletrônica", True),
    TPUEntry(340, CategoriaSemantica.CITACAO, Urgencia.ALTA, "Citação com hora certa", True),

    # === Intimação ===
    TPUEntry(14, CategoriaSemantica.INTIMACAO, Urgencia.ALTA, "Intimação", True),
    TPUEntry(18, CategoriaSemantica.INTIMACAO, Urgencia.ALTA, "Intimação por edital", True),
    TPUEntry(19, CategoriaSemantica.INTIMACAO, Urgencia.ALTA, "Intimação por mandado", True),
    TPUEntry(20, CategoriaSemantica.INTIMACAO, Urgencia.ALTA, "Intimação por AR", True),
    TPUEntry(21, CategoriaSemantica.INTIMACAO, Urgencia.ALTA, "Intimação eletrônica", True),
    TPUEntry(341, CategoriaSemantica.INTIMACAO, Urgencia.ALTA, "Intimação da sentença", True),
    TPUEntry(342, CategoriaSemantica.INTIMACAO, Urgencia.ALTA, "Intimação da decisão", True),
    TPUEntry(343, CategoriaSemantica.INTIMACAO, Urgencia.ALTA, "Intimação para manifestação", True),
    TPUEntry(344, CategoriaSemantica.INTIMACAO, Urgencia.ALTA, "Intimação para audiência", True),

    # === Prazos ===
    TPUEntry(85, CategoriaSemantica.PRAZO_ABERTO, Urgencia.CRITICA, "Prazo concedido", True),
    TPUEntry(86, CategoriaSemantica.PRAZO_ABERTO, Urgencia.CRITICA, "Prazo para manifestação", True),
    TPUEntry(87, CategoriaSemantica.PRAZO_ABERTO, Urgencia.CRITICA, "Prazo para recurso", True),
    TPUEntry(88, CategoriaSemantica.PRAZO_ABERTO, Urgencia.CRITICA, "Prazo para cumprimento", True),
    TPUEntry(89, CategoriaSemantica.PRAZO_ABERTO, Urgencia.CRITICA, "Prazo para contestação", True),
    TPUEntry(90, CategoriaSemantica.PRAZO_ABERTO, Urgencia.CRITICA, "Prazo para réplica", True),
    TPUEntry(91, CategoriaSemantica.PRAZO_ABERTO, Urgencia.CRITICA, "Prazo para alegações finais", True),

    # === Recursos ===
    TPUEntry(195, CategoriaSemantica.RECURSO, Urgencia.MEDIA, "Agravo de instrumento", True),
    TPUEntry(196, CategoriaSemantica.RECURSO, Urgencia.MEDIA, "Agravo de petição", True),
    TPUEntry(197, CategoriaSemantica.RECURSO, Urgencia.MEDIA, "Apelação", True),
    TPUEntry(198, CategoriaSemantica.RECURSO, Urgencia.MEDIA, "Recurso ordinário", True),
    TPUEntry(199, CategoriaSemantica.RECURSO, Urgencia.MEDIA, "Embargos de declaração", True),
    TPUEntry(200, CategoriaSemantica.RECURSO, Urgencia.MEDIA, "Recurso de revista", True),
    TPUEntry(201, CategoriaSemantica.RECURSO, Urgencia.MEDIA, "Recurso especial", True),
    TPUEntry(202, CategoriaSemantica.RECURSO, Urgencia.MEDIA, "Recurso extraordinário", True),
    TPUEntry(203, CategoriaSemantica.RECURSO, Urgencia.MEDIA, "Embargos infringentes", True),
    TPUEntry(204, CategoriaSemantica.RECURSO, Urgencia.MEDIA, "Recurso adesivo", True),
    TPUEntry(205, CategoriaSemantica.RECURSO, Urgencia.MEDIA, "Agravo interno", True),
    TPUEntry(206, CategoriaSemantica.RECURSO, Urgencia.MEDIA, "Agravo regimental", True),
    TPUEntry(460, CategoriaSemantica.RECURSO, Urgencia.MEDIA, "Recurso inominado", True),
    TPUEntry(461, CategoriaSemantica.RECURSO, Urgencia.BAIXA, "Recurso recebido", False),
    TPUEntry(462, CategoriaSemantica.RECURSO, Urgencia.BAIXA, "Recurso não recebido", False),
    TPUEntry(463, CategoriaSemantica.RECURSO, Urgencia.MEDIA, "Recurso provido", True),
    TPUEntry(464, CategoriaSemantica.RECURSO, Urgencia.MEDIA, "Recurso não provido", True),
    TPUEntry(465, CategoriaSemantica.RECURSO, Urgencia.MEDIA, "Recurso parcialmente provido", True),

    # === Acordo ===
    TPUEntry(1051, CategoriaSemantica.ACORDO, Urgencia.MEDIA, "Homologação de acordo", True),
    TPUEntry(466, CategoriaSemantica.ACORDO, Urgencia.MEDIA, "Homologação de transação", True),
    TPUEntry(467, CategoriaSemantica.ACORDO, Urgencia.MEDIA, "Acordo judicial", True),

    # === Outcome codes ===
    TPUEntry(1041, CategoriaSemantica.SENTENCA, Urgencia.CRITICA, "Procedência parcial", True),
    TPUEntry(1042, CategoriaSemantica.SENTENCA, Urgencia.CRITICA, "Procedência", True),
    TPUEntry(1043, CategoriaSemantica.SENTENCA, Urgencia.CRITICA, "Improcedência", True),
    TPUEntry(1054, CategoriaSemantica.SENTENCA, Urgencia.CRITICA, "Desistência", True),
    TPUEntry(1044, CategoriaSemantica.SENTENCA, Urgencia.CRITICA, "Extinção sem mérito", True),

    # === Perícia ===
    TPUEntry(470, CategoriaSemantica.PERICIA, Urgencia.MEDIA, "Perícia designada", True),
    TPUEntry(471, CategoriaSemantica.PERICIA, Urgencia.BAIXA, "Perícia realizada", False),
    TPUEntry(472, CategoriaSemantica.PERICIA, Urgencia.MEDIA, "Laudo pericial apresentado", True),
    TPUEntry(473, CategoriaSemantica.PERICIA, Urgencia.MEDIA, "Prazo para quesitos", True),

    # === Cumprimento / Execução ===
    TPUEntry(480, CategoriaSemantica.CUMPRIMENTO, Urgencia.ALTA, "Cumprimento de sentença iniciado", True),
    TPUEntry(481, CategoriaSemantica.EXECUCAO, Urgencia.ALTA, "Penhora realizada", True),
    TPUEntry(482, CategoriaSemantica.EXECUCAO, Urgencia.ALTA, "Bloqueio de valores", True),
    TPUEntry(483, CategoriaSemantica.EXECUCAO, Urgencia.MEDIA, "Hasta pública designada", True),
    TPUEntry(484, CategoriaSemantica.EXECUCAO, Urgencia.ALTA, "Arresto deferido", True),
    TPUEntry(485, CategoriaSemantica.EXECUCAO, Urgencia.ALTA, "Sequestro deferido", True),
    TPUEntry(486, CategoriaSemantica.CUMPRIMENTO, Urgencia.MEDIA, "Satisfação da obrigação", False),
    TPUEntry(487, CategoriaSemantica.EXECUCAO, Urgencia.ALTA, "Execução provisória", True),
    TPUEntry(488, CategoriaSemantica.CUMPRIMENTO, Urgencia.ALTA, "Multa por descumprimento", True),
    TPUEntry(980, CategoriaSemantica.CUMPRIMENTO, Urgencia.MEDIA, "Expedição de alvará", True),
    TPUEntry(972, CategoriaSemantica.CUMPRIMENTO, Urgencia.MEDIA, "Expedição de RPV", True),
    TPUEntry(973, CategoriaSemantica.CUMPRIMENTO, Urgencia.MEDIA, "Expedição de precatório", True),

    # === Juntada ===
    TPUEntry(246, CategoriaSemantica.JUNTADA_DOCUMENTO, Urgencia.BAIXA, "Juntada", False),
    TPUEntry(581, CategoriaSemantica.JUNTADA_DOCUMENTO, Urgencia.BAIXA, "Juntada de petição", False),
    TPUEntry(582, CategoriaSemantica.JUNTADA_DOCUMENTO, Urgencia.BAIXA, "Juntada de documento", False),
    TPUEntry(583, CategoriaSemantica.JUNTADA_DOCUMENTO, Urgencia.BAIXA, "Juntada de procuração", False),
    TPUEntry(584, CategoriaSemantica.JUNTADA_DOCUMENTO, Urgencia.BAIXA, "Juntada de contestação", True),
    TPUEntry(585, CategoriaSemantica.JUNTADA_DOCUMENTO, Urgencia.BAIXA, "Juntada de réplica", False),
    TPUEntry(586, CategoriaSemantica.JUNTADA_DOCUMENTO, Urgencia.MEDIA, "Juntada de laudo", True),
    TPUEntry(587, CategoriaSemantica.JUNTADA_DOCUMENTO, Urgencia.BAIXA, "Juntada de substabelecimento", False),
    TPUEntry(588, CategoriaSemantica.JUNTADA_DOCUMENTO, Urgencia.BAIXA, "Juntada de GRU", False),

    # === Noise (procedural overhead) ===
    TPUEntry(11, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Distribuição", False),
    TPUEntry(22, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Redistribuição", False),
    TPUEntry(26, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Conclusão", False),
    TPUEntry(36, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Vista", False),
    TPUEntry(37, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Vista ao MP", False),
    TPUEntry(38, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Remessa", False),
    TPUEntry(39, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Remessa ao tribunal", False),
    TPUEntry(40, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Recebimento", False),
    TPUEntry(41, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Devolução", False),
    TPUEntry(123, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Certificação", False),
    TPUEntry(124, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Numeração de folhas", False),
    TPUEntry(125, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Desentranhamento", False),
    TPUEntry(126, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Conclusão para despacho", False),
    TPUEntry(127, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Conclusão para sentença", False),
    TPUEntry(128, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Conclusão para decisão", False),
    TPUEntry(490, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Autos findos", False),
    TPUEntry(491, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Arquivamento", False),
    TPUEntry(492, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Desarquivamento", False),
    TPUEntry(493, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Anotação", False),
    TPUEntry(494, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Publicação", False),
    TPUEntry(495, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Expedição de ofício", False),
    TPUEntry(496, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Expedição de carta precatória", False),
    TPUEntry(497, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Expedição de carta rogatória", False),
    TPUEntry(861, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Baixa definitiva", False),
    TPUEntry(862, CategoriaSemantica.NOISE, Urgencia.NENHUMA, "Baixa provisória", False),
]

# Build lookup maps from the entries list
TPU_CATEGORY_MAP: dict[int, CategoriaSemantica] = {
    e.codigo: e.categoria for e in _TPU_ENTRIES
}

TPU_URGENCY_MAP: dict[int, Urgencia] = {
    e.codigo: e.urgencia for e in _TPU_ENTRIES
}

TPU_ENTRY_MAP: dict[int, TPUEntry] = {
    e.codigo: e for e in _TPU_ENTRIES
}

TPU_DESCRIPTION_MAP: dict[int, str] = {
    e.codigo: e.descricao for e in _TPU_ENTRIES
}

# Categories that typically require lawyer action
_ACTIONABLE_CATEGORIES: frozenset[CategoriaSemantica] = frozenset({
    CategoriaSemantica.SENTENCA,
    CategoriaSemantica.DECISAO_RECORRIVEL,
    CategoriaSemantica.PRAZO_ABERTO,
    CategoriaSemantica.PAUTA_MARCADA,
    CategoriaSemantica.CITACAO,
    CategoriaSemantica.INTIMACAO,
    CategoriaSemantica.TUTELA,
    CategoriaSemantica.CUMPRIMENTO,
    CategoriaSemantica.EXECUCAO,
})

# Categories where rule-based classification is high confidence (skip LLM)
HIGH_CONFIDENCE_CATEGORIES: frozenset[CategoriaSemantica] = frozenset({
    CategoriaSemantica.NOISE,
    CategoriaSemantica.SENTENCA,
    CategoriaSemantica.TRANSITO_JULGADO,
    CategoriaSemantica.PRAZO_ABERTO,
    CategoriaSemantica.CITACAO,
    CategoriaSemantica.INTIMACAO,
    CategoriaSemantica.RECURSO,
    CategoriaSemantica.ACORDO,
})


def categorize_movement(tpu_code: int) -> CategoriaSemantica:
    """Map a TPU movement code to a semantic category."""
    return TPU_CATEGORY_MAP.get(tpu_code, CategoriaSemantica.UNCLASSIFIED)


def get_urgency(tpu_code: int) -> Urgencia:
    """Map a TPU movement code to an urgency level."""
    return TPU_URGENCY_MAP.get(tpu_code, Urgencia.MEDIA)


def get_entry(tpu_code: int) -> TPUEntry | None:
    """Get the full TPU entry for a code, or None if unknown."""
    return TPU_ENTRY_MAP.get(tpu_code)


def is_actionable(category: CategoriaSemantica) -> bool:
    """Whether a movement category typically requires lawyer action."""
    return category in _ACTIONABLE_CATEGORIES


def is_high_confidence(tpu_code: int) -> bool:
    """Whether rule-based classification is sufficient (no LLM needed)."""
    entry = TPU_ENTRY_MAP.get(tpu_code)
    if entry is None:
        return False
    return entry.categoria in HIGH_CONFIDENCE_CATEGORIES


def tpu_coverage_stats() -> dict[str, int]:
    """Return stats about TPU mapping coverage."""
    total = len(_TPU_ENTRIES)
    by_category = {}
    for e in _TPU_ENTRIES:
        by_category[e.categoria.value] = by_category.get(e.categoria.value, 0) + 1
    return {"total_codes": total, "by_category": by_category}
