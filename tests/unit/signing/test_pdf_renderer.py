"""Tests for the PDF renderer module."""

from __future__ import annotations

import builtins
import hashlib
import re
from unittest.mock import MagicMock, patch

import pytest

from juris.signing.pdf_renderer import RenderResult, render_petition_pdf

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_MD = "Hello world"

COMPLEX_MD = """\
# Contestacao

## Dos Fatos

O autor alega que **houve descumprimento** do contrato celebrado em 01/01/2024.

## Do Direito

Conforme *art. 389 do Codigo Civil*:

> O inadimplente responde por perdas e danos.

### Jurisprudencia

- STJ, REsp 1.234.567/SP
- TJSP, Apelacao 0001234-56.2023.8.26.0100

## Do Pedido

Requer a improcedencia dos pedidos iniciais.
"""


def _make_fake_weasyprint_doc(html_string: str) -> MagicMock:
    """Create a mock WeasyPrint document with two pages."""
    page1 = MagicMock()
    page2 = MagicMock()
    doc = MagicMock()
    doc.pages = [page1, page2]
    doc.write_pdf.return_value = b"%PDF-1.4 fake content"
    return doc


def _make_fake_html_cls() -> MagicMock:
    """Return a mock weasyprint.HTML class."""
    html_cls = MagicMock()
    html_cls.return_value.render.side_effect = _make_fake_weasyprint_doc
    return html_cls


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRenderPetitionPdf:
    """Tests for render_petition_pdf."""

    def test_produces_nonempty_bytes(self) -> None:
        """Rendered PDF must have non-empty bytes."""
        with patch(
            "juris.signing.pdf_renderer._render_with_weasyprint",
            return_value=(b"%PDF-1.4 test", 1),
        ):
            result = render_petition_pdf(MINIMAL_MD, "0001234-56.2024.8.26.0100", "contestacao")
        assert len(result.pdf_bytes) > 0

    def test_hash_is_valid_sha256(self) -> None:
        """pdf_hash must be a 64-char lowercase hex string matching SHA-256."""
        with patch(
            "juris.signing.pdf_renderer._render_with_weasyprint",
            return_value=(b"%PDF-1.4 hash-check", 1),
        ):
            result = render_petition_pdf(MINIMAL_MD, "0001234-56.2024.8.26.0100", "inicial")
        assert re.fullmatch(r"[0-9a-f]{64}", result.pdf_hash)
        assert result.pdf_hash == hashlib.sha256(result.pdf_bytes).hexdigest()

    def test_page_count_gte_one(self) -> None:
        """Page count must be at least 1."""
        with patch(
            "juris.signing.pdf_renderer._render_with_weasyprint",
            return_value=(b"%PDF-1.4 pages", 3),
        ):
            result = render_petition_pdf(MINIMAL_MD, "0001234-56.2024.8.26.0100", "recurso")
        assert result.page_count >= 1

    def test_minimal_markdown(self) -> None:
        """A single-line Markdown must produce a valid result."""
        with patch(
            "juris.signing.pdf_renderer._render_with_weasyprint",
            return_value=(b"%PDF-1.4 minimal", 1),
        ):
            result = render_petition_pdf("Texto simples.", "000-test", "inicial")
        assert isinstance(result, RenderResult)
        assert result.page_count == 1

    def test_complex_markdown(self) -> None:
        """Complex Markdown with headers, lists, bold, blockquotes must render."""
        with patch(
            "juris.signing.pdf_renderer._render_with_weasyprint",
            return_value=(b"%PDF-1.4 complex", 2),
        ):
            result = render_petition_pdf(
                COMPLEX_MD, "0001234-56.2024.8.26.0100", "contestacao"
            )
        assert result.page_count >= 1
        assert len(result.pdf_bytes) > 0

    def test_case_number_in_html(self) -> None:
        """Case number must appear in the generated HTML."""
        case_number = "9999999-99.2024.8.26.0100"
        captured_html: list[str] = []

        def capture_weasy(html: str) -> tuple[bytes, int]:
            captured_html.append(html)
            return (b"%PDF-1.4 captured", 1)

        with patch(
            "juris.signing.pdf_renderer._render_with_weasyprint",
            side_effect=capture_weasy,
        ):
            render_petition_pdf(MINIMAL_MD, case_number, "inicial")

        assert len(captured_html) == 1
        assert case_number in captured_html[0]

    def test_metadata_included(self) -> None:
        """Custom metadata keys must appear in the HTML output."""
        extra = {"Advogado": "Dr. Silva", "OAB": "SP-123456"}
        captured_html: list[str] = []

        def capture_weasy(html: str) -> tuple[bytes, int]:
            captured_html.append(html)
            return (b"%PDF-1.4 meta", 1)

        with patch(
            "juris.signing.pdf_renderer._render_with_weasyprint",
            side_effect=capture_weasy,
        ):
            render_petition_pdf(MINIMAL_MD, "000-test", "inicial", metadata=extra)

        html_out = captured_html[0]
        assert "Advogado" in html_out
        assert "Dr. Silva" in html_out
        assert "OAB" in html_out
        assert "SP-123456" in html_out

    def test_empty_markdown_raises(self) -> None:
        """Empty markdown text must raise ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            render_petition_pdf("", "000-test", "inicial")

    def test_whitespace_only_raises(self) -> None:
        """Whitespace-only markdown must also raise ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            render_petition_pdf("   \n\t  ", "000-test", "inicial")

    def test_fallback_to_reportlab(self) -> None:
        """When weasyprint is unavailable, should fall back to reportlab."""
        with patch(
            "juris.signing.pdf_renderer._render_with_weasyprint",
            side_effect=ImportError("no weasyprint"),
        ), patch(
            "juris.signing.pdf_renderer._render_with_reportlab",
            return_value=(b"%PDF-1.4 reportlab", 1),
        ):
            result = render_petition_pdf(MINIMAL_MD, "000-test", "inicial")
        assert len(result.pdf_bytes) > 0
        assert result.page_count == 1

    def test_no_backend_raises_runtime_error(self) -> None:
        """When both backends are unavailable, RuntimeError is raised."""
        with patch(
            "juris.signing.pdf_renderer._render_with_weasyprint",
            side_effect=ImportError("no weasyprint"),
        ), patch(
            "juris.signing.pdf_renderer._render_with_reportlab",
            side_effect=ImportError("no reportlab"),
        ), pytest.raises(RuntimeError, match="No PDF backend"):
            render_petition_pdf(MINIMAL_MD, "000-test", "inicial")

    def test_oserror_native_libs_falls_back_to_reportlab(self) -> None:
        """A weasyprint OSError (missing gobject/pango) must ALSO fall back to
        reportlab, not bubble up as a crash — this is the frozen-bundle case
        where weasyprint is importable-but-broken (native libs excluded)."""
        with patch(
            "juris.signing.pdf_renderer._render_with_weasyprint",
            side_effect=OSError("cannot load library 'libgobject-2.0-0': error 0x7e"),
        ), patch(
            "juris.signing.pdf_renderer._render_with_reportlab",
            return_value=(b"%PDF-1.4 reportlab-after-oserror", 1),
        ):
            result = render_petition_pdf(MINIMAL_MD, "000-test", "inicial")
        assert result.pdf_bytes == b"%PDF-1.4 reportlab-after-oserror"
        assert result.page_count == 1

    def test_no_backend_raises_runtime_error_after_oserror(self) -> None:
        """When weasyprint fails with OSError AND reportlab is also missing,
        the final RuntimeError must still surface (no silent crash)."""
        with patch(
            "juris.signing.pdf_renderer._render_with_weasyprint",
            side_effect=OSError("cannot load library 'libpango-1.0-0'"),
        ), patch(
            "juris.signing.pdf_renderer._render_with_reportlab",
            side_effect=ImportError("no reportlab"),
        ), pytest.raises(RuntimeError, match="No PDF backend"):
            render_petition_pdf(MINIMAL_MD, "000-test", "inicial")

    def test_render_result_is_frozen(self) -> None:
        """RenderResult must be immutable (frozen dataclass)."""
        result = RenderResult(pdf_bytes=b"test", page_count=1, pdf_hash="abc")
        with pytest.raises(AttributeError):
            result.page_count = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Real-reportlab fallback (no mocking of _render_with_reportlab)
#
# These simulate the frozen-bundle scenario: weasyprint's native pango/gobject
# dylibs aren't in the PyInstaller bundle, so `from weasyprint import HTML`
# fails either as ImportError (module excluded entirely) or OSError (module
# importable but its native libs are missing). Both must produce a REAL PDF
# via reportlab, not just a mocked byte string.
# ---------------------------------------------------------------------------


def _patch_weasyprint_import(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    """Make ``from weasyprint import HTML`` raise ``error`` while leaving
    every other import untouched."""
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "weasyprint":
            raise error
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


class TestRealReportlabFallback:
    """Exercise the actual reportlab rendering path end to end."""

    def test_import_error_produces_real_pdf(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """weasyprint absent entirely (frozen exclude list) -> real reportlab PDF."""
        _patch_weasyprint_import(monkeypatch, ImportError("No module named 'weasyprint'"))
        result = render_petition_pdf(
            COMPLEX_MD, "0001234-56.2024.8.26.0100", "contestacao"
        )
        assert result.pdf_bytes.startswith(b"%PDF")
        assert result.page_count >= 1
        assert result.pdf_hash == hashlib.sha256(result.pdf_bytes).hexdigest()

    def test_oserror_native_libs_produces_real_pdf(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """weasyprint importable but native libs missing -> real reportlab PDF."""
        _patch_weasyprint_import(
            monkeypatch, OSError("cannot load library 'libgobject-2.0-0': error 0x7e")
        )
        result = render_petition_pdf(MINIMAL_MD, "0001234-56.2024.8.26.0100", "inicial")
        assert result.pdf_bytes.startswith(b"%PDF")
        assert result.page_count >= 1
        assert result.pdf_hash == hashlib.sha256(result.pdf_bytes).hexdigest()
