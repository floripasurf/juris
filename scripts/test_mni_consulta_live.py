"""Test consultarProcesso against working MNI endpoints with a real public process.

Finds a public process number for each working tribunal and attempts to query it.
This validates the full pipeline: zeep → SOAP → parse → domain object.

Usage:
    uv run python scripts/test_mni_consulta_live.py
"""

from __future__ import annotations

from zeep import Client, Settings
from zeep.transports import Transport
from requests import Session


# Working endpoints confirmed by probe (no mTLS required)
WORKING_TRIBUNALS = {
    "tjes": {
        "wsdl": "https://pje.tjes.jus.br/pje/intercomunicacao?wsdl",
        # TJES process format: NNNNNNN-DD.AAAA.8.08.OOOO (justiça 8, tribunal 08)
        "test_processes": [
            "0001000-00.2024.8.08.0024",
            "0000100-00.2023.8.08.0024",
            "0005000-00.2023.8.08.0035",
        ],
    },
    "tjmt": {
        "wsdl": "https://pje.tjmt.jus.br/pje/intercomunicacao?wsdl",
        # TJMT: justiça 8, tribunal 11
        "test_processes": [
            "0001000-00.2024.8.11.0001",
            "0000100-00.2023.8.11.0001",
        ],
    },
    "tjpe": {
        "wsdl": "https://pje.tjpe.jus.br/pje/intercomunicacao?wsdl",
        # TJPE: justiça 8, tribunal 17
        "test_processes": [
            "0001000-00.2024.8.17.0001",
            "0000100-00.2023.8.17.2001",
        ],
    },
    "trf5": {
        "wsdl": "https://pje.trf5.jus.br/pje/intercomunicacao?wsdl",
        # TRF5: justiça 4, tribunal 05
        "test_processes": [
            "0001000-00.2024.4.05.8300",
            "0000100-00.2023.4.05.8300",
        ],
    },
}

# Dummy credentials — we just want to see if the API responds with process data
# or a meaningful error (both prove the pipeline works)
CPF = "00000000000"


def test_tribunal(tid: str, config: dict) -> None:
    """Test consultarProcesso against a single tribunal."""
    print(f"\n{'='*60}")
    print(f"  {tid.upper()} — {config['wsdl']}")
    print(f"{'='*60}")

    try:
        settings = Settings(strict=False, xml_huge_tree=True)
        transport = Transport(session=Session(), timeout=30, operation_timeout=60)
        client = Client(wsdl=config["wsdl"], transport=transport, settings=settings)
        ops = list(client.service._operations.keys())
        print(f"  Operations: {', '.join(ops)}")
    except Exception as e:
        print(f"  Client creation failed: {e}")
        return

    for proc_num in config["test_processes"]:
        print(f"\n  Testing: {proc_num}")
        try:
            response = client.service.consultarProcesso(
                idConsultante=CPF,
                senhaConsultante=CPF,
                numeroProcesso=proc_num,
                movimentos=True,
                incluirCabecalho=True,
                incluirDocumentos=False,
            )

            sucesso = getattr(response, "sucesso", None)
            mensagem = getattr(response, "mensagem", "")
            print(f"    Success: {sucesso}")
            print(f"    Message: {mensagem[:200]}")

            processo = getattr(response, "processo", None)
            if processo:
                dados = getattr(processo, "dadosBasicos", None)
                if dados:
                    print(f"    Numero: {getattr(dados, 'numero', 'N/A')}")
                    print(f"    Classe: {getattr(dados, 'classeProcessual', 'N/A')}")
                    orgao = getattr(dados, "orgaoJulgador", None)
                    if orgao:
                        print(f"    Orgao: {getattr(orgao, 'nomeOrgao', orgao)}")

                movs = getattr(processo, "movimento", None) or []
                print(f"    Movimentos: {len(movs)}")

                if movs:
                    # Parse with our parser
                    from juris.mni.parsers.processo import parse_processo
                    domain = parse_processo(response, tribunal_id=tid)
                    print(f"    [PARSED] numero_cnj={domain.numero_cnj}")
                    print(f"    [PARSED] classe={domain.classe}")
                    print(f"    [PARSED] movimentos={len(domain.movimentos)}")
                    print(f"    [PARSED] partes={len(domain.partes)}")
                    if domain.ultimo_movimento:
                        um = domain.ultimo_movimento
                        print(f"    [PARSED] ultimo_mov={um.data_hora} code={um.codigo_nacional} {um.descricao}")
                    print(f"    >>> FULL PIPELINE VALIDATED <<<")
                    return  # Success — no need to try more processes

        except Exception as e:
            err = str(e)
            if "Fault" in type(e).__name__:
                print(f"    SOAP Fault: {err[:200]}")
            else:
                print(f"    Error: {type(e).__name__}: {err[:200]}")


def main() -> None:
    print("MNI consultarProcesso — Live Pipeline Test")
    print("Testing against tribunals with publicly accessible WSDLs")

    for tid, config in WORKING_TRIBUNALS.items():
        test_tribunal(tid, config)

    print("\n\nDone.")


if __name__ == "__main__":
    main()
