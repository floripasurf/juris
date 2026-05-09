"""Tests for juris.demo.disclaimer — DEMO MODE guards + footer."""

from __future__ import annotations

from juris.demo.disclaimer import (
    DEMO_BANNER,
    DEMO_DIR_PREFIX,
    DISCLAIMER_FOOTER,
    output_dir_name,
    wrap_document,
)


def test_wrap_document_includes_disclaimer_in_real_mode() -> None:
    body = "# Petição\n\nCorpo da petição."
    wrapped = wrap_document(body, demo_mode=False)
    assert DISCLAIMER_FOOTER in wrapped
    assert DEMO_BANNER not in wrapped
    assert wrapped.startswith("# Petição")


def test_wrap_document_includes_banner_and_footer_in_demo_mode() -> None:
    body = "# Petição\n\nCorpo."
    wrapped = wrap_document(body, demo_mode=True)
    assert DEMO_BANNER in wrapped
    assert DISCLAIMER_FOOTER in wrapped
    # Banner must come first so a lawyer reading top-down sees it immediately.
    assert wrapped.index(DEMO_BANNER) < wrapped.index("# Petição")
    assert wrapped.index("# Petição") < wrapped.index(DISCLAIMER_FOOTER)


def test_wrap_document_preserves_body_content() -> None:
    body = "Linha 1\nLinha 2\nLinha 3"
    wrapped = wrap_document(body, demo_mode=False)
    for line in body.split("\n"):
        assert line in wrapped


def test_output_dir_name_real_mode_has_no_prefix() -> None:
    name = output_dir_name("0001234-56.2024.8.13.0001", demo_mode=False)
    assert name == "0001234-56.2024.8.13.0001"
    assert DEMO_DIR_PREFIX not in name


def test_output_dir_name_demo_mode_has_prefix() -> None:
    name = output_dir_name("0001234-56.2024.8.13.0001", demo_mode=True)
    assert name.startswith(DEMO_DIR_PREFIX)
    assert "0001234-56.2024.8.13.0001" in name


def test_output_dir_name_strips_unsafe_chars() -> None:
    name = output_dir_name("foo/bar baz", demo_mode=False)
    assert "/" not in name
    assert " " not in name


# ---------------------------------------------------------------------------
# Sprint 17: mode_banner support in wrap_document
# ---------------------------------------------------------------------------


def test_wrap_document_with_mode_banner_real_mode() -> None:
    body = "# Petição\n\nCorpo."
    mode_banner = "> 📝 **MINUTA SUGERIDA — REVISÃO OBRIGATÓRIA**\n>\n> texto.\n"
    wrapped = wrap_document(body, demo_mode=False, mode_banner=mode_banner)
    assert DEMO_BANNER not in wrapped
    assert mode_banner in wrapped
    # Mode banner appears before the body, footer at the end.
    assert wrapped.index(mode_banner) < wrapped.index("# Petição")
    assert wrapped.index("# Petição") < wrapped.index(DISCLAIMER_FOOTER)


def test_wrap_document_with_mode_banner_demo_mode_demo_first() -> None:
    body = "# Petição\n\nCorpo."
    mode_banner = "> 🔍 **RASCUNHO DE PESQUISA**\n>\n> texto.\n"
    wrapped = wrap_document(body, demo_mode=True, mode_banner=mode_banner)
    # In demo mode both banners must appear; DEMO banner takes precedence
    # (top of document) followed by the mode banner.
    assert DEMO_BANNER in wrapped
    assert mode_banner in wrapped
    assert wrapped.index(DEMO_BANNER) < wrapped.index(mode_banner)
    assert wrapped.index(mode_banner) < wrapped.index("# Petição")


def test_wrap_document_no_mode_banner_unchanged() -> None:
    """``mode_banner=None`` must preserve the pre-Sprint-17 wrapping."""
    body = "Body."
    wrapped = wrap_document(body, demo_mode=False, mode_banner=None)
    # No extra surface introduced when mode_banner is omitted.
    assert wrapped.startswith("Body.")
    assert DISCLAIMER_FOOTER in wrapped
