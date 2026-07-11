"""Civil Code prescription periods (CC Art. 205-206 and related statutes)."""

from __future__ import annotations

from juris.defesas.models import PrazoInstituto

# All CC Art. 205-206 prescription periods + related statutes
PRAZOS_PRESCRICAO: list[PrazoInstituto] = [
    # === Art. 205 — Prazo geral ===
    PrazoInstituto(
        tipo_acao="Prazo geral",
        prazo_anos=10,
        base_legal="Art. 205 CC",
        termo_inicial="Data da violacao do direito",
        notas="Aplica-se quando nao houver prazo especifico previsto em lei.",
    ),
    # === Art. 206 par.1 — 1 ano ===
    PrazoInstituto(
        tipo_acao="Hospedagem e alimentacao",
        prazo_anos=1,
        base_legal="Art. 206 par.1 I CC",
        termo_inicial="Data do vencimento da conta",
        notas="Pretensao dos hospedeiros ou fornecedores de viveres.",
    ),
    PrazoInstituto(
        tipo_acao="Seguro",
        prazo_anos=1,
        base_legal="Art. 206 par.1 II CC",
        termo_inicial="Ciencia do fato gerador (sinistro)",
        notas="Segurado contra segurador e vice-versa.",
    ),
    PrazoInstituto(
        tipo_acao="Prestacao de contas",
        prazo_anos=1,
        base_legal="Art. 206 par.1 III CC",
        termo_inicial="Cessacao da administracao",
        notas="Pretensao do credor de prestar contas contra mandatario, tutor, etc.",
    ),
    # === Art. 206 par.2 — 2 anos ===
    PrazoInstituto(
        tipo_acao="Alimentos",
        prazo_anos=2,
        base_legal="Art. 206 par.2 CC",
        termo_inicial="Data do vencimento de cada parcela",
        notas="Pretensao para haver prestacoes alimentares.",
    ),
    # === Art. 206 par.3 — 3 anos ===
    PrazoInstituto(
        tipo_acao="Cobranca de alugueis",
        prazo_anos=3,
        base_legal="Art. 206 par.3 I CC",
        termo_inicial="Data do vencimento de cada parcela",
        notas="Alugueis de predios urbanos ou rusticos.",
    ),
    PrazoInstituto(
        tipo_acao="Enriquecimento sem causa",
        prazo_anos=3,
        base_legal="Art. 206 par.3 IV CC",
        termo_inicial="Data do enriquecimento indevido",
        notas="Pretensao de ressarcimento por enriquecimento sem causa.",
    ),
    PrazoInstituto(
        tipo_acao="Indenizatoria",
        prazo_anos=3,
        base_legal="Art. 206 par.3 V CC",
        termo_inicial="Data do conhecimento do dano e de sua autoria",
        notas="Reparacao civil (inclui danos morais e materiais). Sumula 278 STJ.",
    ),
    PrazoInstituto(
        tipo_acao="Danos morais",
        prazo_anos=3,
        base_legal="Art. 206 par.3 V CC",
        termo_inicial="Data do conhecimento do dano e de sua autoria",
        notas="Mesmo prazo da indenizatoria, por ser especie de reparacao civil.",
    ),
    PrazoInstituto(
        tipo_acao="Seguro DPVAT",
        prazo_anos=3,
        base_legal="Art. 206 par.3 IX CC",
        termo_inicial="Data do acidente de transito",
        notas="Seguro obrigatorio DPVAT. Sumula 405 STJ.",
    ),
    # === Art. 206 par.4 — 4 anos ===
    PrazoInstituto(
        tipo_acao="Tutela e curatela",
        prazo_anos=4,
        base_legal="Art. 206 par.4 CC",
        termo_inicial="Cessacao da tutela ou curatela",
        notas="Pretensao relativa a tutela ou curatela.",
    ),
    # === Art. 206 par.5 — 5 anos ===
    PrazoInstituto(
        tipo_acao="Cobranca",
        prazo_anos=5,
        base_legal="Art. 206 par.5 I CC",
        termo_inicial="Data do vencimento da divida",
        notas="Dividas liquidas constantes de instrumento publico ou particular.",
    ),
    # === Prazos de leis especiais ===
    PrazoInstituto(
        tipo_acao="Responsabilidade contratual",
        prazo_anos=10,
        base_legal="Art. 205 CC",
        termo_inicial="Data do inadimplemento",
        notas="Aplica-se o prazo geral de 10 anos. STJ REsp 1360969.",
    ),
    PrazoInstituto(
        tipo_acao="Pretensao possessoria",
        prazo_anos=1,
        base_legal="Art. 558 CPC c/c Art. 924 CPC",
        termo_inicial="Data do esbulho ou turbacao",
        notas="Acao de forca nova (interdito proibitorio/reintegracao). Apos 1 ano e dia, segue rito comum.",
    ),
    PrazoInstituto(
        tipo_acao="Trabalhista bienal",
        prazo_anos=2,
        base_legal="Art. 7 XXIX CF",
        termo_inicial="Data da extincao do contrato de trabalho",
        notas="Prazo para ajuizamento da reclamacao trabalhista apos extincao do contrato.",
    ),
    PrazoInstituto(
        tipo_acao="Trabalhista quinquenal",
        prazo_anos=5,
        base_legal="Art. 7 XXIX CF",
        termo_inicial="Data do ajuizamento da acao",
        notas="Limita pretensao aos 5 anos anteriores ao ajuizamento.",
    ),
    # === CDC ===
    PrazoInstituto(
        tipo_acao="CDC vicio aparente produto nao duravel",
        prazo_anos=30 / 365,  # 30 dias
        base_legal="Art. 26 I CDC",
        termo_inicial="Data da entrega do produto ou conclusao do servico",
        notas="Decadencia (nao prescricao). Produto/servico nao duravel: 30 dias.",
    ),
    PrazoInstituto(
        tipo_acao="CDC vicio aparente produto duravel",
        prazo_anos=90 / 365,  # 90 dias
        base_legal="Art. 26 II CDC",
        termo_inicial="Data da entrega do produto ou conclusao do servico",
        notas="Decadencia (nao prescricao). Produto/servico duravel: 90 dias.",
    ),
    PrazoInstituto(
        tipo_acao="CDC fato do produto",
        prazo_anos=5,
        base_legal="Art. 27 CDC",
        termo_inicial="Data do conhecimento do dano e de sua autoria",
        notas="Prescricao por fato do produto/servico (acidente de consumo).",
    ),
]


# Lookup map for fast search by tipo_acao (normalized lowercase)
_PRAZO_MAP: dict[str, PrazoInstituto] = {p.tipo_acao.lower(): p for p in PRAZOS_PRESCRICAO}


def buscar_prazo_prescricional(tipo_acao: str) -> PrazoInstituto | None:
    """Look up a prescription period by action type.

    Args:
        tipo_acao: Description of the action type (case-insensitive).

    Returns:
        Matching PrazoInstituto or None if not found.
    """
    normalized = tipo_acao.strip().lower()
    result = _PRAZO_MAP.get(normalized)
    if result is not None:
        return result
    # Partial match fallback
    for key, prazo in _PRAZO_MAP.items():
        if normalized in key or key in normalized:
            return prazo
    return None
