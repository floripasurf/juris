"""Tests for peticionamento operation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from juris.mni.operations.peticionamento import entregar_manifestacao


class TestEntregarManifestacao:
    def _mock_client(self, sucesso: bool, protocolo: str = "", mensagem: str = "") -> MagicMock:
        client = MagicMock()
        client.service.entregarManifestacaoProcessual.return_value = SimpleNamespace(
            sucesso=sucesso,
            mensagem=mensagem,
            protocoloRecebimento=protocolo,
            dataOperacao=None,
        )
        return client

    def test_successful_filing(self) -> None:
        client = self._mock_client(True, protocolo="PROT-2026-12345")
        pdf = b"%PDF-1.4 signed content here"

        receipt = entregar_manifestacao(
            client=client,
            id_manifestante="07671039632",
            senha_manifestante="07671039632",
            numero_processo="5082351-40.2017.8.13.0024",
            signed_pdf_bytes=pdf,
            tipo_documento="manifestacao",
        )

        assert receipt.sucesso is True
        assert receipt.protocolo == "PROT-2026-12345"
        assert receipt.pdf_hash is not None
        assert len(receipt.pdf_hash) == 64  # sha256 hex

    def test_failed_filing(self) -> None:
        client = self._mock_client(False, mensagem="Prazo expirado")

        receipt = entregar_manifestacao(
            client=client,
            id_manifestante="07671039632",
            senha_manifestante="07671039632",
            numero_processo="5082351-40.2017.8.13.0024",
            signed_pdf_bytes=b"pdf",
            tipo_documento="manifestacao",
        )

        assert receipt.sucesso is False
        assert "expirado" in receipt.mensagem.lower()

    def test_pdf_hash_is_deterministic(self) -> None:
        client = self._mock_client(True, protocolo="P1")
        pdf = b"test pdf content"

        r1 = entregar_manifestacao(client, "cpf", "senha", "0000000-00.0000.0.00.0000", pdf, "tipo")
        r2 = entregar_manifestacao(client, "cpf", "senha", "0000000-00.0000.0.00.0000", pdf, "tipo")

        assert r1.pdf_hash == r2.pdf_hash

    def test_soap_call_receives_base64(self) -> None:
        client = self._mock_client(True, protocolo="P1")
        pdf = b"test"

        entregar_manifestacao(client, "cpf", "senha", "0000000-00.0000.0.00.0000", pdf, "peticao")

        call_args = client.service.entregarManifestacaoProcessual.call_args
        doc = call_args.kwargs.get("documento") or call_args[1].get("documento")
        assert doc is not None
        assert doc[0]["mimetype"] == "application/pdf"
