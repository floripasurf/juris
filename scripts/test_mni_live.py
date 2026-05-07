"""Test a live MNI consultarProcesso call against a working tribunal.

Usage:
    uv run python scripts/test_mni_live.py
"""

from __future__ import annotations

import sys

from zeep import Client, Settings
from zeep.transports import Transport
from requests import Session


# Working endpoints confirmed by probe
ENDPOINTS = {
    "tjes": "https://pje.tjes.jus.br/pje/intercomunicacao?wsdl",
    "tjmt": "https://pje.tjmt.jus.br/pje/intercomunicacao?wsdl",
    "tjpa": "https://pje.tjpa.jus.br/pje/intercomunicacao?wsdl",
    "tjpe": "https://pje.tjpe.jus.br/pje/intercomunicacao?wsdl",
    "trf5": "https://pje.trf5.jus.br/pje/intercomunicacao?wsdl",
}

# Use a dummy CPF for testing (the API should return meaningful error if auth fails)
CPF = "07671039632"


def test_consulta(tribunal_id: str, wsdl_url: str) -> None:
    """Test consultarProcesso against a tribunal."""
    print(f"\n{'='*60}")
    print(f"Testing: {tribunal_id.upper()} — {wsdl_url}")
    print(f"{'='*60}")

    try:
        settings = Settings(strict=False, xml_huge_tree=True)
        transport = Transport(
            session=Session(),
            timeout=30,
            operation_timeout=60,
        )
        client = Client(wsdl=wsdl_url, transport=transport, settings=settings)

        # List available operations
        ops = list(client.service._operations.keys())
        print(f"  Operations: {', '.join(ops)}")

        # Try consultarProcesso with a plausible number for this tribunal
        # Using a generic format — the point is to see if the API responds
        # (even with "processo não encontrado" is a success — means the API works)
        try:
            response = client.service.consultarProcesso(
                idConsultante=CPF,
                senhaConsultante=CPF,
                numeroProcesso="0000001-00.2024.8.08.0024",  # Dummy TJES number
                movimentos=True,
                incluirCabecalho=True,
                incluirDocumentos=False,
            )
            print(f"  Response type: {type(response).__name__}")
            print(f"  Success: {getattr(response, 'sucesso', 'N/A')}")
            print(f"  Message: {getattr(response, 'mensagem', 'N/A')}")

            if hasattr(response, "processo") and response.processo:
                print(f"  Found processo!")
                dados = getattr(response.processo, "dadosBasicos", None)
                if dados:
                    print(f"    Numero: {getattr(dados, 'numero', 'N/A')}")
                    print(f"    Classe: {getattr(dados, 'classeProcessual', 'N/A')}")
        except Exception as e:
            error_msg = str(e)
            # SOAP faults are expected — they prove the API is working
            if "Fault" in type(e).__name__ or "fault" in error_msg.lower():
                print(f"  SOAP Fault (API is working!): {error_msg[:200]}")
            else:
                print(f"  Error: {type(e).__name__}: {error_msg[:200]}")

    except Exception as e:
        print(f"  Client creation error: {type(e).__name__}: {str(e)[:200]}")


def main() -> None:
    print("MNI Live Test — consultarProcesso")
    print(f"CPF: {CPF}")

    for tid, url in ENDPOINTS.items():
        test_consulta(tid, url)

    print("\nDone.")


if __name__ == "__main__":
    main()
