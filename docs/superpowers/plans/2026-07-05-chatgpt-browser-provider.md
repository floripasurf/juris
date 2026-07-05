# ChatGPT (assinatura via browser) como IA-de-preferência — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tornar o ChatGPT (assinatura do advogado via extensão de browser) provedor de primeira classe ao lado do Claude.ai: preferência declarada, provedor real reportado pela extensão, `ai_model` no audit/payload web e aviso de divergência — sem tocar na guarda de PII.

**Architecture:** O caminho server-side de browser já é agnóstico (`BrowserSessionLLM` → `BrowserTransport`). O trabalho é: neutralizar o enum (`BROWSER`), declarar a preferência (`Settings`), fazer o id canônico do provedor real fluir extensão → wire → `LLMResponse.model` → `DraftResult.ai_model` → audit + `WebDemoRun`, e comparar declarado×real por helpers puros. Spec: `docs/superpowers/specs/2026-07-05-chatgpt-browser-provider-design.md`.

**Tech Stack:** Python 3.12 + uv, pydantic/pydantic-settings, pytest, vitest (extensão em `docs/browser-extension/`).

## Global Constraints

- Type hints em toda assinatura; docstrings Google style; sem `except Exception` novo (BLE001 é gate).
- Gates por task: `uv run pytest <arquivos> -q` no ciclo TDD; antes de cada commit: `uv run ruff check src/juris tests` e `uv run mypy src/juris`.
- Cobertura `fail_under = 72` — não regredir. Suíte baseline: **1872 passed**.
- Ids canônicos de provedor: **exatamente** `"claude"` e `"chatgpt"`. Rótulos de exibição: **exatamente** `"claude.ai (browser session)"` e `"chatgpt (browser session)"`.
- Comparação declarado×real **só** sobre canônicos, nunca sobre rótulo de UI.
- Wire (`CompletionResponse.provider`): `str | None` leniente — valor inesperado JAMAIS falha o parse.
- Invariante de PII intocado: caminho de browser de-identifica fail-closed (`allow_partial=False`, NER ativo).
- Config por env var: campos de `Settings` usam `validation_alias` e **não aceitam kwarg pelo nome do campo** (sem `populate_by_name`) — testes setam env vars via `monkeypatch.setenv`.
- Commits: `type(scope): subject`; um commit por task; trabalhar em `main`.

---

## File Structure (mapa de responsabilidades)

| Arquivo | Papel neste plano |
|---|---|
| `src/juris/core/llm_router.py` | C1: enum `BROWSER` neutro |
| `src/juris/config.py` | C2: `ai_browser_provider` |
| `src/juris/llm/browser_session.py` | C3/C4/C6: `BrowserReply`, helpers puros (`browser_model_label`, `normalize_browser_provider`, `label_to_browser_provider`, `provider_divergence`), `BrowserSessionLLM` |
| `src/juris/api/ws_schemas.py` | C4: `CompletionResponse.provider` |
| `src/juris/api/browser_bridge.py` | C4: `NativeBridgeTransport` → `BrowserReply` |
| `docs/browser-extension/selectors.js` + `content.js` | C4: `providerIdFor` + stamp do `provider` na resposta |
| `src/juris/agents/drafter.py` | C5: `DraftResult.ai_model`/`ai_model_thesis` |
| `src/juris/demo/orchestrator.py` | C5: audit `ai_model` no `demo.finished` |
| `src/juris/web/demo_service.py` | C3 wiring (label pedido) + C6 (`WebDemoRun` campos) |
| `src/juris/web/app.py` | C6: serialização em `/api/demo/run` |
| `src/juris/web/ai_status.py` + `src/juris/cli/main.py` | C7: copy por fornecedor |

Ordem: Task 1 e 2 independentes; Task 3 antes de 4, 6, 7, 8; Task 2 antes de 6, 8, 9.

---

### Task 1: C1 — Enum neutro `LLMProvider.BROWSER` (+ verificação de migração)

**Files:**
- Modify: `src/juris/core/llm_router.py:20` (enum), `:72` (MODELS), `:105` (route)
- Test: `tests/unit/test_llm_router.py:96-107`

**Interfaces:**
- Consumes: nada.
- Produces: `LLMProvider.BROWSER` (valor `"browser"`); `LLMRouter.MODELS[LLMProvider.BROWSER] == "browser session"`. Tasks 6+ referenciam `LLMProvider.BROWSER`.

- [ ] **Step 1: Verificação de migração (hipótese do spec, obrigatória)**

Run: `rg -n "claude_browser|CLAUDE_BROWSER" --type py -g '!__pycache__'`
Expected: exatamente 3 hits — `src/juris/core/llm_router.py:20`, `:105` (2 no fonte) e `tests/unit/test_llm_router.py:101`. Se aparecer QUALQUER outro hit (persistência, serialização), PARE e reporte antes de renomear.

- [ ] **Step 2: Atualizar o teste para o nome novo (falha primeiro)**

Em `tests/unit/test_llm_router.py`, no teste `test_browser_deid_routes_to_browser_session_with_deid` (linha ~96):

```python
    def test_browser_deid_routes_to_browser_session_with_deid(self) -> None:
        # Lawyer's own Claude/ChatGPT subscription via the browser extension.
        # De-id stays ON (consumer plans may train) — defense in depth.
        router = LLMRouter(_make_settings(has_api_key=False))  # no API key needed
        route = router.route(LLMTask.DRAFT, contains_pii=True, pii_mode=PIIMode.BROWSER_DEID)
        assert route.provider == LLMProvider.BROWSER
        assert route.provider.value == "browser"
        assert route.deidentify is True
        assert route.model == "browser session"
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/unit/test_llm_router.py -q`
Expected: FAIL — `AttributeError: BROWSER` (enum ainda se chama `CLAUDE_BROWSER`).

- [ ] **Step 4: Renomear no fonte**

Em `src/juris/core/llm_router.py`:

```python
# linha 20 — era: CLAUDE_BROWSER = "claude_browser"  # lawyer's own subscription via browser extension
    BROWSER = "browser"  # lawyer's own subscription (Claude.ai/ChatGPT) via browser extension

# linha 72 — era: LLMProvider.CLAUDE_BROWSER: "claude.ai (browser session)",
        LLMProvider.BROWSER: "browser session",

# linha 105 — era: provider = LLMProvider.CLAUDE_BROWSER
                provider = LLMProvider.BROWSER
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/unit/test_llm_router.py -q`
Expected: PASS (todos).

- [ ] **Step 6: Gates + commit**

```bash
uv run ruff check src/juris tests && uv run mypy src/juris && uv run pytest -q
git add src/juris/core/llm_router.py tests/unit/test_llm_router.py
git commit -m "refactor(llm): LLMProvider.CLAUDE_BROWSER -> BROWSER (fornecedor-neutro, ADR-0018)"
```

---

### Task 2: C2 — `Settings.ai_browser_provider`

**Files:**
- Modify: `src/juris/config.py` (bloco de campos com `validation_alias`, junto de `tst_inteiro_teor_enabled`)
- Test: `tests/unit/test_config_ai_browser_provider.py` (novo)

**Interfaces:**
- Consumes: nada.
- Produces: `settings.ai_browser_provider: Literal["claude", "chatgpt"] | None` (env `JURIS_AI_BROWSER_PROVIDER`). Usado nas Tasks 6, 8, 9.

- [ ] **Step 1: Teste que falha**

Criar `tests/unit/test_config_ai_browser_provider.py`:

```python
"""Preferência declarada do fornecedor de browser (ADR-0018, spec 2026-07-05)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from juris.config import Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JURIS_AI_BROWSER_PROVIDER", raising=False)


def test_default_is_none() -> None:
    assert Settings(_env_file=None).ai_browser_provider is None


def test_claude_and_chatgpt_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JURIS_AI_BROWSER_PROVIDER", "claude")
    assert Settings(_env_file=None).ai_browser_provider == "claude"
    monkeypatch.setenv("JURIS_AI_BROWSER_PROVIDER", "chatgpt")
    assert Settings(_env_file=None).ai_browser_provider == "chatgpt"


def test_invalid_value_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JURIS_AI_BROWSER_PROVIDER", "gemini")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/unit/test_config_ai_browser_provider.py -q`
Expected: FAIL — `Settings` não tem `ai_browser_provider`.

- [ ] **Step 3: Implementar**

Em `src/juris/config.py`, logo após `clock_skew_probe_enabled` (o `Literal` já está importado no topo):

```python
    ai_browser_provider: Literal["claude", "chatgpt"] | None = Field(
        None,
        validation_alias="JURIS_AI_BROWSER_PROVIDER",
        description="Fornecedor da sessão de browser declarado pelo advogado (ADR-0018).",
    )
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/unit/test_config_ai_browser_provider.py -q`
Expected: 3 passed.

- [ ] **Step 5: Gates + commit**

```bash
uv run ruff check src/juris tests && uv run mypy src/juris
git add src/juris/config.py tests/unit/test_config_ai_browser_provider.py
git commit -m "feat(config): JURIS_AI_BROWSER_PROVIDER — preferência declarada claude/chatgpt"
```

---

### Task 3: C3+C4+C6 — Helpers puros, `BrowserReply` e `BrowserSessionLLM`

**Files:**
- Modify: `src/juris/llm/browser_session.py` (arquivo inteiro reescrito abaixo)
- Test: `tests/unit/test_browser_session_llm.py` (reescrito abaixo)

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces (usados nas Tasks 4, 6, 8, 9):
  - `BrowserReply(content: str, provider: str | None)` (frozen dataclass)
  - `BrowserTransport.send(*, prompt, system) -> BrowserReply` (Protocol)
  - `browser_model_label(provider: Literal["claude","chatgpt"] | None) -> str`
  - `normalize_browser_provider(raw: str | None) -> Literal["claude","chatgpt"] | None`
  - `label_to_browser_provider(label: str | None) -> Literal["claude","chatgpt"] | None`
  - `provider_divergence(declared, actual) -> str | None`
  - `BrowserSessionLLM.complete` com `LLMResponse.model` = verdade de execução

- [ ] **Step 1: Reescrever o teste (falha primeiro)**

Substituir `tests/unit/test_browser_session_llm.py` por:

```python
"""Browser-session LLM: BrowserReply, helpers canônicos e verdade de execução (spec 2026-07-05)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from juris.llm.browser_session import (
    BrowserReply,
    BrowserSessionLLM,
    browser_model_label,
    label_to_browser_provider,
    normalize_browser_provider,
    provider_divergence,
)


class TestHelpers:
    def test_browser_model_label(self) -> None:
        assert browser_model_label("chatgpt") == "chatgpt (browser session)"
        assert browser_model_label("claude") == "claude.ai (browser session)"
        assert browser_model_label(None) == "claude.ai (browser session)"

    def test_normalize_browser_provider(self) -> None:
        assert normalize_browser_provider("claude") == "claude"
        assert normalize_browser_provider("claude.ai") == "claude"
        assert normalize_browser_provider("chatgpt") == "chatgpt"
        assert normalize_browser_provider("chatgpt.com") == "chatgpt"
        assert normalize_browser_provider("chat.openai.com") == "chatgpt"
        # inesperado / rótulo legado de UI / vazio → None, nunca adivinha
        assert normalize_browser_provider("gemini") is None
        assert normalize_browser_provider("claude.ai (browser session)") is None
        assert normalize_browser_provider(None) is None
        assert normalize_browser_provider("") is None

    def test_label_to_browser_provider_inverts_only_our_labels(self) -> None:
        assert label_to_browser_provider("chatgpt (browser session)") == "chatgpt"
        assert label_to_browser_provider("claude.ai (browser session)") == "claude"
        assert label_to_browser_provider("qwen3:latest") is None
        assert label_to_browser_provider(None) is None

    def test_provider_divergence(self) -> None:
        assert provider_divergence("chatgpt", "chatgpt") is None
        assert provider_divergence(None, "claude") is None      # nada declarado
        assert provider_divergence("chatgpt", None) is None     # real desconhecido/local
        msg = provider_divergence("chatgpt", "claude")
        assert msg is not None
        assert "ChatGPT" in msg and "Claude.ai" in msg


@pytest.mark.asyncio
async def test_complete_uses_reported_provider_as_model_truth() -> None:
    transport = AsyncMock()
    transport.send = AsyncMock(return_value=BrowserReply(content="Resposta", provider="chatgpt"))
    llm = BrowserSessionLLM(transport=transport, model="claude.ai (browser session)")

    resp = await llm.complete("Qual a tese?", system="Você é estrategista")

    assert resp.content == "Resposta"
    assert resp.model == "chatgpt (browser session)"  # real vence o pedido
    kwargs = transport.send.await_args.kwargs
    assert kwargs["prompt"] == "Qual a tese?"
    assert kwargs["system"] == "Você é estrategista"


@pytest.mark.asyncio
async def test_complete_falls_back_to_requested_label_without_provider() -> None:
    transport = AsyncMock()
    transport.send = AsyncMock(return_value=BrowserReply(content="Resposta", provider=None))
    llm = BrowserSessionLLM(transport=transport, model="chatgpt (browser session)")

    resp = await llm.complete("Qual a tese?")

    assert resp.model == "chatgpt (browser session)"  # extensão antiga → label pedido


@pytest.mark.asyncio
async def test_unexpected_provider_value_does_not_break_completion() -> None:
    transport = AsyncMock()
    transport.send = AsyncMock(return_value=BrowserReply(content="Resposta", provider="algo-novo"))
    llm = BrowserSessionLLM(transport=transport, model="claude.ai (browser session)")

    resp = await llm.complete("Qual a tese?")

    assert resp.content == "Resposta"                       # nunca falha por observabilidade
    assert resp.model == "claude.ai (browser session)"      # não-canônico → label pedido


def test_model_name() -> None:
    llm = BrowserSessionLLM(transport=AsyncMock(), model="chatgpt (browser session)")
    assert llm.model_name == "chatgpt (browser session)"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/unit/test_browser_session_llm.py -q`
Expected: FAIL — `ImportError: cannot import name 'BrowserReply'`.

- [ ] **Step 3: Implementar (substituir `src/juris/llm/browser_session.py`)**

```python
"""Browser-session LLM backend — the lawyer's own Claude/ChatGPT subscription.

Per ADR-0018, frontier-quality PII work runs through the lawyer's existing
subscription, driven by a browser extension on their machine (the session never
leaves their perimeter — a local capability in the ADR-0015 split-trust model).

This client is provider-agnostic: it relays the prompt over an injected
:class:`BrowserTransport` and wraps the reply. The extension reports back the
CANONICAL provider id it actually drove ("claude"/"chatgpt"); display labels are
always derived from the canonical id, never compared as UI text (spec 2026-07-05).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from juris.core.observability import get_logger
from juris.llm.base import AbstractLLM, LLMResponse

logger = get_logger(__name__)

BrowserProvider = Literal["claude", "chatgpt"]

_LABELS: dict[BrowserProvider, str] = {
    "claude": "claude.ai (browser session)",
    "chatgpt": "chatgpt (browser session)",
}
_CANONICAL: dict[str, BrowserProvider] = {
    "claude": "claude",
    "claude.ai": "claude",
    "chatgpt": "chatgpt",
    "chatgpt.com": "chatgpt",
    "chat.openai.com": "chatgpt",
}
_DISPLAY_NAMES: dict[BrowserProvider, str] = {"claude": "Claude.ai", "chatgpt": "ChatGPT"}


def browser_model_label(provider: BrowserProvider | None) -> str:
    """Rótulo de exibição derivado do id canônico (claude é o default histórico)."""
    return _LABELS[provider or "claude"]


def normalize_browser_provider(raw: str | None) -> BrowserProvider | None:
    """Normaliza o valor cru do wire para o id canônico; desconhecido → None.

    Leniente por design: um valor inesperado de uma extensão desatualizada nunca
    pode derrubar a completion — campo de observabilidade não falha resposta.
    """
    if not raw:
        return None
    return _CANONICAL.get(raw.strip().lower())


def label_to_browser_provider(label: str | None) -> BrowserProvider | None:
    """Inverte APENAS os nossos dois rótulos de exibição; qualquer outro → None."""
    for provider, known in _LABELS.items():
        if label == known:
            return provider
    return None


def provider_divergence(
    declared: BrowserProvider | None, actual: BrowserProvider | None
) -> str | None:
    """Mensagem de aviso quando o declarado e o realmente dirigido divergem.

    ``None`` quando: nada declarado, real desconhecido (extensão antiga ou
    fallback local — o ai_model local já evidencia isso), ou quando batem.
    """
    if declared is None or actual is None or declared == actual:
        return None
    return (
        f"Você declarou {_DISPLAY_NAMES[declared]} como IA de preferência, "
        f"mas a extensão dirigiu {_DISPLAY_NAMES[actual]}."
    )


@dataclass(frozen=True, slots=True)
class BrowserReply:
    """Resposta do transporte: conteúdo + id canônico cru reportado pela extensão."""

    content: str
    provider: str | None = None


@runtime_checkable
class BrowserTransport(Protocol):
    """Relays a prompt to the lawyer's browser session and returns the reply."""

    async def send(self, *, prompt: str, system: str | None) -> BrowserReply: ...


class BrowserSessionLLM(AbstractLLM):
    """Drives the lawyer's browser LLM session through a :class:`BrowserTransport`."""

    def __init__(
        self,
        transport: BrowserTransport,
        model: str = "claude.ai (browser session)",
    ) -> None:
        self._transport = transport
        self._model = model

    async def complete(
        self,
        prompt: str,
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        # schema/max_tokens/temperature are part of the interface but not
        # controllable through a chat UI — the prompt carries the desired format.
        reply = await self._transport.send(prompt=prompt, system=system)
        actual = normalize_browser_provider(reply.provider)
        model = browser_model_label(actual) if actual else self._model
        logger.info("browser_session_complete", model=model, chars=len(reply.content))
        return LLMResponse(content=reply.content, model=model)

    @property
    def model_name(self) -> str:
        return self._model
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/unit/test_browser_session_llm.py -q`
Expected: PASS (todos os novos).

- [ ] **Step 5: Suíte (quebra esperada do transporte) — só diagnosticar**

Run: `uv run pytest tests/unit/test_browser_bridge.py -q`
Expected: pode FALHAR — `NativeBridgeTransport.send` ainda retorna `str`. É a Task 4; NÃO conserte aqui. Se falhar, siga direto ao commit parcial abaixo **junto** com a Task 4 (mesmo commit) OU faça a Task 4 antes de commitar. Recomendado: prosseguir para a Task 4 e commitar as duas juntas.

---

### Task 4: C4 — Wire (`CompletionResponse.provider`) e `NativeBridgeTransport`

**Files:**
- Modify: `src/juris/api/ws_schemas.py:98-103` (`CompletionResponse`)
- Modify: `src/juris/api/browser_bridge.py:138-161` (`NativeBridgeTransport.send`)
- Test: `tests/unit/test_browser_bridge.py`

**Interfaces:**
- Consumes: `BrowserReply` (Task 3).
- Produces: `CompletionResponse.provider: str | None = None`; `NativeBridgeTransport.send -> BrowserReply`.

- [ ] **Step 1: Teste que falha**

Em `tests/unit/test_browser_bridge.py`, localizar o teste que exercita `NativeBridgeTransport.send` (o fake channel devolve um dict de `CompletionResponse`). Adicionar ao arquivo:

```python
@pytest.mark.asyncio
async def test_transport_returns_browser_reply_with_provider() -> None:
    from juris.api.browser_bridge import NativeBridgeTransport
    from juris.llm.browser_session import BrowserReply

    class _Channel:
        async def request(self, message: dict[str, object]) -> dict[str, object]:
            return {
                "request_id": message["request_id"],
                "success": True,
                "content": "ok",
                "error": None,
                "provider": "chatgpt",
            }

    transport = NativeBridgeTransport(_Channel())
    reply = await transport.send(prompt="p", system=None)
    assert isinstance(reply, BrowserReply)
    assert reply.content == "ok"
    assert reply.provider == "chatgpt"


@pytest.mark.asyncio
async def test_transport_tolerates_missing_provider_field() -> None:
    from juris.api.browser_bridge import NativeBridgeTransport
    from juris.llm.browser_session import BrowserReply

    class _Channel:
        async def request(self, message: dict[str, object]) -> dict[str, object]:
            return {"request_id": message["request_id"], "success": True, "content": "ok", "error": None}

    reply = await NativeBridgeTransport(_Channel()).send(prompt="p", system=None)
    assert isinstance(reply, BrowserReply)
    assert reply.provider is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/unit/test_browser_bridge.py -q`
Expected: FAIL (send retorna `str`; `provider` não existe no schema).

- [ ] **Step 3: Implementar**

Em `src/juris/api/ws_schemas.py`, `CompletionResponse`:

```python
class CompletionResponse(BaseModel):
    """Reply from the browser LLM session."""
    request_id: str
    success: bool
    content: str | None = None
    error: str | None = None
    # Canonical id of the provider the extension ACTUALLY drove ("claude"/"chatgpt").
    # Lenient str on the wire: an unexpected value must never fail the completion
    # parse (observability field — normalized server-side, spec 2026-07-05).
    provider: str | None = None
```

Em `src/juris/api/browser_bridge.py`: adicionar import no topo (`from juris.llm.browser_session import BrowserReply`) e trocar o final de `NativeBridgeTransport.send`:

```python
    async def send(self, *, prompt: str, system: str | None) -> BrowserReply:
        request = CompletionRequest(
            request_id=uuid.uuid4().hex,
            prompt=prompt,
            system=system,
            model=self._model,
            # This transport is only ever used behind DeidentifyingLLM
            # (build_ai_of_preference), so the payload here is already de-identified.
            deidentified=True,
            token=self._token,
        )
        raw = await self._channel.request(request.model_dump())
        response = CompletionResponse(**raw)
        if response.request_id != request.request_id:
            msg = (
                f"resposta correlaciona com pedido errado "
                f"(esperado {request.request_id}, veio {response.request_id})"
            )
            raise RuntimeError(msg)
        if not response.success:
            msg = response.error or "browser session completion failed"
            raise RuntimeError(msg)
        logger.info("browser_bridge_completion", request_id=request.request_id)
        return BrowserReply(content=response.content or "", provider=response.provider)
```

Se algum teste existente em `test_browser_bridge.py` assertar retorno `str` do `send` (ex.: `assert result == "..."`), atualizar para `assert result.content == "..."`.

- [ ] **Step 4: Rodar e ver passar (Tasks 3+4 juntas)**

Run: `uv run pytest tests/unit/test_browser_bridge.py tests/unit/test_browser_session_llm.py tests/unit/web/test_ai_preference_wiring.py -q`
Expected: PASS. (`test_ai_preference_wiring` não chama `send`, só monta a cadeia — deve seguir verde.)

- [ ] **Step 5: Gates + commit (Tasks 3+4)**

```bash
uv run ruff check src/juris tests && uv run mypy src/juris && uv run pytest -q
git add src/juris/llm/browser_session.py src/juris/api/ws_schemas.py src/juris/api/browser_bridge.py tests/unit/test_browser_session_llm.py tests/unit/test_browser_bridge.py
git commit -m "feat(llm): BrowserReply + provider canônico da extensão vira verdade de execução (spec 2026-07-05)"
```

---

### Task 5: C4 — Extensão reporta o provider (mudança mínima)

**Files:**
- Modify: `docs/browser-extension/selectors.js` (novo export `providerIdFor`)
- Modify: `docs/browser-extension/content.js:187-219` (handler `complete` estampa `provider`)
- Test: `docs/browser-extension/selectors.test.js`

**Interfaces:**
- Consumes: contrato do wire da Task 4 (`provider: "claude"|"chatgpt"` na resposta).
- Produces: resposta da extensão com `provider` canônico.

- [ ] **Step 1: Teste que falha (vitest)**

Em `docs/browser-extension/selectors.test.js`, no `describe("providerFor", ...)`, adicionar (e acrescentar `providerIdFor` ao import da linha 5):

```javascript
describe("providerIdFor", () => {
  it("maps hosts to canonical ids", () => {
    expect(providerIdFor("claude.ai")).toBe("claude");
    expect(providerIdFor("chatgpt.com")).toBe("chatgpt");
    expect(providerIdFor("chat.openai.com")).toBe("chatgpt");
    expect(providerIdFor("example.com")).toBeNull();
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd docs/browser-extension && npx vitest run selectors.test.js`
Expected: FAIL — `providerIdFor` não exportado.

- [ ] **Step 3: Implementar `providerIdFor` em `selectors.js`**

Logo após `providerFor` (linha ~41):

```javascript
// Canonical provider id for the wire ("claude"/"chatgpt") — the server compares
// canonical ids, never UI labels (spec 2026-07-05).
export function providerIdFor(host) {
  if (host.includes("claude.ai")) return "claude";
  if (host.includes("chatgpt.com") || host.includes("chat.openai.com")) return "chatgpt";
  return null;
}
```

- [ ] **Step 4: Estampar `provider` no handler de `content.js`**

Adicionar `providerIdFor` ao import da linha 12. No `async function complete(request)` (linha ~187), após resolver o provider:

```javascript
  const provider = providerFor(location.host);
  if (!provider) return fail(request_id, "provedor não suportado nesta aba");
  const providerId = providerIdFor(location.host);
```

E estampar nos retornos a partir daí (os `fail` anteriores à resolução ficam sem provider — desconhecido mesmo):

```javascript
  const blocker = detectBlocker(document, provider);
  if (blocker) return { ...fail(request_id, BLOCKER_MESSAGES[blocker]), provider: providerId };

  const composer = findComposer(document, provider);
  if (!composer)
    return { ...fail(request_id, "dom_changed: composer não encontrado (a interface do provedor mudou)"), provider: providerId };

  try {
    const full = system ? `${system}\n\n${prompt}` : prompt;
    insertPrompt(composer, full);
    submit(composer, provider);
    const result = await waitForCompletion(provider, request_id);
    if (!result.success) {
      const post = detectBlocker(document, provider);
      if (post) return { ...fail(request_id, BLOCKER_MESSAGES[post]), provider: providerId };
    }
    return { ...result, provider: providerId };
  } catch (e) {
    return { ...fail(request_id, `falha ao injetar/extrair: ${e?.message ?? e}`), provider: providerId };
  }
```

- [ ] **Step 5: Rodar a suíte da extensão inteira**

Run: `cd docs/browser-extension && npx vitest run`
Expected: PASS (novo teste + todos os existentes; nenhum teste existente asserta a ausência de `provider`).

- [ ] **Step 6: Commit**

```bash
git add docs/browser-extension/selectors.js docs/browser-extension/content.js docs/browser-extension/selectors.test.js
git commit -m "feat(extension): resposta reporta provider canônico (claude/chatgpt) dirigido"
```

---

### Task 6: C3 — Label pedido derivado da preferência (+ invariante de PII)

**Files:**
- Modify: `src/juris/web/demo_service.py:355-394` (`_build_ai_of_preference_llm`)
- Test: `tests/unit/web/test_ai_preference_wiring.py`

**Interfaces:**
- Consumes: `browser_model_label` (Task 3); `settings.ai_browser_provider` (Task 2).
- Produces: `NativeBridgeTransport` construído com `model=browser_model_label(preferência)`.

- [ ] **Step 1: Teste que falha**

Adicionar a `tests/unit/web/test_ai_preference_wiring.py` (usa o mesmo harness `_StubChannel`/monkeypatch dos testes existentes no arquivo):

```python
def test_declared_chatgpt_drives_requested_label_and_keeps_deid(monkeypatch) -> None:
    """Preferência=chatgpt: o label pedido muda; a de-id fail-closed NÃO muda (invariante PII)."""
    from juris.api import browser_bridge
    from juris.core import deid_llm
    from juris.web import demo_service

    monkeypatch.setenv("JURIS_AI_PREFERENCE", "1")
    monkeypatch.setenv("JURIS_BROWSER_BRIDGE_URL", "ws://127.0.0.1:8777")
    monkeypatch.setenv("JURIS_AI_BROWSER_PROVIDER", "chatgpt")
    monkeypatch.setattr(deid_llm, "default_ner_redactor", lambda: (lambda _t: []))
    # settings é singleton — forçar releitura do env neste teste
    import juris.config as config

    monkeypatch.setattr(config, "_settings", None)

    class _StubChannel:
        async def request(self, message: dict) -> dict:
            return {}

    monkeypatch.setattr(
        browser_bridge.WebSocketBridgeChannel,
        "to_localhost",
        classmethod(lambda cls, url, **kw: _StubChannel()),
    )

    llm = demo_service._build_llm(use_cloud=False)
    assert "chatgpt (browser session)" in llm.model_name  # label pedido veio da preferência
    browser_wrap = llm._primary
    assert browser_wrap._allow_partial is False  # PII: fail-closed intocado
    assert browser_wrap._ner is not None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/unit/web/test_ai_preference_wiring.py -q`
Expected: FAIL — o label ainda é o default `claude.ai (browser session)`.

- [ ] **Step 3: Implementar**

Em `src/juris/web/demo_service.py`, dentro de `_build_ai_of_preference_llm`, trocar a construção do browser (linha ~367-368):

```python
    from juris.config import get_settings
    from juris.llm.browser_session import BrowserSessionLLM, browser_model_label

    requested_label = browser_model_label(get_settings().ai_browser_provider)
    bridge_url = validate_bridge_url(os.environ.get("JURIS_BROWSER_BRIDGE_URL", ""))
    browser = BrowserSessionLLM(
        NativeBridgeTransport(WebSocketBridgeChannel.to_localhost(bridge_url), model=requested_label),
        model=requested_label,
    )
```

(O `from juris.config import get_settings` interno mais abaixo no caminho `use_cloud` fica redundante — remover o duplicado.)

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/unit/web/test_ai_preference_wiring.py -q`
Expected: PASS (novo + 3 existentes).

- [ ] **Step 5: Gates + commit**

```bash
uv run ruff check src/juris tests && uv run mypy src/juris
git add src/juris/web/demo_service.py tests/unit/web/test_ai_preference_wiring.py
git commit -m "feat(web): label da sessão de browser derivado da preferência declarada"
```

---

### Task 7: C5 — `ai_model` no DraftResult, drafter e audit do orchestrator

**Files:**
- Modify: `src/juris/agents/drafter.py` (`DraftResult` ~74; `_generate` ~531; call sites 293/400; `_infer_thesis` ~570; caller ~169)
- Modify: `src/juris/demo/orchestrator.py` (evento `demo.finished`, ~222)
- Test: `tests/unit/agents/test_drafter_ai_model.py` (novo; harness espelha `tests/unit/agents/test_grounding.py`)

**Interfaces:**
- Consumes: `LLMResponse.model` (verdade de execução — Tasks 3/4; para LLMs locais/cloud já era o rótulo real; `FallbackLLM`/`DeidentifyingLLM` já propagam via `dataclasses.replace`).
- Produces: `DraftResult.ai_model: str | None` (modelo da geração da minuta FINAL — última geração vence), `DraftResult.ai_model_thesis: str | None`; audit `demo.finished` com `ai_model`/`ai_model_thesis`. Task 8 consome `DraftResult.ai_model`.

- [ ] **Step 1: Teste que falha**

Criar `tests/unit/agents/test_drafter_ai_model.py` (o harness FakeLLM/FakeResearcher/_agent/_request/_context é o mesmo padrão de `tests/unit/agents/test_grounding.py` — copiar de lá as funções `_agent`, `_request`, `_context`, `FakeLLM`, `FakeResearcher` ajustando só o necessário):

```python
"""C5 (spec 2026-07-05): ai_model = modelo da geração da minuta final; tese em campo próprio."""

from __future__ import annotations

import pytest

# Copiar deste diretório o harness de test_grounding.py: FakeLLM, FakeResearcher,
# _agent(llm_content), _request(), _context(). Única mudança: FakeLLM ganha um
# parâmetro model para o rótulo:
#
# class FakeLLM(AbstractLLM):
#     def __init__(self, content: str, model: str = "fake-llm") -> None:
#         self._content = content
#         self._model = model
#     @property
#     def model_name(self) -> str:
#         return self._model
#     async def complete(...) -> LLMResponse:
#         return LLMResponse(content=self._content, model=self._model)


@pytest.mark.asyncio
async def test_ai_model_records_final_generation_model() -> None:
    agent = _agent("Minuta com [CITE:src-1].", model="chatgpt (browser session)")
    result = await agent.draft(_request(), _context())
    assert result.ai_model == "chatgpt (browser session)"


@pytest.mark.asyncio
async def test_ai_model_thesis_only_when_thesis_is_inferred() -> None:
    # _request() passa thesis explícita → nenhuma chamada de tese → campo None
    agent = _agent("Minuta com [CITE:src-1].", model="fake-llm")
    result = await agent.draft(_request(), _context())
    assert result.ai_model_thesis is None
```

Nota: `_agent(content, model=...)` — estender o helper copiado para repassar `model` ao `FakeLLM`. O conteúdo `"Minuta com [CITE:src-1]."` cita a fonte `src-1` que o `FakeResearcher` fornece, então a verificação de citações passa sem revisões.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/unit/agents/test_drafter_ai_model.py -q`
Expected: FAIL — `DraftResult` não tem `ai_model`.

- [ ] **Step 3: Implementar no drafter**

Em `src/juris/agents/drafter.py`:

(a) `DraftResult` (após `blocked_reason`, ~linha 88):

```python
    # Modelo efetivo da geração da minuta FINAL (última geração vence) e da
    # inferência de tese — a resposta a "qual IA escreveu isto?" (spec 2026-07-05).
    ai_model: str | None = None
    ai_model_thesis: str | None = None
```

(b) `_generate` (~531): mudar retorno para `tuple[str, str]`:

```python
    ) -> tuple[str, str]:
        """Generate a draft via LLM call; returns (markdown, effective model label)."""
```
e no final (era `return response.content`):
```python
        return response.content, response.model
```

(c) Call sites — linha ~293:
```python
            draft_text, generation_model = await self._generate(
                ...  # argumentos inalterados
            )
            result.ai_model = generation_model
```
e linha ~400 (revisão — última geração vence):
```python
                    draft_text, generation_model = await self._generate(
                        ...  # argumentos inalterados
                    )
                    result.ai_model = generation_model
```

(d) `_infer_thesis` (~570): retorno `tuple[str, str | None]`; no sucesso `return response.content.strip(), response.model`; no `except` `return f"Defesa em {request.tipo_peticao.value}", None`.

(e) Caller (~169):
```python
        if request.thesis:
            thesis = request.thesis
        else:
            thesis, result.ai_model_thesis = await self._infer_thesis(request, context)
```

- [ ] **Step 4: Audit no orchestrator**

Em `src/juris/demo/orchestrator.py`, no `details` do evento `demo.finished` (~linha 226), após `"draft_revisions"`:

```python
                "ai_model": result.draft.ai_model if result.draft else None,
                "ai_model_thesis": result.draft.ai_model_thesis if result.draft else None,
```

- [ ] **Step 5: Rodar testes do drafter + demo**

Run: `uv run pytest tests/unit/agents tests/unit/demo -q`
Expected: PASS (novos + existentes; quem chamava `_generate`/`_infer_thesis` direto em testes, se existir, ajustar para o novo retorno-tupla).

- [ ] **Step 6: Gates + commit**

```bash
uv run ruff check src/juris tests && uv run mypy src/juris && uv run pytest -q
git add src/juris/agents/drafter.py src/juris/demo/orchestrator.py tests/unit/agents/test_drafter_ai_model.py
git commit -m "feat(drafter): ai_model efetivo da minuta final + ai_model_thesis no audit (C5)"
```

---

### Task 8: C6 — Contrato web (`WebDemoRun` + `/api/demo/run`)

**Files:**
- Modify: `src/juris/web/demo_service.py:70-84` (`WebDemoRun`) e `:281` (construção)
- Modify: `src/juris/web/app.py:1597-1615` (serialização)
- Test: `tests/unit/web/test_app.py` (estender `test_create_demo_run_returns_artifact_previews`, linha ~927)

**Interfaces:**
- Consumes: `DraftResult.ai_model` (Task 7); `provider_divergence`/`label_to_browser_provider` (Task 3); `settings.ai_browser_provider` (Task 2).
- Produces: `WebDemoRun.ai_model`, `.ai_browser_provider_declared`, `.provider_warning` + as 3 chaves no JSON de `/api/demo/run`.

- [ ] **Step 1: Teste que falha**

Em `tests/unit/web/test_app.py`, no teste `test_create_demo_run_returns_artifact_previews` (~927) — ele monkeypatcha o serviço de demo; localizar onde o `WebDemoRun` fake é construído e o assert do payload. Acrescentar ao `WebDemoRun` fake `ai_model="chatgpt (browser session)"`, `ai_browser_provider_declared="claude"`, `provider_warning="Você declarou Claude.ai..."` e assertar no response JSON:

```python
    assert payload["ai_model"] == "chatgpt (browser session)"
    assert payload["ai_browser_provider_declared"] == "claude"
    assert payload["provider_warning"].startswith("Você declarou")
```

E um teste puro da montagem (mesmo arquivo ou `tests/unit/web/test_demo_provider_fields.py`, novo):

```python
def test_provider_fields_computed_from_draft_and_settings(monkeypatch) -> None:
    """Campos de IA do run: ai_model do draft, declarado do settings, warning do helper."""
    import juris.config as config
    from juris.llm.browser_session import label_to_browser_provider, provider_divergence

    monkeypatch.setenv("JURIS_AI_BROWSER_PROVIDER", "chatgpt")
    monkeypatch.setattr(config, "_settings", None)

    declared = config.get_settings().ai_browser_provider
    ai_model = "claude.ai (browser session)"  # o que o draft de fato usou
    warning = provider_divergence(declared, label_to_browser_provider(ai_model))
    assert declared == "chatgpt"
    assert warning is not None and "Claude.ai" in warning

    # fallback local: label não-browser → sem warning (o próprio ai_model evidencia)
    assert provider_divergence(declared, label_to_browser_provider("qwen3:latest")) is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/unit/web/test_app.py::test_create_demo_run_returns_artifact_previews tests/unit/web/test_demo_provider_fields.py -q`
Expected: FAIL — `WebDemoRun` não aceita `ai_model`.

- [ ] **Step 3: Implementar**

(a) `WebDemoRun` (demo_service.py ~83, após `grounding`):

```python
    # IA do run (spec 2026-07-05): modelo efetivo da minuta final, preferência
    # declarada e aviso de divergência declarado×real (por-run, sem store).
    ai_model: str | None = None
    ai_browser_provider_declared: str | None = None
    provider_warning: str | None = None
```

(b) Construção (~281):

```python
    from juris.config import get_settings
    from juris.llm.browser_session import label_to_browser_provider, provider_divergence

    draft = getattr(result, "draft", None)
    ai_model = getattr(draft, "ai_model", None)
    declared = get_settings().ai_browser_provider
    return WebDemoRun(
        succeeded=result.succeeded,
        degraded=result.degraded,
        degradation_reason=result.degradation_reason,
        errors=tuple(result.errors),
        duration_seconds=result.duration_seconds,
        output_dir=_relative_key(case_dir, request.out_root),
        artifacts=artifacts,
        estrategia=estrategia_payload(draft),
        review=review_payload(draft),
        grounding=grounding_payload(draft),
        ai_model=ai_model,
        ai_browser_provider_declared=declared,
        provider_warning=provider_divergence(declared, label_to_browser_provider(ai_model)),
    )
```

(c) Serialização em `app.py` (~1614, após `"grounding"`):

```python
        "ai_model": result.ai_model,
        "ai_browser_provider_declared": result.ai_browser_provider_declared,
        "provider_warning": result.provider_warning,
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/unit/web -q`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

```bash
uv run ruff check src/juris tests && uv run mypy src/juris
git add src/juris/web/demo_service.py src/juris/web/app.py tests/unit/web/test_app.py tests/unit/web/test_demo_provider_fields.py
git commit -m "feat(web): ai_model + aviso de divergência declarado×real no payload do run (C6)"
```

---

### Task 9: C7 — Copy por fornecedor (status + onboarding)

**Files:**
- Modify: `src/juris/web/ai_status.py` (mensagens + `declared_provider` no payload)
- Modify: `src/juris/cli/main.py:2464` (instrução final do install-native-host)
- Test: `tests/unit/web/test_ai_status.py`

**Interfaces:**
- Consumes: `normalize_browser_provider` (Task 3); env `JURIS_AI_BROWSER_PROVIDER` (Task 2).
- Produces: `ai_session_status(..., declared_provider=...)`; chave `browser.declared_provider` e `browser.training_optout` no payload de status.

- [ ] **Step 1: Teste que falha**

Adicionar a `tests/unit/web/test_ai_status.py`:

```python
def test_status_names_declared_provider_chatgpt() -> None:
    from juris.web.ai_status import ai_session_status

    status = ai_session_status(
        anthropic_key=False,
        browser_bridge=True,
        ollama_reachable=False,
        browser_bridge_url="ws://127.0.0.1:8777",
        native_host_manifest=None,
        browser_bridge_reachable=False,
        declared_provider="chatgpt",
    )
    browser = status["browser"]
    assert browser["declared_provider"] == "chatgpt"
    assert "ChatGPT" in browser["training_optout"]
    assert "Improve the model" in browser["training_optout"]


def test_status_without_declared_provider_keeps_generic_copy() -> None:
    from juris.web.ai_status import ai_session_status

    status = ai_session_status(
        anthropic_key=False,
        browser_bridge=True,
        ollama_reachable=False,
        browser_bridge_url="ws://127.0.0.1:8777",
        native_host_manifest=None,
        browser_bridge_reachable=False,
    )
    browser = status["browser"]
    assert browser["declared_provider"] is None
    assert "Claude.ai" in browser["training_optout"] and "ChatGPT" in browser["training_optout"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/unit/web/test_ai_status.py -q`
Expected: FAIL — `declared_provider` não é parâmetro.

- [ ] **Step 3: Implementar em `ai_status.py`**

(a) Assinatura de `ai_session_status` ganha `declared_provider: str | None = None` (último parâmetro).

(b) Antes do `return`, resolver nome de exibição e copy de opt-out:

```python
    display = {"claude": "Claude.ai", "chatgpt": "ChatGPT"}.get(declared_provider or "", "Claude.ai/ChatGPT")
    training_optout = {
        "claude": "Claude.ai: Settings → Privacy → desative 'Help improve Claude'.",
        "chatgpt": "ChatGPT: Settings → Data Controls → 'Improve the model for everyone' = off.",
    }.get(
        declared_provider or "",
        "Claude.ai: Privacy → desative 'Help improve Claude'. ChatGPT: Data Controls → 'Improve the model' = off.",
    )
```

(c) Nas duas mensagens que citam "Claude.ai/ChatGPT" (linhas ~53 e ~56), usar `display`:

```python
        browser_message = f"bridge ativo; mantenha {display} logado e aberto"
        ...
        browser_message = f"host instalado, mas bridge WS não respondeu; recarregue a extensão e abra {display}"
```

(d) No dict `browser` do retorno, acrescentar:

```python
            "declared_provider": declared_provider,
            "training_optout": training_optout,
```

(e) Em `resolve_ai_session_status`, passar o declarado (normalizado do env, coerente com o resto da função que lê env direto):

```python
    from juris.llm.browser_session import normalize_browser_provider

    ...
        declared_provider=normalize_browser_provider(os.environ.get("JURIS_AI_BROWSER_PROVIDER")),
```

- [ ] **Step 4: Copy do onboarding no CLI**

Em `src/juris/cli/main.py` (~2464), trocar a linha final do install-native-host:

```python
    from juris.llm.browser_session import normalize_browser_provider

    declared = normalize_browser_provider(os.environ.get("JURIS_AI_BROWSER_PROVIDER"))
    display = {"claude": "Claude.ai", "chatgpt": "ChatGPT"}.get(declared or "", "Claude.ai/ChatGPT")
    console.print(f"Depois recarregue a extensão e mantenha {display} logado em uma aba.")
    console.print("Desligue o treino do provedor (LGPD/ADR-0018):")
    if declared in (None, "claude"):
        console.print("  Claude.ai: Settings → Privacy → desative 'Help improve Claude'.")
    if declared in (None, "chatgpt"):
        console.print("  ChatGPT: Settings → Data Controls → 'Improve the model for everyone' = off.")
```

(Conferir se `os` já está importado no módulo — está, é usado amplamente no CLI.)

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/unit/web/test_ai_status.py tests/unit/cli -q`
Expected: PASS.

- [ ] **Step 6: Gates + commit**

```bash
uv run ruff check src/juris tests && uv run mypy src/juris
git add src/juris/web/ai_status.py src/juris/cli/main.py tests/unit/web/test_ai_status.py
git commit -m "feat(status): copy e opt-out de treino dirigidos pela preferência declarada (C7)"
```

---

### Task 10: Fechamento — suíte completa, extensão e doc

**Files:**
- Modify: `docs/architecture-decisions/0018-ai-provider-browser-session.md` (nota de implementação)

- [ ] **Step 1: Suíte inteira + gates de CI**

```bash
uv run pytest -q
uv run ruff check src/juris tests scripts/scan_secrets.py
uv run mypy src/juris
cd docs/browser-extension && npx vitest run && cd ../..
```
Expected: pytest ≥ baseline 1872 + novos, tudo verde; ruff/mypy/vitest limpos.

- [ ] **Step 2: Nota no ADR-0018**

Ao final da seção *Implementation* do ADR-0018, acrescentar:

```markdown
- **ChatGPT first-class (2026-07-05):** `LLMProvider.BROWSER` (neutro), preferência
  declarada via `JURIS_AI_BROWSER_PROVIDER`, extensão reporta o provider canônico
  realmente dirigido, `ai_model` no audit/payload do run e aviso de divergência
  declarado×real. Spec: `docs/superpowers/specs/2026-07-05-chatgpt-browser-provider-design.md`.
```

- [ ] **Step 3: Commit final + push**

```bash
git add docs/architecture-decisions/0018-ai-provider-browser-session.md
git commit -m "docs(adr): ADR-0018 — ChatGPT como fornecedor de primeira classe implementado"
git push origin main
```

---

## Self-review (2026-07-05)

- **Cobertura do spec:** C1→Task 1, C2→Task 2, C3→Tasks 3+6, C4→Tasks 3+4+5, C5→Task 7, C6→Tasks 3+8, C7→Task 9; migração→Task 1 Step 1; invariante PII→Task 6 Step 1; extensão mínima→Task 5. Sem lacunas.
- **Tipos consistentes:** `BrowserReply(content, provider)` igual nas Tasks 3/4; helpers com os mesmos nomes nas Tasks 3/6/8/9; ids `"claude"/"chatgpt"` e labels exatos em Global Constraints.
- **Riscos anotados no próprio plano:** quebra transitória do transporte entre Tasks 3 e 4 (commit conjunto); singleton de `Settings` nos testes (reset via `monkeypatch.setattr(config, "_settings", None)`); testes existentes de `test_browser_bridge` que assertem `str` (instrução de ajuste na Task 4).
