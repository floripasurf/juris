"""Convert drafter Markdown output to a signable PDF document."""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass

from juris.core.observability import get_logger

logger = get_logger(__name__)

# On macOS, Homebrew installs gobject/pango under a non-default path.
# WeasyPrint uses cffi.dlopen which respects DYLD_LIBRARY_PATH but macOS SIP
# strips it from child processes. We patch it at process level before the
# first WeasyPrint import so `uv run juris file` just works without env setup.
if sys.platform == "darwin" and not os.environ.get("DYLD_LIBRARY_PATH"):
    _brew_lib_candidates = ["/opt/homebrew/lib", "/usr/local/lib"]
    _brew_libs = [p for p in _brew_lib_candidates if os.path.isdir(p)]
    if _brew_libs:
        os.environ["DYLD_LIBRARY_PATH"] = ":".join(_brew_libs)

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<style>
@page {{
    size: A4;
    margin: 3cm 2.5cm;
    @top-center {{
        content: "Processo: {case_number}";
        font-family: serif;
        font-size: 9pt;
        color: #555;
    }}
    @bottom-center {{
        content: counter(page) " / " counter(pages);
        font-family: serif;
        font-size: 9pt;
        color: #555;
    }}
}}
body {{
    font-family: "Times New Roman", Times, serif;
    font-size: 12pt;
    line-height: 1.6;
    text-align: justify;
    color: #000;
}}
h1 {{
    font-size: 16pt;
    text-align: center;
    margin-bottom: 1.5em;
}}
h2 {{
    font-size: 14pt;
    margin-top: 1.5em;
    margin-bottom: 0.5em;
}}
h3 {{
    font-size: 12pt;
    margin-top: 1.2em;
    margin-bottom: 0.4em;
}}
blockquote {{
    margin-left: 2cm;
    margin-right: 1cm;
    font-size: 11pt;
    line-height: 1.4;
}}
.metadata {{
    font-size: 10pt;
    color: #555;
    margin-bottom: 2em;
}}
</style>
</head>
<body>
{metadata_html}
{body_html}
</body>
</html>
"""


@dataclass(frozen=True, slots=True)
class RenderResult:
    """Immutable result of a PDF rendering operation.

    Attributes:
        pdf_bytes: Raw PDF content.
        page_count: Number of pages in the generated PDF.
        pdf_hash: SHA-256 hex digest of ``pdf_bytes``.
    """

    pdf_bytes: bytes
    page_count: int
    pdf_hash: str


def _build_metadata_html(
    case_number: str,
    petition_type: str,
    metadata: dict[str, str] | None,
) -> str:
    """Build an HTML block for petition metadata."""
    parts: list[str] = [
        f"<p><strong>Processo:</strong> {case_number}</p>",
        f"<p><strong>Tipo:</strong> {petition_type}</p>",
    ]
    if metadata:
        for key, value in metadata.items():
            parts.append(f"<p><strong>{key}:</strong> {value}</p>")
    return f'<div class="metadata">{"".join(parts)}</div>'


def _md_to_html(markdown_text: str) -> str:
    """Convert Markdown text to HTML.

    Uses the ``markdown`` library when available, otherwise falls back
    to a minimal regex-based converter.
    """
    try:
        import markdown

        return markdown.markdown(
            markdown_text,
            extensions=["tables", "fenced_code"],
        )
    except ImportError:  # pragma: no cover
        import re

        html = markdown_text
        html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
        html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
        html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)
        html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
        html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)
        html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
        html = re.sub(
            r"(<li>.*?</li>(?:\n<li>.*?</li>)*)",
            r"<ul>\1</ul>",
            html,
            flags=re.DOTALL,
        )
        paragraphs = html.split("\n\n")
        processed: list[str] = []
        for p in paragraphs:
            stripped = p.strip()
            if stripped and not stripped.startswith("<"):
                processed.append(f"<p>{stripped}</p>")
            else:
                processed.append(stripped)
        return "\n".join(processed)


def _render_with_weasyprint(html: str) -> tuple[bytes, int]:
    """Render HTML to PDF using WeasyPrint.

    Returns:
        Tuple of (pdf_bytes, page_count).

    Raises:
        ImportError: If weasyprint is not installed.
        RuntimeError: If native libs (gobject/pango) are missing, with a
            clear fix message instead of the cryptic ctypes error.
    """
    try:
        from weasyprint import HTML  # type: ignore[import-untyped]
    except OSError as exc:
        msg = str(exc)
        if "libgobject" in msg or "libpango" in msg or "cannot load library" in msg:
            hint = "WeasyPrint cannot find its native libraries (gobject/pango).\n\n"
            if sys.platform == "darwin":
                hint += (
                    "Fix: brew install glib pango gobject-introspection\n"
                    "Then run with:\n"
                    "  DYLD_LIBRARY_PATH=/opt/homebrew/lib uv run juris ...\n"
                )
            else:
                hint += "Fix: apt install libpango-1.0-0 libgobject-2.0-0  (or equivalent)\n"
            raise RuntimeError(hint) from exc
        raise

    doc = HTML(string=html).render()
    pdf_bytes: bytes = doc.write_pdf()
    return pdf_bytes, len(doc.pages)


def _render_with_reportlab(html: str, text: str) -> tuple[bytes, int]:
    """Fallback PDF renderer using ReportLab.

    Args:
        html: Ignored (kept for interface consistency).
        text: Plain/markdown text to render.

    Returns:
        Tuple of (pdf_bytes, page_count).
    """
    import io

    from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # type: ignore[import-untyped]
    from reportlab.lib.units import cm  # type: ignore[import-untyped]
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer  # type: ignore[import-untyped]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=3 * cm,
        bottomMargin=3 * cm,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
    )
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "JurisBody",
        parent=styles["Normal"],
        fontName="Times-Roman",
        fontSize=12,
        leading=19,
        alignment=4,  # justified
    )
    story: list[object] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            story.append(Spacer(1, 12))
        else:
            safe = stripped.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            story.append(Paragraph(safe, body_style))
    if not story:
        story.append(Paragraph("&nbsp;", body_style))
    doc.build(story)
    pdf_bytes = buf.getvalue()
    page_count = max(1, pdf_bytes.count(b"/Type /Page") - pdf_bytes.count(b"/Type /Pages"))
    return pdf_bytes, page_count


def render_petition_pdf(
    markdown_text: str,
    case_number: str,
    petition_type: str,
    metadata: dict[str, str] | None = None,
) -> RenderResult:
    """Render a petition from Markdown to a signable PDF.

    Args:
        markdown_text: Petition content in Markdown format.
        case_number: Brazilian CNJ case number (``processo``).
        petition_type: Type of petition (e.g. ``contestacao``, ``inicial``).
        metadata: Optional key-value pairs included in the document header.

    Returns:
        A ``RenderResult`` with the PDF bytes, page count and SHA-256 hash.

    Raises:
        ValueError: If ``markdown_text`` is empty.
        RuntimeError: If no PDF backend is available.
    """
    if not markdown_text or not markdown_text.strip():
        raise ValueError("markdown_text must not be empty")

    body_html = _md_to_html(markdown_text)
    metadata_html = _build_metadata_html(case_number, petition_type, metadata)
    full_html = _HTML_TEMPLATE.format(
        case_number=case_number,
        metadata_html=metadata_html,
        body_html=body_html,
    )

    logger.info(
        "rendering_petition_pdf",
        case_number=case_number,
        petition_type=petition_type,
    )

    try:
        pdf_bytes, page_count = _render_with_weasyprint(full_html)
        logger.debug("pdf_rendered_with_weasyprint", pages=page_count)
    except ImportError:
        logger.warning("weasyprint_unavailable, falling_back_to_reportlab")
        try:
            pdf_bytes, page_count = _render_with_reportlab(full_html, markdown_text)
            logger.debug("pdf_rendered_with_reportlab", pages=page_count)
        except ImportError as exc:
            raise RuntimeError(
                "No PDF backend available. Install weasyprint or reportlab."
            ) from exc

    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()

    logger.info(
        "petition_pdf_ready",
        page_count=page_count,
        size_bytes=len(pdf_bytes),
        hash=pdf_hash[:16],
    )

    return RenderResult(
        pdf_bytes=pdf_bytes,
        page_count=page_count,
        pdf_hash=pdf_hash,
    )
