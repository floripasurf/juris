"""Tests for document processing — storage and text extraction."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import pytest

from juris.core.storage import LocalFileStorage
from juris.mni.parsers.documentos import (
    ProcessedDocument,
    _mime_to_ext,
    store_document,
)


class TestMimeToExt:
    def test_pdf(self) -> None:
        assert _mime_to_ext("application/pdf") == "pdf"

    def test_docx(self) -> None:
        assert _mime_to_ext("application/vnd.openxmlformats-officedocument.wordprocessingml.document") == "docx"

    def test_unknown(self) -> None:
        assert _mime_to_ext("application/octet-stream") == "bin"


class TestStoreDocument:
    def test_store_and_verify(self, tmp_path: Path) -> None:
        storage = LocalFileStorage(tmp_path / "docs")
        content = b"fake pdf content for testing"
        b64 = base64.b64encode(content).decode()

        result = asyncio.run(
            store_document(
                storage=storage,
                processo_cnj="1234567-89.2026.8.13.0001",
                id_documento="doc_001",
                conteudo_base64=b64,
                mime_type="application/pdf",
            )
        )

        assert isinstance(result, ProcessedDocument)
        assert result.id_documento == "doc_001"
        assert result.size_bytes == len(content)
        assert result.sha256  # Non-empty hash
        assert "doc_001.pdf" in result.storage_key

        # Verify the file was actually stored
        stored = asyncio.run(
            storage.get(result.storage_key)
        )
        assert stored == content

    def test_storage_key_structure(self, tmp_path: Path) -> None:
        storage = LocalFileStorage(tmp_path / "docs")
        b64 = base64.b64encode(b"test").decode()

        result = asyncio.run(
            store_document(
                storage=storage,
                processo_cnj="5082351-40.2017.8.13.0024",
                id_documento="abc123",
                conteudo_base64=b64,
            )
        )

        assert result.storage_key == "documentos/50823514020178130024/abc123.pdf"


class TestOvernightSync:
    """Test the overnight sync orchestration."""

    def test_datajud_sync(self) -> None:
        """Test that DataJud sync returns a DiffResult."""
        from juris.mni.operations.differential import DiffResult, diff_processo
        from juris.mni.parsers.processo import Movimento, ProcessoDomain

        # Simulate a DataJud-parsed processo
        processo = ProcessoDomain(
            numero_cnj="5082351-40.2017.8.13.0024",
            tribunal="tjmg",
            classe="Procedimento Comum Cível",
            movimentos=[
                Movimento(
                    data_hora=__import__("datetime").datetime(2017, 6, 19, 13, 20),
                    tipo="nacional",
                    codigo_nacional=26,
                    descricao="Distribuição",
                ),
                Movimento(
                    data_hora=__import__("datetime").datetime(2018, 9, 17, 11, 23),
                    tipo="nacional",
                    codigo_nacional=466,
                    descricao="Homologação de Transação",
                ),
            ],
        )

        # First sync: all movements are new
        result = diff_processo(processo, last_sync_at=None)
        assert result.had_changes
        assert len(result.new_movimentos) == 2

        # Second sync with same data: no new movements
        from datetime import datetime, timezone
        result2 = diff_processo(
            processo,
            last_sync_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            known_movimento_keys={
                (m.data_hora, m.codigo_nacional, m.id_movimento)
                for m in processo.movimentos
            },
        )
        assert not result2.had_changes
