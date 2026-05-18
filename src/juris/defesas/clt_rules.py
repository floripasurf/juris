"""CLT-specific procedural defense rules."""

from __future__ import annotations

from juris.defesas.models import (
    CodigoProcessual,
    InstitutoProcessual,
    PrazoInstituto,
    TipoDefesa,
)


CLT_DEFESAS: list[InstitutoProcessual] = [
    # === Prescricao bienal ===
    InstitutoProcessual(
        nome="Prescricao bienal trabalhista",
        codigo_processual=CodigoProcessual.CLT,
        artigos=["Art. 7 XXIX CF", "Art. 11 CLT"],
        descricao=(
            "Prazo de 2 anos apos a extincao do contrato de trabalho "
            "para ajuizamento de reclamacao trabalhista."
        ),
        tipo=TipoDefesa.PRESCRICAO,
        prazos=[
            PrazoInstituto(
                tipo_acao="Trabalhista bienal",
                prazo_anos=2,
                base_legal="Art. 7 XXIX CF",
                termo_inicial="Data da extincao do contrato de trabalho",
                notas="Sumula 308 TST. Conta-se a partir do dia seguinte ao termino do contrato.",
            ),
        ],
        requisitos=[
            "Contrato de trabalho extinto",
            "Mais de 2 anos entre extincao e ajuizamento",
        ],
        excecoes=[
            "Menor de 18 anos (Art. 440 CLT): prescricao nao corre",
            "Doenca incapacitante devidamente comprovada",
        ],
        jurisprudencia_chave=[
            "Sumula 308 TST",
            "Sumula 268 TST",
        ],
    ),

    # === Prescricao quinquenal ===
    InstitutoProcessual(
        nome="Prescricao quinquenal trabalhista",
        codigo_processual=CodigoProcessual.CLT,
        artigos=["Art. 7 XXIX CF", "Art. 11 CLT"],
        descricao=(
            "Limita a pretensao aos 5 anos anteriores ao ajuizamento "
            "da reclamacao trabalhista."
        ),
        tipo=TipoDefesa.PRESCRICAO,
        prazos=[
            PrazoInstituto(
                tipo_acao="Trabalhista quinquenal",
                prazo_anos=5,
                base_legal="Art. 7 XXIX CF",
                termo_inicial="Data do ajuizamento da acao",
                notas="Limita pretensao retroativamente. Parcelas anteriores a 5 anos estao prescritas.",
            ),
        ],
        requisitos=[
            "Contrato de trabalho vigente ou extinto ha menos de 2 anos",
            "Parcelas reclamadas com mais de 5 anos do ajuizamento",
        ],
        excecoes=[
            "FGTS: prazo de 5 anos (Art. 23 par.5 Lei 8.036/90, STF ARE 709.212)",
        ],
        jurisprudencia_chave=[
            "Sumula 308 TST",
            "STF ARE 709.212 (FGTS)",
        ],
    ),

    # === Decadencia trabalhista ===
    InstitutoProcessual(
        nome="Decadencia trabalhista",
        codigo_processual=CodigoProcessual.CLT,
        artigos=["Art. 853 CLT"],
        descricao=(
            "Prazo decadencial de 30 dias para ajuizamento de inquerito "
            "para apuracao de falta grave de empregado estavel."
        ),
        tipo=TipoDefesa.DECADENCIA,
        prazos=[
            PrazoInstituto(
                tipo_acao="Inquerito para apuracao de falta grave",
                prazo_anos=30 / 365,  # 30 dias
                base_legal="Art. 853 CLT + Sumula 403 STF",
                termo_inicial="Data da suspensao do empregado",
                notas="Empregador deve ajuizar inquerito em 30 dias da suspensao.",
            ),
        ],
        requisitos=[
            "Empregado com estabilidade provisoria",
            "Suspensao para apuracao de falta grave",
            "Decurso de 30 dias sem ajuizamento de inquerito",
        ],
        excecoes=[
            "Empregado sem estabilidade (nao se aplica)",
        ],
        jurisprudencia_chave=[
            "Sumula 403 STF",
            "Sumula 62 TST",
        ],
    ),
]


# Lookup map by TipoDefesa
_CLT_DEFESA_MAP: dict[TipoDefesa, list[InstitutoProcessual]] = {}
for _inst in CLT_DEFESAS:
    _CLT_DEFESA_MAP.setdefault(_inst.tipo, []).append(_inst)


def buscar_instituto_clt(tipo: TipoDefesa) -> list[InstitutoProcessual]:
    """Look up CLT institutes by defense type.

    Args:
        tipo: The defense type to look up.

    Returns:
        List of matching InstitutoProcessual entries.
    """
    return _CLT_DEFESA_MAP.get(tipo, [])
