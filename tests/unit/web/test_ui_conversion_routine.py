"""Conversão + rotina: trial countdown/upgrade CTA and deadline badge in nav.

Static pins so the conversion + daily-safety affordances can't silently regress.
"""

from __future__ import annotations

from pathlib import Path

_INDEX_HTML = (
    Path(__file__).resolve().parents[3] / "src" / "juris" / "web" / "static" / "index.html"
).read_text(encoding="utf-8")


class TestTrialStatusAndUpgrade:
    def test_trial_pill_and_upgrade_cta_ship(self) -> None:
        assert 'id="trial-status"' in _INDEX_HTML
        assert "renderTrialStatus" in _INDEX_HTML
        # upgrade path is a real contact (mailto), shown only for trials
        assert "Contratar" in _INDEX_HTML
        assert "mailto:" in _INDEX_HTML

    def test_trial_status_is_driven_by_access_summary(self) -> None:
        # the pill is updated from the /api/access data already loaded on boot
        assert "renderTrialStatus(" in _INDEX_HTML
        summary = _INDEX_HTML[_INDEX_HTML.index("function renderAccessSummary") :][:600]
        assert "renderTrialStatus" in summary


class TestDeadlineBadge:
    def test_nav_badge_helper_and_agenda_wiring(self) -> None:
        assert "function setNavBadge(" in _INDEX_HTML
        # the workbench render feeds the critical-deadline count into the Agenda tab
        render = _INDEX_HTML[_INDEX_HTML.index("function renderWorkbench") :][:2400]
        assert 'setNavBadge("agenda"' in render
