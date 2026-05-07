"""Test consultarAvisosPendentes against working tribunals.

Some tribunals allow avisos query with looser auth.
Also tests if your real CPF works on any tribunal.

Usage:
    uv run python scripts/test_mni_avisos.py [--cpf CPF] [--senha SENHA]
"""

from __future__ import annotations

import sys

from zeep import Client, Settings
from zeep.transports import Transport
from requests import Session

WORKING = {
    "tjes": "https://pje.tjes.jus.br/pje/intercomunicacao?wsdl",
    "tjmt": "https://pje.tjmt.jus.br/pje/intercomunicacao?wsdl",
    "tjpe": "https://pje.tjpe.jus.br/pje/intercomunicacao?wsdl",
    "trf5": "https://pje.trf5.jus.br/pje/intercomunicacao?wsdl",
}

CPF = "07671039632"


def main() -> None:
    senha = CPF  # Default: CPF as senha (common for cert-based auth)
    if "--senha" in sys.argv:
        idx = sys.argv.index("--senha")
        senha = sys.argv[idx + 1]

    print(f"Testing consultarAvisosPendentes with CPF: {CPF}")
    print(f"Senha: {'[provided]' if senha != CPF else '[CPF as senha]'}\n")

    settings = Settings(strict=False, xml_huge_tree=True)

    for tid, wsdl in WORKING.items():
        print(f"\n{tid.upper()} — {wsdl}")
        try:
            transport = Transport(session=Session(), timeout=30, operation_timeout=60)
            client = Client(wsdl=wsdl, transport=transport, settings=settings)

            # Test consultarAvisosPendentes
            try:
                response = client.service.consultarAvisosPendentes(
                    idConsultante=CPF,
                    senhaConsultante=senha,
                )
                sucesso = getattr(response, "sucesso", None)
                mensagem = getattr(response, "mensagem", "")
                print(f"  avisosPendentes: success={sucesso} msg={mensagem[:200]}")

                avisos = getattr(response, "aviso", None) or []
                if avisos:
                    print(f"  Found {len(avisos)} pending avisos!")
                    for a in avisos[:3]:
                        print(f"    - {getattr(a, 'idAviso', '?')}: {getattr(a, 'dataDisponibilizacao', '?')}")
            except Exception as e:
                print(f"  avisosPendentes error: {type(e).__name__}: {str(e)[:200]}")

            # Also test consultarProcesso with the real CPF
            test_proc = {
                "tjes": "0001000-00.2024.8.08.0024",
                "tjmt": "0001000-00.2024.8.11.0001",
                "tjpe": "0001000-00.2024.8.17.0001",
                "trf5": "0001000-00.2024.4.05.8300",
            }
            try:
                response = client.service.consultarProcesso(
                    idConsultante=CPF,
                    senhaConsultante=senha,
                    numeroProcesso=test_proc[tid],
                    movimentos=True,
                    incluirCabecalho=True,
                    incluirDocumentos=False,
                )
                sucesso = getattr(response, "sucesso", None)
                mensagem = getattr(response, "mensagem", "")
                print(f"  consultarProcesso: success={sucesso} msg={mensagem[:200]}")

                if sucesso and getattr(response, "processo", None):
                    print(f"  >>> PROCESS DATA RETURNED! Full pipeline possible. <<<")
            except Exception as e:
                print(f"  consultarProcesso error: {type(e).__name__}: {str(e)[:200]}")

        except Exception as e:
            print(f"  Client error: {e}")


if __name__ == "__main__":
    main()
