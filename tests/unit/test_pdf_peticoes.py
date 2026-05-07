"""Tests for PDF petition ingestion pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from juris.llm.base import LLMResponse
from juris.repertory.ingestion.pdf_peticoes import (
    extract_text_from_pdf,
    ingest_peticoes,
    scan_peticoes_dir,
)
from juris.repertory.peticoes.models import TipoPeticao


class TestScanPeticoesDir:
    """Tests for scan_peticoes_dir function."""

    def test_empty_directory(self, tmp_path: Path) -> None:
        result = scan_peticoes_dir(tmp_path)
        assert result == []

    def test_nonexistent_directory(self) -> None:
        result = scan_peticoes_dir(Path("/nonexistent/path/peticoes"))
        assert result == []

    def test_finds_pdf_files(self, tmp_path: Path) -> None:
        (tmp_path / "peticao_1.pdf").write_bytes(b"%PDF-1.4")
        (tmp_path / "peticao_2.pdf").write_bytes(b"%PDF-1.4")
        (tmp_path / "notes.txt").write_text("not a pdf")

        result = scan_peticoes_dir(tmp_path)
        assert len(result) == 2
        assert all(p.suffix == ".pdf" for p in result)

    def test_results_sorted(self, tmp_path: Path) -> None:
        (tmp_path / "c_peticao.pdf").write_bytes(b"%PDF")
        (tmp_path / "a_peticao.pdf").write_bytes(b"%PDF")
        (tmp_path / "b_peticao.pdf").write_bytes(b"%PDF")

        result = scan_peticoes_dir(tmp_path)
        names = [p.name for p in result]
        assert names == ["a_peticao.pdf", "b_peticao.pdf", "c_peticao.pdf"]


class TestExtractTextFromPdf:
    """Tests for extract_text_from_pdf function."""

    def test_extract_text(self) -> None:
        mock_page1 = MagicMock()
        mock_page1.get_text.return_value = "Page 1 text"
        mock_page2 = MagicMock()
        mock_page2.get_text.return_value = "Page 2 text"

        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page1, mock_page2]))

        mock_pymupdf = MagicMock()
        mock_pymupdf.open.return_value = mock_doc

        with patch.dict("sys.modules", {"pymupdf": mock_pymupdf}):
            result = extract_text_from_pdf(Path("/fake/path.pdf"))

        assert "Page 1 text" in result
        assert "Page 2 text" in result
        mock_doc.close.assert_called_once()


@pytest.mark.asyncio
class TestIngestPeticoes:
    """Tests for ingest_peticoes function."""

    async def test_no_llm_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "test.pdf").write_bytes(b"%PDF")
        result = await ingest_peticoes(directory=tmp_path, llm=None)
        assert result == []

    @patch("juris.repertory.ingestion.pdf_peticoes.extract_text_from_pdf")
    async def test_full_flow_with_mocked_pdf_and_llm(
        self, mock_extract: MagicMock, tmp_path: Path
    ) -> None:
        (tmp_path / "inicial_teste.pdf").write_bytes(b"%PDF")
        mock_extract.return_value = "EXMO. SR. DR. JUIZ DE DIREITO..."

        extraction_data = {
            "titulo": "Petição Inicial",
            "ramo_direito": "civil",
            "fase_processual": "conhecimento",
            "estrutura": [
                {
                    "ordem": 1,
                    "titulo": "Fatos",
                    "proposito": "Narrar",
                    "exemplo_resumido": "...",
                }
            ],
            "cadeia_argumentativa": ["Fato"],
            "padroes_argumentacao": ["Art. 186 CC"],
            "fundamento_legal": ["Art. 186 CC"],
        }

        llm = AsyncMock()
        llm.complete.return_value = LLMResponse(
            content=json.dumps(extraction_data),
            model="test",
            usage={},
            structured=extraction_data,
        )

        result = await ingest_peticoes(directory=tmp_path, llm=llm)

        assert len(result) == 1
        assert result[0].id == "tpl_inicial_teste"
        assert result[0].tipo == TipoPeticao.INICIAL
        assert result[0].titulo == "Petição Inicial"
        assert len(result[0].estrutura) == 1
