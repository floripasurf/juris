"""Tests for STF Landmark Cases PDF ingester."""

from __future__ import annotations

from pathlib import Path

import pytest

from juris.repertory.corpus.models import FonteJurisprudencia, TipoFonte
from juris.repertory.ingestion.stf_landmark import (
    STFLandmarkIngester,
    _extract_ementa,
    _parse_filename,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_pdf_dir(tmp_path: Path) -> Path:
    """Create a temp directory with sample STF landmark PDFs."""
    try:
        import pymupdf  # type: ignore[import-untyped]
    except ImportError:
        import fitz as pymupdf  # type: ignore[import-untyped,no-redef]

    def _make_pdf(filename: str, body: str) -> None:
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), body, fontsize=10)
        doc.save(str(tmp_path / filename))
        doc.close()

    _make_pdf(
        "ADC_12.pdf",
        (
            "TRIBUNAL PLENO\n\n"
            "EMENTA: AÇÃO DIRETA DE CONSTITUCIONALIDADE. NEPOTISMO. "
            "Vedação ao nepotismo nos três poderes.\n\n"
            "ACÓRDÃO\n"
            "Vistos, relatados e discutidos estes autos...\n"
        ),
    )

    _make_pdf(
        "HC_82424.pdf",
        (
            "SEGUNDA TURMA\n\n"
            "EMENTA CRIME DE RACISMO. Publicação de livros antissemitas.\n\n"
            "VOTO\n"
            "O relator votou pela denegação da ordem.\n"
        ),
    )

    _make_pdf(
        "ADPF_132_ADI_4277.pdf",
        (
            "TRIBUNAL PLENO\n\n"
            "EMENTA: DIREITO DE FAMÍLIA. União homoafetiva reconhecida como "
            "entidade familiar.\n\n"
            "RELATÓRIO\n"
            "Trata-se de arguição de descumprimento de preceito fundamental.\n"
        ),
    )

    # Place a PDF inside an Informativos/ subfolder — must be excluded
    info_dir = tmp_path / "Informativos"
    info_dir.mkdir()
    _make_pdf_in = lambda filename, body: (  # noqa: E731
        _make_pdf_in_dir(info_dir, filename, body)
    )

    def _make_pdf_in_dir(directory: Path, filename: str, body: str) -> None:
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), body, fontsize=10)
        doc.save(str(directory / filename))
        doc.close()

    _make_pdf_in_dir(info_dir, "Informativo_1000.pdf", "Informativo STF 1000\nResumo dos julgamentos.")

    return tmp_path


# ---------------------------------------------------------------------------
# Unit tests: _parse_filename
# ---------------------------------------------------------------------------

class TestParseFilename:
    def test_simple_class_number(self) -> None:
        classe, numero = _parse_filename("ADC_12")
        assert classe == "ADC"
        assert numero == "12"

    def test_adi(self) -> None:
        classe, numero = _parse_filename("ADI_1856")
        assert classe == "ADI"
        assert numero == "1856"

    def test_hc(self) -> None:
        classe, numero = _parse_filename("HC_82424")
        assert classe == "HC"
        assert numero == "82424"

    def test_compound_name(self) -> None:
        # ADPF_132_ADI_4277 -> classe=ADPF, numero=132_ADI_4277
        classe, numero = _parse_filename("ADPF_132_ADI_4277")
        assert classe == "ADPF"
        assert numero == "132_ADI_4277"

    def test_no_underscore(self) -> None:
        classe, numero = _parse_filename("RE848826")
        assert classe == "RE848826"
        assert numero == ""

    def test_lowercase_normalised(self) -> None:
        classe, _ = _parse_filename("re_123")
        assert classe == "RE"


# ---------------------------------------------------------------------------
# Unit tests: _extract_ementa
# ---------------------------------------------------------------------------

class TestExtractEmenta:
    def test_extracts_after_ementa_colon(self) -> None:
        text = "EMENTA: Direito constitucional. Princípio da igualdade.\n\nACÓRDÃO\nTexto do acórdão."
        ementa = _extract_ementa(text)
        assert "Direito constitucional" in ementa
        assert "ACÓRDÃO" not in ementa

    def test_extracts_after_ementa_no_colon(self) -> None:
        text = "EMENTA Direito penal. Tráfico de entorpecentes.\n\nVOTO\nO ministro votou..."
        ementa = _extract_ementa(text)
        assert "Direito penal" in ementa
        assert "VOTO" not in ementa

    def test_fallback_to_first_500_chars_when_no_ementa(self) -> None:
        text = "A" * 600
        ementa = _extract_ementa(text)
        assert len(ementa) == 500

    def test_ementa_capped_at_500_chars(self) -> None:
        long_body = "X" * 1000
        text = f"EMENTA: {long_body}\n\nACÓRDÃO\nfoo"
        ementa = _extract_ementa(text)
        assert len(ementa) <= 500

    def test_case_insensitive_match(self) -> None:
        text = "ementa: Texto da ementa aqui.\n\nACÓRDÃO\nTexto."
        ementa = _extract_ementa(text)
        assert "Texto da ementa aqui" in ementa


# ---------------------------------------------------------------------------
# Integration tests: STFLandmarkIngester
# ---------------------------------------------------------------------------

class TestSTFLandmarkIngester:
    def test_fetch_returns_fontes(self, tmp_pdf_dir: Path) -> None:
        ingester = STFLandmarkIngester(source_dir=tmp_pdf_dir)
        fontes = ingester.fetch()
        # 3 valid PDFs (Informativo excluded)
        assert len(fontes) == 3

    def test_fetch_excludes_informativos(self, tmp_pdf_dir: Path) -> None:
        ingester = STFLandmarkIngester(source_dir=tmp_pdf_dir)
        fontes = ingester.fetch()
        ids = [f.id for f in fontes]
        assert not any("Informativo" in fid for fid in ids)

    def test_fetch_with_limit(self, tmp_pdf_dir: Path) -> None:
        ingester = STFLandmarkIngester(source_dir=tmp_pdf_dir, limit=2)
        fontes = ingester.fetch()
        assert len(fontes) == 2

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        ingester = STFLandmarkIngester(source_dir=tmp_path / "nope")
        fontes = ingester.fetch()
        assert fontes == []

    def test_fonte_tipo_is_acordao_landmark(self, tmp_pdf_dir: Path) -> None:
        ingester = STFLandmarkIngester(source_dir=tmp_pdf_dir)
        fontes = ingester.fetch()
        for fonte in fontes:
            assert fonte.tipo == TipoFonte.ACORDAO_LANDMARK

    def test_fonte_hierarquia_is_3(self, tmp_pdf_dir: Path) -> None:
        ingester = STFLandmarkIngester(source_dir=tmp_pdf_dir)
        fontes = ingester.fetch()
        for fonte in fontes:
            assert fonte.hierarquia == 3

    def test_fonte_tribunal_is_stf(self, tmp_pdf_dir: Path) -> None:
        ingester = STFLandmarkIngester(source_dir=tmp_pdf_dir)
        fontes = ingester.fetch()
        for fonte in fontes:
            assert fonte.tribunal == "STF"

    def test_fonte_situacao_and_publisher(self, tmp_pdf_dir: Path) -> None:
        ingester = STFLandmarkIngester(source_dir=tmp_pdf_dir)
        fontes = ingester.fetch()
        for fonte in fontes:
            assert fonte.situacao == "publicado"
            assert fonte.source_publisher == "STF"
            assert fonte.legal_basis == "government_publication"

    def test_source_id_format(self, tmp_pdf_dir: Path) -> None:
        ingester = STFLandmarkIngester(source_dir=tmp_pdf_dir)
        fontes = ingester.fetch()
        fonte_adc = next(f for f in fontes if "ADC" in f.id)
        assert fonte_adc.id == "acordao_landmark_STF_ADC_12"

    def test_compound_source_id(self, tmp_pdf_dir: Path) -> None:
        ingester = STFLandmarkIngester(source_dir=tmp_pdf_dir)
        fontes = ingester.fetch()
        fonte_adpf = next(f for f in fontes if "ADPF" in f.id)
        assert fonte_adpf.id == "acordao_landmark_STF_ADPF_132_ADI_4277"

    def test_ementa_extracted_from_pdf(self, tmp_pdf_dir: Path) -> None:
        ingester = STFLandmarkIngester(source_dir=tmp_pdf_dir)
        fontes = ingester.fetch()
        fonte_adc = next(f for f in fontes if "ADC_12" in f.id)
        assert "NEPOTISMO" in fonte_adc.ementa.upper() or "nepotismo" in fonte_adc.ementa.lower()

    def test_parse_produces_chunks(self, tmp_pdf_dir: Path) -> None:
        ingester = STFLandmarkIngester(source_dir=tmp_pdf_dir)
        fontes = ingester.fetch()
        for fonte in fontes:
            chunks = ingester.parse(fonte)
            assert len(chunks) >= 1
            for chunk in chunks:
                assert chunk.text
                assert chunk.source_type == TipoFonte.ACORDAO_LANDMARK

    def test_parse_ignores_non_fonte(self, tmp_pdf_dir: Path) -> None:
        ingester = STFLandmarkIngester(source_dir=tmp_pdf_dir)
        assert ingester.parse("not a fonte") == []
        assert ingester.parse(None) == []
