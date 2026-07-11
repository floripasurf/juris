"""UX polish: mobile nav, keyboard/screen-reader access, jargon, provenance links.

Pins the P2–P9 audit fixes against the static SPA so they can't regress:
mobile-scrollable nav, modal dialog semantics + Escape, ARIA live regions and
aria-current, lawyer-facing labels, balanced workbench grid, mobile meta tags,
and clickable corpus provenance.
"""

from __future__ import annotations

import re
from pathlib import Path

_INDEX_HTML = (
    Path(__file__).resolve().parents[3] / "src" / "juris" / "web" / "static" / "index.html"
).read_text(encoding="utf-8")


class TestMobileNav:
    def test_nav_scrolls_horizontally_on_small_screens(self) -> None:
        # inside a max-width media query, #nav must scroll instead of wrapping
        assert re.search(r"#nav\s*\{[^}]*overflow-x:\s*auto", _INDEX_HTML)


class TestMobileMeta:
    def test_theme_color_and_touch_icon(self) -> None:
        assert '<meta name="theme-color"' in _INDEX_HTML
        assert 'rel="apple-touch-icon"' in _INDEX_HTML


class TestModalAccessibility:
    def test_modal_has_dialog_semantics(self) -> None:
        modal = _INDEX_HTML[_INDEX_HTML.index('id="proc-modal"') :][:200]
        assert 'role="dialog"' in modal
        assert 'aria-modal="true"' in modal

    def test_escape_closes_modal(self) -> None:
        assert re.search(r'key\s*===?\s*"Escape"', _INDEX_HTML)


class TestScreenReader:
    def test_dynamic_status_regions_are_live(self) -> None:
        # the AI-mode status and the main notice announce to screen readers
        assert 'id="ai-session"' in _INDEX_HTML
        assert 'aria-live=' in _INDEX_HTML

    def test_active_nav_marked_current(self) -> None:
        assert "aria-current" in _INDEX_HTML


class TestLawyerLanguageResidual:
    def test_provider_and_english_jargon_gone(self) -> None:
        for jargon in ("usar Claude cloud", "pós-draft", "última sync"):
            assert jargon not in _INDEX_HTML, f"jargão residual: {jargon!r}"

    def test_friendly_replacements(self) -> None:
        assert "IA em nuvem" in _INDEX_HTML


class TestWorkbenchGrid:
    def test_grid_is_balanced_three_columns(self) -> None:
        assert re.search(r"\.workbench-grid\s*\{[^}]*repeat\(3", _INDEX_HTML)


class TestCorpusProvenance:
    def test_search_render_links_source_url(self) -> None:
        # the corpus result row exposes a clickable provenance link
        block = _INDEX_HTML[_INDEX_HTML.index("function searchCorpus") :][:1400]
        assert "source_url" in block
        assert 'target="_blank"' in block
