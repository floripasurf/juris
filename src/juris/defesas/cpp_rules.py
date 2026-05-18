"""CPP (criminal procedure) defense rules."""

from __future__ import annotations

from juris.defesas.models import (
    CodigoProcessual,
    InstitutoProcessual,
    PrazoInstituto,
    TipoDefesa,
)


# Prescription periods by maximum penalty (Art. 109 CP)
PRAZOS_PRESCRICAO_PENAL: list[PrazoInstituto] = [
    PrazoInstituto(
        tipo_acao="Pena maxima superior a 12 anos",
        prazo_anos=20,
        base_legal="Art. 109 I CP",
        termo_inicial="Data do fato (Art. 111 CP)",
        notas="Crimes com pena maxima superior a 12 anos.",
    ),
    PrazoInstituto(
        tipo_acao="Pena maxima superior a 8 e nao excede 12 anos",
        prazo_anos=16,
        base_legal="Art. 109 II CP",
        termo_inicial="Data do fato (Art. 111 CP)",
        notas="Crimes com pena maxima entre 8 e 12 anos.",
    ),
    PrazoInstituto(
        tipo_acao="Pena maxima superior a 4 e nao excede 8 anos",
        prazo_anos=12,
        base_legal="Art. 109 III CP",
        termo_inicial="Data do fato (Art. 111 CP)",
        notas="Crimes com pena maxima entre 4 e 8 anos.",
    ),
    PrazoInstituto(
        tipo_acao="Pena maxima superior a 2 e nao excede 4 anos",
        prazo_anos=8,
        base_legal="Art. 109 IV CP",
        termo_inicial="Data do fato (Art. 111 CP)",
        notas="Crimes com pena maxima entre 2 e 4 anos.",
    ),
    PrazoInstituto(
        tipo_acao="Pena maxima igual ou inferior a 2 anos",
        prazo_anos=4,  # Lei 12.234/2010 alterou para 3 anos o minimo
        base_legal="Art. 109 V CP",
        termo_inicial="Data do fato (Art. 111 CP)",
        notas="Crimes com pena maxima de 1 a 2 anos. Minimo de 3 anos apos Lei 12.234/2010.",
    ),
    PrazoInstituto(
        tipo_acao="Pena maxima inferior a 1 ano",
        prazo_anos=3,
        base_legal="Art. 109 VI CP (Lei 12.234/2010)",
        termo_inicial="Data do fato (Art. 111 CP)",
        notas="Crimes com pena maxima inferior a 1 ano. Prazo minimo de 3 anos.",
    ),
]


CPP_DEFESAS: list[InstitutoProcessual] = [
    # === Prescricao penal ===
    InstitutoProcessual(
        nome="Prescricao penal",
        codigo_processual=CodigoProcessual.CPP,
        artigos=[
            "Art. 109 CP", "Art. 110 CP", "Art. 111 CP",
            "Art. 112 CP", "Art. 117 CP", "Art. 119 CP",
        ],
        descricao=(
            "Extincao da punibilidade pelo decurso do tempo. "
            "Prazos variam conforme a pena maxima cominada (abstrata) "
            "ou a pena aplicada (concreta)."
        ),
        tipo=TipoDefesa.PRESCRICAO,
        prazos=PRAZOS_PRESCRICAO_PENAL,
        requisitos=[
            "Decurso do prazo prescricional sem sentenca condenatoria irrecorrivel",
        ],
        excecoes=[
            "Crimes imprescritiveis (racismo, acao de grupos armados - Art. 5 XLII/XLIV CF)",
            "Causas interruptivas (Art. 117 CP): recebimento da denuncia, pronuncia, etc.",
            "Menor de 21 na data do fato ou maior de 70 na sentenca: prazo reduzido pela metade",
        ],
        jurisprudencia_chave=[
            "Sumula 497 STF",
            "STF HC 82.424/RS (imprescritibilidade do racismo)",
        ],
    ),

    # === Decadencia do direito de queixa ===
    InstitutoProcessual(
        nome="Decadencia do direito de queixa",
        codigo_processual=CodigoProcessual.CPP,
        artigos=["Art. 38 CPP", "Art. 103 CP"],
        descricao=(
            "Perda do direito de oferecer queixa-crime por decurso do prazo "
            "de 6 meses a contar da ciencia da autoria."
        ),
        tipo=TipoDefesa.DECADENCIA,
        prazos=[
            PrazoInstituto(
                tipo_acao="Queixa-crime",
                prazo_anos=0.5,  # 6 meses
                base_legal="Art. 38 CPP c/c Art. 103 CP",
                termo_inicial="Data em que a vitima toma ciencia da autoria do crime",
                notas="Prazo decadencial. Nao admite suspensao ou interrupcao.",
            ),
        ],
        requisitos=[
            "Crime de acao penal privada",
            "Decurso de 6 meses da ciencia da autoria",
        ],
        excecoes=[
            "Crime de acao penal publica (nao se aplica)",
        ],
        jurisprudencia_chave=[
            "Sumula 594 STF",
        ],
    ),
]


def buscar_prazo_prescricao_penal(pena_maxima_anos: float) -> PrazoInstituto | None:
    """Look up criminal prescription period by maximum penalty.

    Args:
        pena_maxima_anos: Maximum penalty in years for the crime.

    Returns:
        Matching PrazoInstituto or None.
    """
    if pena_maxima_anos > 12:
        return PRAZOS_PRESCRICAO_PENAL[0]
    if pena_maxima_anos > 8:
        return PRAZOS_PRESCRICAO_PENAL[1]
    if pena_maxima_anos > 4:
        return PRAZOS_PRESCRICAO_PENAL[2]
    if pena_maxima_anos > 2:
        return PRAZOS_PRESCRICAO_PENAL[3]
    if pena_maxima_anos >= 1:
        return PRAZOS_PRESCRICAO_PENAL[4]
    if pena_maxima_anos > 0:
        return PRAZOS_PRESCRICAO_PENAL[5]
    return None
