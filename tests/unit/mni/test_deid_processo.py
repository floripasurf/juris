"""De-identify a ProcessoDomain at the split-trust boundary (agent → cloud).

The agent reads MNI locally, then returns the processo to the (Phase-2 SaaS) cloud.
Party names and CPFs must not cross raw: they are redacted to reversible placeholders,
with the re-identification map kept LOCAL to the agent.
"""

from __future__ import annotations

from juris.core.deid import reidentify
from juris.mni.deid_processo import deidentify_processo
from juris.mni.parsers.processo import Movimento, Parte, ProcessoDomain


def _processo() -> ProcessoDomain:
    return ProcessoDomain(
        numero_cnj="5082351-40.2017.8.13.0024",
        partes=[
            Parte(
                nome="João da Silva",
                tipo="autor",
                documento="123.456.789-09",
                advogados=["Maria Souza"],
            ),
            Parte(nome="Empresa XPTO Ltda", tipo="reu", documento="12.345.678/0001-90"),
        ],
        movimentos=[
            Movimento(
                data_hora=None,
                tipo="movimentoNacional",
                descricao="Intimação de João da Silva para manifestação",
                complemento="patrono Maria Souza",
            ),
        ],
    )


def test_party_names_and_documents_redacted() -> None:
    deid, _mapping = deidentify_processo(_processo())
    assert "João da Silva" not in deid.partes[0].nome
    assert "123.456.789-09" not in (deid.partes[0].documento or "")
    assert "12.345.678/0001-90" not in (deid.partes[1].documento or "")
    assert "Maria Souza" not in deid.partes[0].advogados[0]
    # movement free-text is scrubbed of the known party/lawyer names too
    assert "João da Silva" not in (deid.movimentos[0].descricao or "")
    assert "Maria Souza" not in (deid.movimentos[0].complemento or "")


def test_same_name_gets_same_placeholder_across_fields() -> None:
    deid, _mapping = deidentify_processo(_processo())
    # "João da Silva" appears in parte.nome AND movimento.descricao → ONE stable placeholder
    placeholder = deid.partes[0].nome
    assert placeholder.startswith("[") and placeholder.endswith("]")
    assert placeholder in (deid.movimentos[0].descricao or "")


def test_reidentify_restores_the_originals() -> None:
    deid, mapping = deidentify_processo(_processo())
    assert reidentify(deid.partes[0].nome, mapping) == "João da Silva"
    assert (
        reidentify(deid.movimentos[0].descricao or "", mapping)
        == "Intimação de João da Silva para manifestação"
    )
    assert reidentify(deid.partes[0].documento or "", mapping) == "123.456.789-09"


def test_numero_cnj_preserved_for_routing() -> None:
    # The case number is the routing key the cloud needs — it is not personal PII
    # of a party, so it stays intact (still a placeholder-free CNJ for correlation).
    deid, _mapping = deidentify_processo(_processo())
    assert deid.numero_cnj == "5082351-40.2017.8.13.0024"


def test_bare_digit_cpf_is_redacted() -> None:
    # Adversarial (agent A): MNI returns unformatted documents; the dotted-CPF regex
    # misses "12345678909", so it must be redacted as a KNOWN document value instead.
    from juris.mni.parsers.processo import Parte

    processo = ProcessoDomain(
        numero_cnj="5082351-40.2017.8.13.0024",
        partes=[Parte(nome="João da Silva", tipo="autor", documento="12345678909")],
        movimentos=[
            Movimento(data_hora=None, tipo="movimentoNacional", descricao="réu doc 12345678909 intimado")
        ],
    )
    deid, mapping = deidentify_processo(processo)

    assert "12345678909" not in (deid.partes[0].documento or "")  # bare CPF gone from the field
    assert "12345678909" not in (deid.movimentos[0].descricao or "")  # and from free text
    assert reidentify(deid.partes[0].documento or "", mapping) == "12345678909"  # reversible
