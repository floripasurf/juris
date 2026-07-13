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

import re
from pathlib import Path

from fastapi.testclient import TestClient

from juris.web.app import app

_INDEX_HTML = (
    Path(__file__).resolve().parents[3] / "src" / "juris" / "web" / "static" / "index.html"
).read_text(encoding="utf-8")

_PRIVACIDADE_HTML = (
    Path(__file__).resolve().parents[3] / "src" / "juris" / "web" / "static" / "privacidade.html"
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

    def test_privacy_policy_pins_honest_retention_claims(self) -> None:
        """Pin every load-bearing sentence of §1/§5 of privacidade.html.

        The audited overpromise ("não reter" absolute) and its first replacement
        ("nunca saem do computador" — false in co-located mode, where credentials
        transit the server transiently) must never come back. What IS promised:
        credentials never STORED; process data retained per-office only while the
        account is active; auto-erasure at trial end with a registered certificate;
        on-demand LGPD erasure.
        """
        # §1 ¶1 — credentials: transient use, never stored; agent-local as opt-in stronger mode
        assert "nunca ficam armazenadas por nós" in _PRIVACIDADE_HTML
        assert "usadas apenas de forma transitória para autenticar no PJe/MNI" in _PRIVACIDADE_HTML
        assert "instalado no seu próprio computador, elas nem chegam a sair dele" in _PRIVACIDADE_HTML
        # §1 ¶2 — process data: per-office retention while active, auto-erasure with certificate
        assert "isolados por escritório, enquanto sua conta estiver ativa" in _PRIVACIDADE_HTML
        assert "apagados automaticamente" in _PRIVACIDADE_HTML
        assert "certificado de eliminação registrado" in _PRIVACIDADE_HTML
        assert "pedir a eliminação a qualquer momento" in _PRIVACIDADE_HTML
        assert "LGPD, Lei 13.709/2018" in _PRIVACIDADE_HTML
        # §3 — credentials transient + de-identified cloud AI
        assert "nunca ficam armazenadas pelo Causia" in _PRIVACIDADE_HTML
        assert "de forma de-identificada" in _PRIVACIDADE_HTML
        # §5 — trial-end auto-erasure + on-demand (LGPD) erasure
        assert "apagados automaticamente do ambiente Causia" in _PRIVACIDADE_HTML
        assert "certificado de eliminação registrado em nossos logs de conformidade" in _PRIVACIDADE_HTML
        assert "eliminação antecipada" in _PRIVACIDADE_HTML
        assert "direito garantido pela LGPD" in _PRIVACIDADE_HTML
        # the retired overclaims
        assert "não reter" not in _PRIVACIDADE_HTML
        assert "nunca saem do computador" not in _PRIVACIDADE_HTML

    def test_access_key_generation_for_team_is_visible(self) -> None:
        assert 'data-nav="acessos"' in _MAIN_NAV
        assert 'id="access-key-form"' in _INDEX_HTML
        assert "/api/access-keys" in _INDEX_HTML

    def test_agent_pairing_is_browser_first_with_technical_fallback(self) -> None:
        assert 'id="agent-setup"' in _INDEX_HTML
        assert 'id="agent-credentials-modal"' in _INDEX_HTML
        assert 'id="agent-credentials-form"' in _INDEX_HTML
        assert 'id="connect-btn"' in _INDEX_HTML
        assert 'id="agent-credentials-edit"' in _INDEX_HTML
        assert 'id="first-access-credentials"' in _INDEX_HTML
        assert 'id="first-access-connect"' in _INDEX_HTML
        assert 'id="c_seed"' in _INDEX_HTML
        assert "Primeiro acesso: siga nesta ordem" in _INDEX_HTML
        assert "Baixar e abrir o Causia Agent" in _INDEX_HTML
        assert "Espete o token e abra o agente" in _INDEX_HTML
        assert "Sincronize seus processos" in _INDEX_HTML
        assert "Salvar e sincronizar" in _INDEX_HTML
        assert "Atualizar credenciais" in _INDEX_HTML
        assert "Adicionar processos por número CNJ" in _INDEX_HTML
        assert "Causia Agent ainda não conectado neste computador" in _INDEX_HTML
        assert "Agente remoto indisponível" not in _INDEX_HTML
        assert "localAgentCredentialsStatus" in _INDEX_HTML
        assert "Credenciais locais já salvas neste computador" in _INDEX_HTML
        assert "por CNJs informados" in _INDEX_HTML
        assert "agent-pairing-button" not in _INDEX_HTML
        assert "agent-credentials-link" not in _INDEX_HTML
        assert "Gerar comando do agente" not in _INDEX_HTML
        assert "/api/agent/pairing" in _INDEX_HTML
        assert "/api/connect" in _INDEX_HTML
        assert "/credentials/status" in _INDEX_HTML
        assert "/credentials" in _INDEX_HTML
        assert "http://127.0.0.1:8765" in _INDEX_HTML
        assert "http://localhost:8765" in _INDEX_HTML
        assert "pairLocalAgent" in _INDEX_HTML
        assert "local.endpoint" in _INDEX_HTML
        assert "show_agent_command" in _INDEX_HTML
        assert "comando técnico" in _INDEX_HTML

    def test_credential_inputs_hidden_by_default(self) -> None:
        """CPF/PIN must not flash visible before loadAgentMode() confirms co-located mode.

        The raw HTML must ship these inputs hidden; JS (applyAgentMode()) only reveals them
        once the backend confirms remote mode is False. If the /api/agent-mode fetch fails
        entirely, the fail-closed default (AGENT_REMOTE stays True) must keep them hidden too.
        """
        cpf_tag = re.search(r'<input id="c_cpf"[^>]*>', _INDEX_HTML)
        pin_tag = re.search(r'<input id="c_pin"[^>]*>', _INDEX_HTML)
        assert cpf_tag is not None and "hidden" in cpf_tag.group(0), cpf_tag
        assert pin_tag is not None and "hidden" in pin_tag.group(0), pin_tag

    def test_console_offers_agent_download(self) -> None:
        assert "Baixar o Causia Agent" in _INDEX_HTML
        assert "CausiaAgente.dmg" in _INDEX_HTML or "agent/download" in _INDEX_HTML


class TestConsoleOnboarding:
    def test_workbench_ships_two_path_empty_state(self) -> None:
        # activation: explore agent-free with sample data OR connect the real caseload
        assert "Explorar com dados de exemplo" in _INDEX_HTML
        assert "Conectar meu acervo" in _INDEX_HTML
        assert "exploreWithSampleData" in _INDEX_HTML

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
