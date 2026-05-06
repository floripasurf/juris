"""Tests for STF Informativos ingester."""

from __future__ import annotations

import io
from pathlib import Path

import fitz
import pytest

from juris.repertory.corpus.models import TipoFonte
from juris.repertory.ingestion.stf_informativos import (
    STFInformativosIngester,
    _extract_case_refs,
    _extract_pdf_text,
    _split_into_digests,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_INFORMATIVO = """\
EDIÇÃO 1042/2022 | INFORMATIVO STF

1.1 PLENÁRIO

DIREITO CONSTITUCIONAL

Área de Preservação Ambiental Permanente e competência legislativa -
ADI 5675/MG

RESUMO:
É inconstitucional lei estadual que legitime ocupações em solo urbano de área de
preservação permanente (APP) fora das situações previstas em normas gerais
editadas pela União. Precedente: ADPF 109; ADI 5.312.

ADI 5675/MG, rel. Min. Ricardo Lewandowski, julgado em 17.12.2021.

Plano de redução de letalidade policial -
ADPF 635 MC-ED/RJ

RESUMO:
O Estado do Rio de Janeiro deve elaborar plano para redução da letalidade policial.
Conforme decidido no RE 1059819/PE o prazo é de 90 dias.

ADPF 635 MC-ED/RJ, rel. Min. Edson Fachin, julgado em 05.02.2022.

DIREITO TRIBUTÁRIO

Artigo 149 da CF: rol exemplificativo -
RE 1317786/PE

RESUMO:
O rol do artigo 149, § 2º, III, a, da Constituição Federal é exemplificativo.
Vide também ARE 654321/SP e HC 98765/DF.

RE 1317786/PE, rel. Min. Alexandre de Moraes, julgado em 10.02.2022.
"""


def _make_pdf(tmp_path: Path, name: str, content: str) -> Path:
    """Create a minimal PDF from plain text content using pymupdf."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), content, fontsize=10)
    out = tmp_path / name
    doc.save(str(out))
    doc.close()
    return out


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_pdf_dir(tmp_path: Path) -> Path:
    """Create a temp directory with a sample STF Informativo PDF."""
    _make_pdf(tmp_path, "Informativo_stf_1042.pdf", _SAMPLE_INFORMATIVO)
    return tmp_path


@pytest.fixture()
def sample_pdf(tmp_pdf_dir: Path) -> Path:
    return tmp_pdf_dir / "Informativo_stf_1042.pdf"


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


class TestExtractCaseRefs:
    def test_finds_multiple_types(self) -> None:
        text = "ADI 5675/MG e ADPF 635 MC-ED/RJ foram julgados. Vide RE 1317786/PE."
        refs = _extract_case_refs(text)
        assert any("ADI" in r for r in refs)
        assert any("ADPF" in r for r in refs)
        assert any("RE" in r for r in refs)

    def test_deduplicates(self) -> None:
        text = "ADI 5675/MG ... ADI 5675/MG repeated"
        refs = _extract_case_refs(text)
        assert refs.count("ADI 5675/MG") == 1

    def test_empty_text(self) -> None:
        assert _extract_case_refs("no cases here") == []


class TestSplitIntoDigests:
    def test_splits_on_case_headers(self) -> None:
        digests = _split_into_digests(_SAMPLE_INFORMATIVO)
        assert len(digests) >= 3

    def test_fallback_single_item_when_no_match(self) -> None:
        text = "Texto sem nenhum número de processo identificável. " * 10
        digests = _split_into_digests(text)
        assert len(digests) == 1
        assert digests[0][0] == ""

    def test_digest_text_contains_case_content(self) -> None:
        digests = _split_into_digests(_SAMPLE_INFORMATIVO)
        all_text = " ".join(body for _, body in digests)
        assert "inconstitucional" in all_text.lower()
        assert "letalidade" in all_text.lower()


class TestExtractPdfText:
    def test_extracts_text_from_pdf(self, sample_pdf: Path) -> None:
        text = _extract_pdf_text(sample_pdf)
        assert "INFORMATIVO STF" in text
        assert "ADI" in text

    def test_nonexistent_raises(self, tmp_path: Path) -> None:
        with pytest.raises(Exception):
            _extract_pdf_text(tmp_path / "nonexistent.pdf")


# ---------------------------------------------------------------------------
# Integration-level tests for ingester
# ---------------------------------------------------------------------------


class TestSTFInformativosIngester:
    def test_fetch_returns_fontes(self, tmp_pdf_dir: Path) -> None:
        ingester = STFInformativosIngester(source_dir=tmp_pdf_dir)
        fontes = ingester.fetch()
        assert len(fontes) >= 1

    def test_fetch_with_limit(self, tmp_pdf_dir: Path) -> None:
        # Add a second PDF to confirm limit is on files, not digests
        _make_pdf(tmp_pdf_dir, "Informativo_stf_1043.pdf", _SAMPLE_INFORMATIVO)
        ingester = STFInformativosIngester(source_dir=tmp_pdf_dir, limit=1)
        fontes = ingester.fetch()
        # Only 1 PDF processed; still ≥1 digest from it
        assert len(fontes) >= 1

    def test_fetch_nonexistent_dir(self, tmp_path: Path) -> None:
        ingester = STFInformativosIngester(source_dir=tmp_path / "nope")
        assert ingester.fetch() == []

    def test_fonte_tipo_and_hierarquia(self, tmp_pdf_dir: Path) -> None:
        ingester = STFInformativosIngester(source_dir=tmp_pdf_dir)
        fontes = ingester.fetch()
        for fonte in fontes:
            assert fonte.tipo == TipoFonte.NOTICIA_TRIBUNAL
            assert fonte.hierarquia == 7

    def test_fonte_tribunal(self, tmp_pdf_dir: Path) -> None:
        ingester = STFInformativosIngester(source_dir=tmp_pdf_dir)
        fontes = ingester.fetch()
        for fonte in fontes:
            assert fonte.tribunal == "STF"

    def test_fonte_legal_basis_and_publisher(self, tmp_pdf_dir: Path) -> None:
        ingester = STFInformativosIngester(source_dir=tmp_pdf_dir)
        fontes = ingester.fetch()
        for fonte in fontes:
            assert fonte.legal_basis == "government_publication"
            assert fonte.source_publisher == "STF"

    def test_fonte_situacao(self, tmp_pdf_dir: Path) -> None:
        ingester = STFInformativosIngester(source_dir=tmp_pdf_dir)
        fontes = ingester.fetch()
        for fonte in fontes:
            assert fonte.situacao == "publicado"

    def test_source_id_format(self, tmp_pdf_dir: Path) -> None:
        ingester = STFInformativosIngester(source_dir=tmp_pdf_dir)
        fontes = ingester.fetch()
        for fonte in fontes:
            assert fonte.id.startswith("noticia_tribunal_STF_info_")
            parts = fonte.id.split("_")
            # noticia_tribunal_STF_info_<hash8>_<position>
            assert len(parts) >= 6
            position_part = parts[-1]
            assert position_part.isdigit()

    def test_multi_case_splitting(self, tmp_pdf_dir: Path) -> None:
        ingester = STFInformativosIngester(source_dir=tmp_pdf_dir)
        fontes = ingester.fetch()
        # Sample text has 3 distinct case headings so expect ≥3 digests
        assert len(fontes) >= 3

    def test_temas_contain_case_refs(self, tmp_pdf_dir: Path) -> None:
        ingester = STFInformativosIngester(source_dir=tmp_pdf_dir)
        fontes = ingester.fetch()
        all_temas: list[str] = []
        for fonte in fontes:
            all_temas.extend(fonte.temas)
        # At least some temas should be case references
        assert any("ADI" in t or "RE" in t or "ADPF" in t for t in all_temas)

    def test_parse_produces_chunks(self, tmp_pdf_dir: Path) -> None:
        ingester = STFInformativosIngester(source_dir=tmp_pdf_dir)
        fontes = ingester.fetch()
        for fonte in fontes:
            chunks = ingester.parse(fonte)
            assert len(chunks) >= 1
            for chunk in chunks:
                assert chunk.source_type == TipoFonte.NOTICIA_TRIBUNAL
                assert chunk.text

    def test_parse_ignores_non_fonte(self) -> None:
        ingester = STFInformativosIngester()
        assert ingester.parse("not a fonte") == []
        assert ingester.parse(None) == []
