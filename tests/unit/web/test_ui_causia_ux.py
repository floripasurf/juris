"""UX goals: conversion honesty, console onboarding, lawyer-facing language.

Pins the three tracks of the Causia UX overhaul against the static SPA so the
copy/structure can't silently regress:

1. Conversão & promessa — anonymous trial CTA, key as secondary flow, legal footer.
   No manual access request as the primary path.
2. Onboarding & confiança — actionable empty-state on the workbench.
3. Linguagem de advogado — no raw dev jargon in the primary interface; the
   internal "Piloto" telemetry tab is out of the main nav.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from juris.web.app import app

_INDEX_HTML = (
    Path(__file__).resolve().parents[3] / "src" / "juris" / "web" / "static" / "index.html"
).read_text(encoding="utf-8")

# The <nav id="nav"> … </nav> block: what the lawyer sees as primary tasks.
_NAV_START = _INDEX_HTML.index('<nav id="nav">')
_MAIN_NAV = _INDEX_HTML[_NAV_START : _INDEX_HTML.index("</nav>", _NAV_START)]


class TestConversionAndPromise:
    def test_primary_cta_starts_anonymous_trial(self) -> None:
        assert "Começar teste anônimo" in _INDEX_HTML
        assert 'id="start-trial"' in _INDEX_HTML
        assert "Solicitar acesso" not in _INDEX_HTML

    def test_key_flow_is_secondary_disclosure(self) -> None:
        assert "Já tenho uma chave" in _INDEX_HTML
        # the key input still ships (existing customers must get in)
        assert 'id="landing-api-key"' in _INDEX_HTML

    def test_copy_does_not_promise_false_self_service(self) -> None:
        assert "Teste gratuito por 30 dias, sem cadastro" not in _INDEX_HTML
        assert "sem informar nome, e-mail ou escritório" in _INDEX_HTML
        assert "sem nome, e-mail, telefone ou formulário comercial" in _INDEX_HTML

    def test_trial_endpoint_is_wired_from_landing(self) -> None:
        assert 'window.fetch("/api/trial/start"' in _INDEX_HTML
        assert "causiaTrialSetup" in _INDEX_HTML
        assert "causiaStartView" in _INDEX_HTML

    def test_footer_with_contact_and_legal_links(self) -> None:
        assert "<footer" in _INDEX_HTML
        assert "Termos" in _INDEX_HTML
        assert "Privacidade" in _INDEX_HTML

    def test_hero_uses_real_visual_asset_not_fake_dashboard_mock(self) -> None:
        assert "causia-hero-legal-desk-v2.jpg" in _INDEX_HTML
        assert "app-frame" not in _INDEX_HTML

    def test_legal_pages_are_served_publicly(self) -> None:
        client = TestClient(app)
        for page in ("termos", "privacidade"):
            resp = client.get(f"/static/{page}.html")
            assert resp.status_code == 200, page
            assert resp.headers["content-type"].startswith("text/html")
        # allowlist: no arbitrary .html leaks
        assert client.get("/static/index-secret.html").status_code == 404

    def test_access_key_generation_for_team_is_visible(self) -> None:
        assert 'data-nav="acessos"' in _MAIN_NAV
        assert 'id="access-key-form"' in _INDEX_HTML
        assert "/api/access-keys" in _INDEX_HTML

    def test_agent_pairing_is_browser_first_with_technical_fallback(self) -> None:
        assert 'id="agent-setup"' in _INDEX_HTML
        assert 'id="agent-credentials-modal"' in _INDEX_HTML
        assert 'id="agent-credentials-form"' in _INDEX_HTML
        assert 'id="connect-btn"' in _INDEX_HTML
        assert "Salvar e sincronizar" in _INDEX_HTML
        assert "agent-pairing-button" not in _INDEX_HTML
        assert "agent-credentials-link" not in _INDEX_HTML
        assert "Gerar comando do agente" not in _INDEX_HTML
        assert "/api/agent/pairing" in _INDEX_HTML
        assert "/api/connect" in _INDEX_HTML
        assert "/credentials/status" in _INDEX_HTML
        assert "/credentials" in _INDEX_HTML
        assert "pairLocalAgent" in _INDEX_HTML
        assert "local.endpoint" in _INDEX_HTML
        assert "show_agent_command" in _INDEX_HTML
        assert "comando técnico" in _INDEX_HTML


class TestConsoleOnboarding:
    def test_workbench_ships_actionable_empty_state(self) -> None:
        assert "Comece importando seu acervo" in _INDEX_HTML
        assert "Ir para Acervo" in _INDEX_HTML

    def test_empty_state_is_gated_on_all_queues_empty(self) -> None:
        # a function that decides whether the workbench is entirely empty
        assert "workbenchIsEmpty" in _INDEX_HTML


class TestLawyerLanguage:
    def test_pilot_telemetry_tab_not_in_main_nav(self) -> None:
        assert 'data-nav="piloto"' not in _MAIN_NAV

    def test_no_raw_dev_jargon_in_interface(self) -> None:
        for jargon in (
            "Nightly",
            "fixture demo",
            "de-id ✓",
            "dry-run / preflight",
            "Piloto instrumentado",
        ):
            assert jargon not in _INDEX_HTML, f"jargão ainda presente: {jargon!r}"

    def test_friendly_replacements_present(self) -> None:
        for label in (
            "Atualização automática",
            "Dados demonstrativos",
            "dados protegidos",
        ):
            assert label in _INDEX_HTML, f"rótulo amigável ausente: {label!r}"

    def test_machine_values_have_label_layer(self) -> None:
        # the raw token must not be a visible text-input default …
        assert '<input id="fl_tipo_doc" value="manifestacao"' not in _INDEX_HTML
        assert '<input id="fl_tipo_peticao" value="manifestacao"' not in _INDEX_HTML
        # … it lives behind a friendly label in a select
        assert ">Manifestação</option>" in _INDEX_HTML
