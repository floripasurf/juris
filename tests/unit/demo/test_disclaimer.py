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
