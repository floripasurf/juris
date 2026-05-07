"""Fixture factories for MNI consultarProcesso responses.

These simulate the zeep-parsed SOAP response objects using SimpleNamespace,
matching the MNI 2.2.2 XSD structure. Use these for unit tests without
needing a live tribunal connection.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace


def make_movimento(
    data_hora: datetime,
    codigo_nacional: int,
    descricao: str,
    complemento: str = "",
    id_movimento: str = "",
) -> SimpleNamespace:
    """Create a single MNI movimento object."""
    return SimpleNamespace(
        dataHora=data_hora,
        movimentoNacional=SimpleNamespace(
            codigoNacional=codigo_nacional,
            descricao=descricao,
        ),
        movimentoLocal=None,
        complementoNacional=complemento,
        identificadorMovimento=id_movimento,
    )


def make_documento(
    id_documento: str = "DOC001",
    tipo: str = "Petição Inicial",
    descricao: str = "Petição inicial do processo",
    data_hora: datetime | None = None,
    mime_type: str = "application/pdf",
    conteudo: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        idDocumento=id_documento,
        tipoDocumento=tipo,
        descricao=descricao,
        dataHora=data_hora or datetime(2017, 10, 5, 14, 30),
        mimetype=mime_type,
        conteudo=conteudo,
        hash=None,
    )


def make_parte(
    nome: str,
    polo: str = "AT",
    documento: str | None = None,
    advogados: list[dict[str, str]] | None = None,
) -> SimpleNamespace:
    advs = [SimpleNamespace(nome=a["nome"]) for a in (advogados or [])]
    return SimpleNamespace(
        nome=nome,
        numeroDocumentoPrincipal=documento,
        advogado=advs,
    )


def make_polo(polo_tipo: str, partes: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(polo=polo_tipo, parte=partes)


def make_consulta_response_5082351() -> SimpleNamespace:
    """Fixture for processo 5082351-40.2017.8.13.0024 (user's real case in TJMG).

    Simulated data based on typical TJMG civil case structure.
    """
    dados = SimpleNamespace(
        numero="5082351-40.2017.8.13.0024",
        classeProcessual="Procedimento Comum Cível",
        assuntoLocal=None,
        assunto="Indenização por Dano Moral",
        valorCausa=50000.00,
        orgaoJulgador="5ª Vara Cível da Comarca de Belo Horizonte",
        dataAjuizamento=datetime(2017, 10, 5),
        polo=[
            make_polo("AT", [
                make_parte(
                    "JOAO RAPHAEL MARTINS DE FARIA LAGES",
                    documento="07671039632",
                    advogados=[{"nome": "JOAO RAPHAEL MARTINS DE FARIA LAGES"}],
                ),
            ]),
            make_polo("RE", [
                make_parte("EMPRESA REQUERIDA LTDA", documento="12345678000100"),
            ]),
        ],
    )

    movimentos = [
        make_movimento(
            datetime(2017, 10, 5, 10, 0),
            26,
            "Distribuído por sorteio",
            id_movimento="MOV001",
        ),
        make_movimento(
            datetime(2017, 10, 10, 9, 30),
            12,
            "Citação",
            complemento="Citação por AR",
            id_movimento="MOV002",
        ),
        make_movimento(
            datetime(2017, 11, 15, 14, 0),
            85,
            "Juntada de Petição",
            complemento="Contestação",
            id_movimento="MOV003",
        ),
        make_movimento(
            datetime(2018, 3, 20, 11, 0),
            970,
            "Intimação Eletrônica",
            complemento="Prazo de 15 dias para réplica",
            id_movimento="MOV004",
        ),
        make_movimento(
            datetime(2018, 6, 15, 16, 0),
            60,
            "Despacho",
            complemento="Designada audiência de conciliação",
            id_movimento="MOV005",
        ),
        make_movimento(
            datetime(2018, 9, 10, 10, 30),
            132,
            "Sentença",
            complemento="Julgado procedente em parte",
            id_movimento="MOV006",
        ),
    ]

    documentos = [
        make_documento("DOC001", "Petição Inicial", "Petição inicial", datetime(2017, 10, 5, 10, 0)),
        make_documento("DOC002", "Contestação", "Contestação do réu", datetime(2017, 11, 15, 14, 0)),
        make_documento("DOC003", "Sentença", "Sentença do juiz", datetime(2018, 9, 10, 10, 30)),
    ]

    processo = SimpleNamespace(
        dadosBasicos=dados,
        movimento=movimentos,
        documento=documentos,
    )

    return SimpleNamespace(processo=processo, sucesso=True, mensagem="")


def make_consulta_response_5080938() -> SimpleNamespace:
    """Fixture for processo 5080938-89.2017.8.13.0024 (user's second case)."""
    dados = SimpleNamespace(
        numero="5080938-89.2017.8.13.0024",
        classeProcessual="Procedimento Comum Cível",
        assuntoLocal=None,
        assunto="Obrigação de Fazer",
        valorCausa=30000.00,
        orgaoJulgador="3ª Vara Cível da Comarca de Belo Horizonte",
        dataAjuizamento=datetime(2017, 9, 28),
        polo=[
            make_polo("AT", [
                make_parte(
                    "JOAO RAPHAEL MARTINS DE FARIA LAGES",
                    documento="07671039632",
                    advogados=[{"nome": "JOAO RAPHAEL MARTINS DE FARIA LAGES"}],
                ),
            ]),
            make_polo("RE", [
                make_parte("MUNICIPIO DE BELO HORIZONTE", documento="18715383000140"),
            ]),
        ],
    )

    movimentos = [
        make_movimento(datetime(2017, 9, 28, 8, 0), 26, "Distribuído por sorteio", id_movimento="MOV101"),
        make_movimento(datetime(2017, 10, 5, 9, 0), 12, "Citação", id_movimento="MOV102"),
        make_movimento(datetime(2017, 12, 1, 14, 30), 85, "Juntada de Petição", complemento="Contestação", id_movimento="MOV103"),
        make_movimento(datetime(2018, 4, 10, 11, 0), 60, "Despacho", complemento="Saneador", id_movimento="MOV104"),
        make_movimento(datetime(2019, 2, 20, 15, 0), 132, "Sentença", complemento="Julgado improcedente", id_movimento="MOV105"),
        make_movimento(datetime(2019, 3, 5, 10, 0), 60, "Apelação", id_movimento="MOV106"),
    ]

    documentos = [
        make_documento("DOC101", "Petição Inicial", "Petição inicial", datetime(2017, 9, 28, 8, 0)),
        make_documento("DOC102", "Sentença", "Sentença", datetime(2019, 2, 20, 15, 0)),
    ]

    processo = SimpleNamespace(
        dadosBasicos=dados,
        movimento=movimentos,
        documento=documentos,
    )

    return SimpleNamespace(processo=processo, sucesso=True, mensagem="")


def make_consulta_response_empty() -> SimpleNamespace:
    """Fixture for an empty/not-found response."""
    return SimpleNamespace(
        processo=None,
        sucesso=False,
        mensagem="Processo não encontrado",
    )
