# ChatGPT (assinatura via browser) como IA-de-preferência — Design

**Data:** 2026-07-05 · **Status:** aprovado (brainstorming) · **Relaciona-se a:** ADR-0015 (fronteira do agente local), ADR-0016 (PII e IA de preferência), ADR-0018 (IA via sessão de browser do advogado)

## Contexto

O ADR-0018 já decidiu usar a **assinatura do próprio advogado** dirigida por uma extensão de browser como provedor de fronteira para tarefas com PII — e já escopou **Claude.ai OU ChatGPT** (o onboarding cita "ChatGPT: Data Controls → Improve the model = off"). O código server-side do caminho de browser é **agnóstico de fornecedor**: `BrowserSessionLLM` (`src/juris/llm/browser_session.py`) repassa o prompt por um `BrowserTransport` e a guarda de PII (`build_ai_of_preference(..., allow_partial=False)`) é neutra.

O que falta é tornar o ChatGPT um provedor de **primeira classe**: hoje o enum, os rótulos de modelo e a copy são Claude-específicos, e o provedor **realmente** dirigido pela extensão não volta para ser auditado.

### Decisões do brainstorming (2026-07-05)

1. **Escopo:** apenas a **assinatura** (ChatGPT via browser), paralelo ao Claude.ai. **Sem** backend de API da OpenAI.
2. **Identidade:** **preferência explícita** declarada pelo advogado + **rótulo real** reportado pela extensão gravado no audit + **aviso de divergência** quando declarado ≠ real.
3. **Rename** `LLMProvider.CLAUDE_BROWSER` → `LLMProvider.BROWSER`: aprovado.
4. **Aviso de divergência por-artefato** (sem store persistente de "último provedor visto"): aprovado.

## Invariante de PII (não muda — reafirmado)

O caminho de browser **sempre** de-identifica fail-closed antes do prompt sair do perímetro (`PIIMode.BROWSER_DEID` → `route.deidentify = True`; `build_ai_of_preference(..., allow_partial=False)`; atestação `deidentified=True` no `CompletionRequest`; re-scan independente da extensão). O ChatGPT herda isso integralmente — é nuvem americana e **só vê conteúdo redigido**. Dado cru de cliente continua no modelo local (Ollama). Nenhuma mudança nesta guarda; apenas cobertura de teste confirmando que vale com `ai_browser_provider="chatgpt"`.

## Estado atual (arquivos e assinaturas reais)

- `src/juris/core/llm_router.py`
  - `LLMProvider.CLAUDE_BROWSER = "claude_browser"` (enum, valor **não persistido** — 3 referências: linhas 72, 105 e um teste).
  - `LLMRouter.MODELS[LLMProvider.CLAUDE_BROWSER] = "claude.ai (browser session)"`.
  - `route(...)`: `PIIMode.BROWSER_DEID` → `provider = LLMProvider.CLAUDE_BROWSER`, `deidentify = True`.
- `src/juris/llm/browser_session.py`
  - `BrowserTransport.send(*, prompt, system) -> str` (Protocol; devolve só o conteúdo).
  - `BrowserSessionLLM.complete(...) -> LLMResponse(content=..., model=self._model)` (model = default do construtor, não o real).
- `src/juris/api/ws_schemas.py`
  - `CompletionRequest`: tem `model: str = "claude.ai (browser session)"` e `deidentified: bool`.
  - `CompletionResponse`: `request_id, success, content, error` — **não** reporta provedor/modelo real.
- `src/juris/api/browser_bridge.py`
  - `NativeBridgeTransport(channel, model="claude.ai (browser session)", *, token=None)`; `send()` monta `CompletionRequest`, parseia `CompletionResponse`, **retorna `response.content or ""`** (descarta qualquer rótulo real).
- `src/juris/web/demo_service.py`
  - `_ai_preference_enabled()` lê `JURIS_AI_PREFERENCE`.
  - `_build_ai_of_preference_llm(*, use_cloud)` constrói `BrowserSessionLLM(NativeBridgeTransport(...))` + fallback de-id.
- `src/juris/web/ai_status.py`
  - `ai_session_status(...)` resolve `mode` e a copy do browser (hoje "Claude.ai/ChatGPT" genérico).
- `src/juris/config.py` — **nenhum** campo de preferência de fornecedor de browser.
- O `LLMResponse.model` **não é auditado** em nenhum lugar hoje (analyze/draft não gravam o modelo efetivo).

## Componentes do design

### C1 — Router neutro de fornecedor
- Renomear `LLMProvider.CLAUDE_BROWSER` → `LLMProvider.BROWSER` (valor `"browser"`). Atualizar as 3 referências (`MODELS`, `route`, teste).
- `MODELS[LLMProvider.BROWSER] = "browser session"` (rótulo genérico; o real vem da execução).
- `route(...)`: `PIIMode.BROWSER_DEID` → `provider = LLMProvider.BROWSER`, `deidentify = True` (lógica inalterada).
- **Interface produzida:** `LLMProvider.BROWSER`.

### C2 — Preferência declarada (Settings)
- Novo campo em `Settings` (`src/juris/config.py`):
  ```python
  ai_browser_provider: Literal["claude", "chatgpt"] | None = Field(
      default=None, validation_alias="JURIS_AI_BROWSER_PROVIDER"
  )
  ```
- Semântica: `None` = não declarado (neutro). É o que o advogado declara no onboarding.
- **Interface produzida:** `settings.ai_browser_provider`.

### C3 — Rótulo pedido (o que pedimos à extensão dirigir)
- Helper puro para o label do request a partir da preferência:
  ```python
  def request_model_label(provider: str | None) -> str:
      # "chatgpt" -> "chatgpt (browser session)"
      # "claude"/None -> "claude.ai (browser session)"
  ```
  (localização: `src/juris/llm/browser_session.py` ou um pequeno módulo de labels reutilizado por transport + status.)
- `_build_ai_of_preference_llm` passa `model=request_model_label(settings.ai_browser_provider)` ao `NativeBridgeTransport`.
- **Interface produzida:** `request_model_label(provider) -> str`.

### C4 — Rótulo real (o que a extensão de fato dirigiu)
- `CompletionResponse` (ws_schemas) ganha `provider: str | None = None` — a extensão reporta o modelo/tab real (ex.: `"chatgpt (browser session)"`). Campo opcional → compatível com extensão que ainda não reporta (cai no label pedido).
- Nova seam de retorno do transporte:
  ```python
  @dataclass(frozen=True, slots=True)
  class BrowserReply:
      content: str
      model: str | None  # rótulo real reportado pela extensão, se houver
  ```
  `BrowserTransport.send(*, prompt, system) -> BrowserReply` (era `-> str`). Única impl real: `NativeBridgeTransport` (devolve `BrowserReply(response.content or "", response.provider)`). Fakes de teste atualizados.
- `BrowserSessionLLM.complete`: `LLMResponse(content=reply.content, model=reply.model or self._model)`.
- **Interface produzida:** `BrowserReply`; `LLMResponse.model` reflete a verdade de execução.

### C5 — Audit do rótulo real
- O `drafter` já tem o `LLMResponse` em mãos (`src/juris/agents/drafter.py:562` e `:583`, `response = await self._llm.complete(...)`), e o pipeline já audita em `src/juris/demo/orchestrator.py` (`self._audit.log(...)` em ~150/206/222). Threading: o drafter expõe o `response.model` efetivo no seu resultado; o orchestrator o inclui no evento de audit do artefato (campo `ai_model`).
- Analyzer/estratégia seguem o mesmo padrão quando produzem via LLM.
- **Interface produzida:** eventos de audit de análise/minuta passam a conter `ai_model` (o provedor/modelo de IA efetivo).

### C6 — Aviso de divergência (por-artefato, sem store)
- O resultado do run/minuta carrega **declarado** (`settings.ai_browser_provider`) e **real** (do `LLMResponse.model`).
- Helper puro:
  ```python
  def provider_divergence(declared: str | None, actual_model: str | None) -> str | None:
      # retorna mensagem quando declarado e real divergem; None caso contrário
      # declared None -> None (nada declarado, sem aviso)
  ```
- O payload web do artefato expõe o aviso quando presente; o console mostra ("você declarou ChatGPT, mas a extensão dirigiu Claude.ai"). `ai_status` também aplica o mesmo helper quando conhece um real recente (best-effort; sem persistência).
- **Interface produzida:** `provider_divergence(declared, actual_model) -> str | None`.

### C7 — Copy de onboarding/status por fornecedor
- A copy do passo "desligar treino" é dirigida pela preferência: Claude.ai (*Privacy → don't help improve*) vs ChatGPT (*Data Controls → Improve the model = off*).
- `ai_status` nomeia a declarada em vez do genérico "Claude.ai/ChatGPT" quando `ai_browser_provider` está definido.
- Localização da copy de onboarding: onde hoje o CLI/console instrui o setup do browser (`src/juris/cli/main.py` ~2464 e o painel de IA do console).

## Fluxo de dados (tarefa com PII, preferência = chatgpt)

```
analyze/draft (PII)
  → LLMRouter.route(BROWSER_DEID) → provider=BROWSER, deidentify=True
  → prepare_payload → de-id fail-closed (ensure_cloud_safe)
  → BrowserSessionLLM.complete(prompt de-id)
      → NativeBridgeTransport.send (model pedido = "chatgpt (browser session)")
      → extensão dirige a aba ChatGPT logada, reporta provider real
      → BrowserReply(content, model="chatgpt (browser session)")
  → LLMResponse(model=real) → re-id da resposta
  → audit grava ai_model=real (C5)
  → provider_divergence(declared="chatgpt", actual=real) → None (bate)
```

## Testes (por componente)

- **C1:** `route(BROWSER_DEID)` → `provider == LLMProvider.BROWSER`, `deidentify is True`; label de `MODELS[BROWSER]`.
- **C2:** parsing de `JURIS_AI_BROWSER_PROVIDER` = claude / chatgpt / ausente (None).
- **C3:** `request_model_label("chatgpt")`, `("claude")`, `(None)`.
- **C4:** `CompletionResponse` com `provider` flui a `LLMResponse.model`; ausente → cai no label pedido; fake transport devolve `BrowserReply`.
- **C5:** o evento de audit de analyze/draft contém o modelo de IA efetivo.
- **C6:** `provider_divergence`: declarado≠real → mensagem; ==→ None; declarado None → None.
- **C7:** preferência=chatgpt → passo do ChatGPT na copy; status nomeia o declarado.
- **PII (invariante):** com `ai_browser_provider="chatgpt"`, o caminho de browser ainda de-identifica fail-closed (`allow_partial=False`); prompt cru nunca sai.

## Fora de escopo (YAGNI)

- Backend de API da OpenAI (`src/juris/llm/openai.py`, `openai_api_key`, provider `OPENAI`).
- Preferência por-tenant (fase multi-tenant; hoje é Settings/env, um valor por deploy).
- Implementação da extensão Chrome (artefato à parte em `docs/browser-extension`). Este design define o **contrato de servidor** que a extensão deve preencher: reportar `CompletionResponse.provider` com o modelo/tab real.
- Store persistente de "último provedor visto" para o status (divergência é por-artefato).

## Riscos herdados (ADR-0018, registrados)

- **ToS.** Dirigir sessão logada do ChatGPT por automação pode conflitar com o ToS da OpenAI (mesmo risco do Claude browser; menor para uso próprio do escritório). A extensão deve degradar graciosamente para o fallback local.
- **Sem DPA** em plano consumidor: a postura LGPD repousa sobre de-id + opt-out de treino, não contrato — aceitável no piloto, revisitar em multi-tenant.
- **Fragilidade** de automação de UI: a extensão precisa falhar visível e cair para o local.
