"""Prazo rules — maps movement categories to deadline durations.

Based on CPC (Código de Processo Civil), CLT, and common procedural rules.
Each rule defines: which movement triggers the deadline, how many dias úteis,
and what action is expected.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from juris.mni.tpu import CategoriaSemantica


class TipoAcao(StrEnum):
    """Type of action required by a deadline."""

    CONTESTAR = "contestar"
    RECORRER = "recorrer"
    MANIFESTAR = "manifestar"
    COMPARECER = "comparecer"
    CUMPRIR = "cumprir"
    EMBARGAR = "embargar"
    IMPUGNAR = "impugnar"
    PAGAR = "pagar"
    INFORMAR = "informar"


@dataclass(frozen=True, slots=True)
class PrazoRule:
    """A single deadline rule."""

    nome: str
    categoria_trigger: CategoriaSemantica
    codigo_tpu: int | None  # None = applies to all codes in the category
    dias_uteis: int
    tipo_acao: TipoAcao
    base_legal: str
    fatal: bool = True  # If True, missing this deadline = preclusão
    # If True, this rule is eligible for prazo em dobro (arts. 180/183/186 CPC)
    # when the caller declares a parte_representada. False for rules that are
    # themselves a "prazo próprio" (exception under the §§2º/4º) or governed by
    # an incompatible regime (e.g. art. 523 cumprimento — Fazenda follows arts.
    # 534-535 instead) or CLT rules (dobra is a CPC benefit, out of scope for
    # Justiça do Trabalho).
    admite_dobro: bool = True


# CPC-based deadline rules (most common in cível)
CPC_RULES: list[PrazoRule] = [
    # === Contestação ===
    PrazoRule(
        nome="Contestação",
        categoria_trigger=CategoriaSemantica.CITACAO,
        codigo_tpu=None,
        dias_uteis=15,
        tipo_acao=TipoAcao.CONTESTAR,
        base_legal="Art. 335 CPC",
    ),
    # === Réplica ===
    PrazoRule(
        nome="Réplica à contestação",
        categoria_trigger=CategoriaSemantica.INTIMACAO,
        codigo_tpu=343,  # Intimação para manifestação
        dias_uteis=15,
        tipo_acao=TipoAcao.MANIFESTAR,
        base_legal="Art. 351 CPC",
    ),
    # === Apelação ===
    PrazoRule(
        nome="Apelação",
        categoria_trigger=CategoriaSemantica.SENTENCA,
        codigo_tpu=None,
        dias_uteis=15,
        tipo_acao=TipoAcao.RECORRER,
        base_legal="Art. 1.003 §5º CPC",
    ),
    # === Embargos de declaração ===
    PrazoRule(
        nome="Embargos de declaração",
        categoria_trigger=CategoriaSemantica.SENTENCA,
        codigo_tpu=None,
        dias_uteis=5,
        tipo_acao=TipoAcao.EMBARGAR,
        base_legal="Art. 1.023 CPC",
    ),
    PrazoRule(
        nome="Embargos de declaração (decisão)",
        categoria_trigger=CategoriaSemantica.DECISAO_RECORRIVEL,
        codigo_tpu=None,
        dias_uteis=5,
        tipo_acao=TipoAcao.EMBARGAR,
        base_legal="Art. 1.023 CPC",
    ),
    # === Agravo de instrumento ===
    PrazoRule(
        nome="Agravo de instrumento",
        categoria_trigger=CategoriaSemantica.DECISAO_RECORRIVEL,
        codigo_tpu=385,  # Decisão interlocutória
        dias_uteis=15,
        tipo_acao=TipoAcao.RECORRER,
        base_legal="Art. 1.015 c/c Art. 1.003 §5º CPC",
    ),
    # === Contrarrazões ===
    PrazoRule(
        nome="Contrarrazões de apelação",
        categoria_trigger=CategoriaSemantica.RECURSO,
        codigo_tpu=197,  # Apelação
        dias_uteis=15,
        tipo_acao=TipoAcao.MANIFESTAR,
        base_legal="Art. 1.010 §1º CPC",
    ),
    PrazoRule(
        nome="Contrarrazões de agravo",
        categoria_trigger=CategoriaSemantica.RECURSO,
        codigo_tpu=195,  # Agravo de instrumento
        dias_uteis=15,
        tipo_acao=TipoAcao.MANIFESTAR,
        base_legal="Art. 1.019 II CPC",
    ),
    # === Cumprimento de sentença ===
    PrazoRule(
        nome="Pagamento voluntário (cumprimento)",
        categoria_trigger=CategoriaSemantica.CUMPRIMENTO,
        codigo_tpu=480,
        dias_uteis=15,
        tipo_acao=TipoAcao.PAGAR,
        base_legal="Art. 523 CPC",
        admite_dobro=False,  # Regime da Fazenda é outro (arts. 534-535 CPC), não este fluxo comum
    ),
    PrazoRule(
        nome="Impugnação ao cumprimento",
        categoria_trigger=CategoriaSemantica.CUMPRIMENTO,
        codigo_tpu=480,
        dias_uteis=15,
        tipo_acao=TipoAcao.IMPUGNAR,
        base_legal="Art. 525 CPC",
    ),
    # === Tutela / liminar ===
    PrazoRule(
        nome="Cumprimento de tutela antecipada",
        categoria_trigger=CategoriaSemantica.TUTELA,
        codigo_tpu=334,
        dias_uteis=5,
        tipo_acao=TipoAcao.CUMPRIR,
        base_legal="Art. 297 CPC",
        fatal=True,
        admite_dobro=False,  # Prazo próprio de cumprimento; dobra não se estende — direção segura
    ),
    # === Execução — embargos ===
    PrazoRule(
        nome="Embargos à execução",
        categoria_trigger=CategoriaSemantica.EXECUCAO,
        codigo_tpu=481,  # Penhora realizada
        dias_uteis=15,
        tipo_acao=TipoAcao.EMBARGAR,
        base_legal="Art. 915 CPC",
    ),
    # === Manifestação genérica ===
    PrazoRule(
        nome="Manifestação sobre documento",
        categoria_trigger=CategoriaSemantica.JUNTADA_DOCUMENTO,
        codigo_tpu=584,  # Juntada de contestação
        dias_uteis=15,
        tipo_acao=TipoAcao.MANIFESTAR,
        base_legal="Art. 437 §1º CPC",
    ),
    PrazoRule(
        nome="Manifestação sobre laudo pericial",
        categoria_trigger=CategoriaSemantica.PERICIA,
        codigo_tpu=472,  # Laudo pericial apresentado
        dias_uteis=15,
        tipo_acao=TipoAcao.MANIFESTAR,
        base_legal="Art. 477 §1º CPC",
    ),
    # === Prazo genérico (juiz define) ===
    PrazoRule(
        nome="Prazo judicial genérico",
        categoria_trigger=CategoriaSemantica.PRAZO_ABERTO,
        codigo_tpu=None,
        dias_uteis=5,
        tipo_acao=TipoAcao.MANIFESTAR,
        base_legal="Art. 218 §3º CPC (prazo mínimo)",
        fatal=True,
        admite_dobro=False,  # Prazo fixado pelo juiz = prazo próprio, exceção expressa dos §§2º/4º
    ),
]

# CLT-specific rules (Justiça do Trabalho). Prazo em dobro (arts. 180/183/186 CPC)
# is a CPC benefit and does not extend to CLT rules — admite_dobro=False on all.
CLT_RULES: list[PrazoRule] = [
    PrazoRule(
        nome="Contestação trabalhista",
        categoria_trigger=CategoriaSemantica.CITACAO,
        codigo_tpu=None,
        dias_uteis=15,
        tipo_acao=TipoAcao.CONTESTAR,
        base_legal="Art. 847 CLT c/c Reforma Trabalhista",
        admite_dobro=False,
    ),
    PrazoRule(
        nome="Recurso ordinário trabalhista",
        categoria_trigger=CategoriaSemantica.SENTENCA,
        codigo_tpu=None,
        dias_uteis=8,
        tipo_acao=TipoAcao.RECORRER,
        base_legal="Art. 895 CLT",
        admite_dobro=False,
    ),
    PrazoRule(
        nome="Embargos de declaração trabalhista",
        categoria_trigger=CategoriaSemantica.SENTENCA,
        codigo_tpu=None,
        dias_uteis=5,
        tipo_acao=TipoAcao.EMBARGAR,
        base_legal="Art. 897-A CLT",
        admite_dobro=False,
    ),
]


def _match_rule(
    rule: PrazoRule,
    categoria: CategoriaSemantica,
    codigo_tpu: int | None,
) -> bool:
    """Check if a rule matches the given category and TPU code."""
    if rule.categoria_trigger != categoria:
        return False
    return not (rule.codigo_tpu is not None and rule.codigo_tpu != codigo_tpu)


def find_applicable_rules(
    categoria: CategoriaSemantica,
    codigo_tpu: int | None = None,
    justica: str = "civel",
) -> list[PrazoRule]:
    """Find all applicable prazo rules for a given movement.

    Args:
        categoria: Semantic category of the movement.
        codigo_tpu: TPU code (optional, for more specific matching).
        justica: "civel" (CPC) or "trabalho" (CLT).

    Returns:
        List of matching PrazoRule entries, sorted by dias_uteis ascending.
    """
    rules = CPC_RULES if justica != "trabalho" else CLT_RULES
    matched = [r for r in rules if _match_rule(r, categoria, codigo_tpu)]

    # If we have specific-code matches, prefer them over generic (codigo_tpu=None)
    specific = [r for r in matched if r.codigo_tpu is not None]
    if specific:
        return sorted(specific, key=lambda r: r.dias_uteis)

    return sorted(matched, key=lambda r: r.dias_uteis)


def shortest_deadline(
    categoria: CategoriaSemantica,
    codigo_tpu: int | None = None,
    justica: str = "civel",
) -> PrazoRule | None:
    """Return the shortest (most urgent) applicable deadline rule."""
    rules = find_applicable_rules(categoria, codigo_tpu, justica)
    return rules[0] if rules else None
