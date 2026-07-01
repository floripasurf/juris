"""CPC procedural defense rules (institutos processuais)."""

from __future__ import annotations

from juris.defesas.models import (
    CodigoProcessual,
    InstitutoProcessual,
    PrazoInstituto,
    TipoDefesa,
)

CPC_DEFESAS: list[InstitutoProcessual] = [
    # === Prescricao intercorrente ===
    InstitutoProcessual(
        nome="Prescricao intercorrente",
        codigo_processual=CodigoProcessual.CPC,
        artigos=["Art. 921 par.4 CPC", "Art. 921 par.5 CPC"],
        descricao=(
            "Prescricao que ocorre durante a fase de execucao, "
            "apos suspensao do processo por 1 ano sem localizacao de bens."
        ),
        tipo=TipoDefesa.PRESCRICAO_INTERCORRENTE,
        prazos=[
            PrazoInstituto(
                tipo_acao="Prescricao intercorrente",
                prazo_anos=0,  # same as original action
                base_legal="Art. 921 par.4 CPC + Sumula 150 STJ",
                termo_inicial="Apos 1 ano de suspensao do processo (Art. 921 par.1)",
                notas="Prazo igual ao da acao originaria. Sumula 150 STJ.",
            ),
        ],
        requisitos=[
            "Processo em fase de execucao",
            "Suspensao por 1 ano sem localizacao de bens",
            "Intimacao do exequente sobre a suspensao",
            "Decurso do prazo prescricional apos a suspensao",
        ],
        excecoes=[
            "Falta de intimacao do exequente",
            "Bens localizados durante o prazo",
            "Causas suspensivas ou interruptivas",
        ],
        jurisprudencia_chave=[
            "Sumula 150 STJ",
            "IAC no REsp 1604412/SC",
        ],
    ),
    # === Preclusao temporal ===
    InstitutoProcessual(
        nome="Preclusao temporal",
        codigo_processual=CodigoProcessual.CPC,
        artigos=["Art. 223 CPC"],
        descricao="Perda da faculdade processual por decurso do prazo.",
        tipo=TipoDefesa.PRECLUSAO_TEMPORAL,
        requisitos=[
            "Prazo legal ou judicial fixado",
            "Decurso do prazo sem manifestacao",
        ],
        excecoes=[
            "Justa causa (Art. 223 par.1 CPC)",
            "Prazo nao peremptorio",
        ],
    ),
    # === Preclusao consumativa ===
    InstitutoProcessual(
        nome="Preclusao consumativa",
        codigo_processual=CodigoProcessual.CPC,
        artigos=["Art. 507 CPC"],
        descricao=(
            "Perda da faculdade processual por ja ter sido exercida. Uma vez praticado o ato, nao pode ser repetido."
        ),
        tipo=TipoDefesa.PRECLUSAO_CONSUMATIVA,
        requisitos=[
            "Ato processual ja praticado pela parte",
            "Tentativa de repetir o mesmo ato",
        ],
        excecoes=[
            "Emenda da inicial por determinacao judicial",
        ],
    ),
    # === Preclusao logica ===
    InstitutoProcessual(
        nome="Preclusao logica",
        codigo_processual=CodigoProcessual.CPC,
        artigos=["Art. 1.000 CPC"],
        descricao=(
            "Perda da faculdade processual por pratica de ato incompativel. Ex: aceitar a sentenca e depois recorrer."
        ),
        tipo=TipoDefesa.PRECLUSAO_LOGICA,
        requisitos=[
            "Pratica de ato incompativel com o direito que se pretende exercer",
        ],
        excecoes=[
            "Atos praticados sob reserva",
        ],
        jurisprudencia_chave=[
            "STJ REsp 1.223.412/PR",
        ],
    ),
    # === Coisa julgada ===
    InstitutoProcessual(
        nome="Coisa julgada",
        codigo_processual=CodigoProcessual.CPC,
        artigos=["Art. 502 CPC", "Art. 503 CPC", "Art. 504 CPC", "Art. 508 CPC"],
        descricao=("Autoridade que torna imutavel e indiscutivel a decisao de merito nao mais sujeita a recurso."),
        tipo=TipoDefesa.COISA_JULGADA,
        requisitos=[
            "Decisao de merito transitada em julgado",
            "Identidade de partes",
            "Identidade de pedido",
            "Identidade de causa de pedir",
        ],
        excecoes=[
            "Acao rescisoria (Art. 966 CPC, prazo de 2 anos)",
            "Revisao criminal",
            "Coisa julgada inconstitucional",
        ],
        jurisprudencia_chave=[
            "STF RE 363.889",
            "STJ REsp 1.521.914/PE",
        ],
    ),
    # === Litispendencia ===
    InstitutoProcessual(
        nome="Litispendencia",
        codigo_processual=CodigoProcessual.CPC,
        artigos=["Art. 337 par.1 CPC", "Art. 337 par.2 CPC", "Art. 337 par.3 CPC"],
        descricao=("Existencia de acao identica em tramitacao, com mesmas partes, causa de pedir e pedido."),
        tipo=TipoDefesa.LITISPENDENCIA,
        requisitos=[
            "Acao anterior em tramitacao",
            "Identidade de partes",
            "Identidade de pedido",
            "Identidade de causa de pedir",
        ],
        excecoes=[
            "Conexao (mesma causa de pedir ou pedido, mas nao ambos)",
        ],
    ),
    # === Incompetencia absoluta ===
    InstitutoProcessual(
        nome="Incompetencia absoluta",
        codigo_processual=CodigoProcessual.CPC,
        artigos=["Art. 64 CPC"],
        descricao=("Incompetencia em razao da materia, da pessoa ou funcional. Pode ser alegada a qualquer tempo."),
        tipo=TipoDefesa.INCOMPETENCIA,
        requisitos=[
            "Materia alheia a competencia do juizo",
            "Razao da pessoa ou funcional violada",
        ],
        excecoes=[],
        jurisprudencia_chave=[
            "Sumula 33 STJ",
        ],
    ),
    # === Incompetencia relativa ===
    InstitutoProcessual(
        nome="Incompetencia relativa",
        codigo_processual=CodigoProcessual.CPC,
        artigos=["Art. 65 CPC"],
        descricao=(
            "Incompetencia territorial ou em razao do valor. "
            "Deve ser alegada em preliminar de contestacao, sob pena de prorrogacao."
        ),
        tipo=TipoDefesa.INCOMPETENCIA,
        requisitos=[
            "Competencia territorial ou por valor inadequada",
            "Alegacao em preliminar de contestacao",
        ],
        excecoes=[
            "Prorrogacao por nao-alegacao em tempo habil",
        ],
    ),
    # === Inepcia da inicial ===
    InstitutoProcessual(
        nome="Inepcia da inicial",
        codigo_processual=CodigoProcessual.CPC,
        artigos=["Art. 330 CPC"],
        descricao="Peticao inicial que nao preenche os requisitos legais.",
        tipo=TipoDefesa.INEPCIA,
        requisitos=[
            "Falta de pedido ou causa de pedir",
            "Pedido indeterminado (fora das hipoteses legais)",
            "Incompatibilidade logica entre pedidos",
            "Narrativa sem conclusao logica",
        ],
        excecoes=[
            "Emenda da inicial deferida pelo juiz (Art. 321 CPC)",
        ],
    ),
    # === Ilegitimidade ===
    InstitutoProcessual(
        nome="Ilegitimidade de parte",
        codigo_processual=CodigoProcessual.CPC,
        artigos=["Art. 17 CPC"],
        descricao=(
            "Ausencia de legitimidade ativa ou passiva. Parte nao e titular do direito ou da obrigacao em discussao."
        ),
        tipo=TipoDefesa.ILEGITIMIDADE,
        requisitos=[
            "Parte nao titula o direito discutido (ativa)",
            "Parte nao e obrigada pela relacao juridica (passiva)",
        ],
        excecoes=[
            "Legitimidade extraordinaria (substituicao processual)",
        ],
    ),
    # === Falta de interesse ===
    InstitutoProcessual(
        nome="Falta de interesse de agir",
        codigo_processual=CodigoProcessual.CPC,
        artigos=["Art. 17 CPC"],
        descricao=(
            "Ausencia de necessidade, utilidade ou adequacao da via eleita. "
            "A parte nao precisa do Judiciario para obter o que pretende."
        ),
        tipo=TipoDefesa.FALTA_INTERESSE,
        requisitos=[
            "Ausencia de necessidade de tutela jurisdicional",
            "Via processual inadequada",
            "Utilidade do provimento nao demonstrada",
        ],
        excecoes=[
            "Direito nao alcancavel por via administrativa",
        ],
    ),
]


# Lookup map by TipoDefesa
_CPC_DEFESA_MAP: dict[TipoDefesa, list[InstitutoProcessual]] = {}
for _inst in CPC_DEFESAS:
    _CPC_DEFESA_MAP.setdefault(_inst.tipo, []).append(_inst)


def buscar_instituto_cpc(tipo: TipoDefesa) -> list[InstitutoProcessual]:
    """Look up CPC institutes by defense type.

    Args:
        tipo: The defense type to look up.

    Returns:
        List of matching InstitutoProcessual entries.
    """
    return _CPC_DEFESA_MAP.get(tipo, [])
