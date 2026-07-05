# ChatGPT (assinatura via browser) como IA-de-preferência — Design

**Data:** 2026-07-05 · **Status:** aprovado (brainstorming) · **Relaciona-se a:** ADR-0015 (fronteira do agente local), ADR-0016 (PII e IA de preferência), ADR-0018 (IA via sessão de browser do advogado)

## Contexto

O ADR-0018 já decidiu usar a **assinatura do próprio advogado** dirigida por uma extensão de browser como provedor de fronteira para tarefas com PII — e já escopou **Claude.ai OU ChatGPT** (o onboarding cita "ChatGPT: Data Controls → Improve the model = off"). O código server-side do caminho de browser é **agnóstico de fornecedor**: `BrowserSessionLLM` (`src/juris/llm/browser_session.py`) repassa o prompt por um `BrowserTransport` e a guarda de PII (`build_ai_of_preference(..., allow_partial=False)`) é neutra.

O que falta é tornar o ChatGPT um provedor de **primeira classe**: hoje o enum, os rótulos de modelo e a copy são Claude-específicos, e o provedor **realmente** dirigido pela extensão não volta para ser auditado.

### Decisões do brainstorming (2026-07-05)

1. **Escopo:** apenas a **assinatura** (ChatGPT via browser), paralelo ao Claude.ai. **Sem** backend de API da OpenAI.
2. **Identidade:** **preferência explícita** declarada pelo advogado + **rótulo real** reportado pela extensão gravado no audit + **aviso de divergência** quando declarado ≠ real.
3. **Rename** `LLMProvider.CLAUDE_BROWSER` → `LLMProvider.BROWSER`: aprovado.
4. **Aviso de divergência sem store persistente** ("último provedor visto" não é armazenado): aprovado. Refinado após revisão externa (Codex, 2026-07-05): o aviso viaja no **run** (`WebDemoRun`), não em cada artefato — o `ai_model` é fato do run (modelo da minuta final, ver C5) e repeti-lo em ~6 artefatos seria ruído sem granularidade real.

### Incorporações da revisão externa (Codex, 2026-07-05)

1. Contrato web explícito para `ai_model`/aviso (campos no `WebDemoRun` + `/api/demo/run`) — aceito (C6), com o refinamento run-vs-artefato acima.
2. Separação id canônico × rótulo de exibição + normalização no servidor — aceito (C4), com um ajuste: o wire fica `str | None` leniente (não `Literal` estrito), para que uma extensão com versão defasada nunca derrube o parse da completion; o canônico é garantido pelo `normalize_browser_provider` no servidor.
3. Mudança mínima da extensão entra no escopo (reportar `provider`) — aceito; sem ela o contrato de servidor ficaria inerte.
4. Precedência do modelo efetivo com múltiplas chamadas/fallback — aceito (C5): `ai_model` = geração da minuta final; tese em campo próprio de audit; fallback propaga a verdade via `FallbackLLM`.
5. Rename tratado como hipótese verificável de migração leve — aceito (seção "Migração"): `rg` obrigatório no plano; logs antigos não migram.

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
- Helper puro **único** de rótulo (canônico → exibição), reutilizado pelo request (C3), pela resposta (C4) e pelo status (C7):
  ```python
  def browser_model_label(provider: Literal["claude", "chatgpt"] | None) -> str:
      # "chatgpt" -> "chatgpt (browser session)"
      # "claude"/None -> "claude.ai (browser session)"
  ```
  (localização: `src/juris/llm/browser_session.py`, ao lado do `BrowserReply`.)
- `_build_ai_of_preference_llm` passa `model=browser_model_label(settings.ai_browser_provider)` ao `NativeBridgeTransport`.
- **Interface produzida:** `browser_model_label(provider) -> str`.

### C4 — Provedor real (o que a extensão de fato dirigiu)

Separação explícita entre **id canônico** (para comparação) e **rótulo de exibição** (para UI/audit) — comparação nunca é feita sobre texto de UI:

- **Wire:** `CompletionResponse` (ws_schemas) ganha `provider: str | None = None`. A extensão reporta o id canônico do host que dirigiu — ela já o conhece (`selectors.js:37`, `providerFor(host)` com chaves `claude.ai`/`chatgpt.com`). Valores esperados: `"claude"` / `"chatgpt"`. O tipo no wire é **`str | None` leniente, não `Literal`**: um valor inesperado de uma extensão desatualizada/adiantada não pode derrubar o parse da completion inteira (campo de observabilidade nunca falha a resposta). Ausente → compatível com extensão antiga (cai no declarado/pedido, sem aviso).
- **Normalização (servidor):** helper puro canônico:
  ```python
  def normalize_browser_provider(raw: str | None) -> Literal["claude", "chatgpt"] | None:
      # "claude", "claude.ai" -> "claude"; "chatgpt", "chatgpt.com", "chat.openai.com" -> "chatgpt"
      # qualquer outro valor (inclusive rótulos legados de UI) -> None
  ```
- **Extensão (mudança mínima, EM escopo — ver "Escopo da extensão"):** `content.js` inclui `provider` no objeto de resposta (linha ~155), derivado do host via `providerFor`; teste em `content.test.js`.
- Nova seam de retorno do transporte:
  ```python
  @dataclass(frozen=True, slots=True)
  class BrowserReply:
      content: str
      provider: str | None  # id canônico cru reportado pela extensão (normalizar no consumo)
  ```
  `BrowserTransport.send(*, prompt, system) -> BrowserReply` (era `-> str`). Única impl real: `NativeBridgeTransport` (devolve `BrowserReply(response.content or "", response.provider)`). Fakes de teste atualizados.
- `BrowserSessionLLM.complete`: `LLMResponse(content=reply.content, model=browser_model_label(normalize_browser_provider(reply.provider)) if reply.provider else self._model)`. O rótulo de exibição é derivado do canônico (helper único do C3), nunca o contrário.
- **Interfaces produzidas:** `BrowserReply`; `normalize_browser_provider(raw)`; `LLMResponse.model` reflete a verdade de execução.

### C5 — Audit do rótulo real (e qual modelo "vale")

Regra de precedência quando há múltiplas chamadas LLM e/ou fallback:

- **`ai_model` do run = o modelo da geração da minuta final** — o `response.model` da chamada de `_generate_draft` (`src/juris/agents/drafter.py:562`); com loop de revisão, a **última** geração vence. É o que o console mostra e o que o aviso de divergência compara.
- **Chamadas auxiliares** (ex.: inferência de tese, `drafter.py:583`) vão apenas ao **audit detalhado** (campo próprio, ex. `ai_model_thesis`), nunca ao `ai_model` do run — evita ambiguidade sobre "quem escreveu a minuta".
- **Fallback:** o `FallbackLLM.complete` já retorna o `LLMResponse` de quem **de fato serviu** (browser ou o backup local) — o `.model` propaga a verdade de execução sem trabalho extra. Se o browser caiu para o Ollama, `ai_model` reflete o Ollama (e a divergência compara contra isso: declarado "chatgpt" + real local ⇒ aviso de que a sessão não foi usada).
- Threading: o drafter hoje **descarta** `response.model` (retorna só `response.content`) — passa a expor o modelo efetivo da geração final no seu resultado; o orchestrator (`src/juris/demo/orchestrator.py`, `self._audit.log(...)` em ~150/206/222) inclui `ai_model` no evento de audit do run/minuta.
- **Interface produzida:** eventos de audit de análise/minuta contêm `ai_model` (modelo efetivo da minuta final) e, quando houver, `ai_model_thesis`.

### C6 — Aviso de divergência (por-run, sem store) + contrato web explícito

- Helper puro comparando **valores canônicos** (nunca texto de UI):
  ```python
  def provider_divergence(
      declared: Literal["claude", "chatgpt"] | None,
      actual: Literal["claude", "chatgpt"] | None,
  ) -> str | None:
      # declared None -> None (nada declarado, sem aviso)
      # actual None (extensão antiga não reportou, ou fallback local) -> None
      # declared != actual -> mensagem ("você declarou ChatGPT, mas a extensão dirigiu Claude.ai")
  ```
  Nota: quando o run caiu no **fallback local**, o `ai_model` (C5) já evidencia isso; o aviso de sessão-não-usada vem do `ai_model` local no payload, não deste helper.
- **Contrato web explícito** (hoje `WebDemoRun`/`WebDemoArtifact` não têm nenhum campo de IA — `src/juris/web/demo_service.py:62`, serialização em `src/juris/web/app.py:1597`): `WebDemoRun` ganha três campos, serializados em `/api/demo/run`:
  - `ai_model: str | None` — modelo efetivo da minuta final (C5);
  - `ai_browser_provider_declared: str | None` — a preferência declarada (C2);
  - `provider_warning: str | None` — saída de `provider_divergence`, quando houver.
  **Nível run, não artefato** (refinamento sobre a revisão): o próprio C5 define `ai_model` como fato do run (o modelo da minuta final) — um run gera ~6 artefatos e repetir o mesmo aviso em cada um seria ruído sem granularidade real. O console mostra o aviso junto do resultado do run/minuta.
- `ai_status` aplica o mesmo helper quando conhece um real recente (best-effort; sem persistência).
- **Interfaces produzidas:** `provider_divergence(declared, actual) -> str | None`; campos `ai_model`/`ai_browser_provider_declared`/`provider_warning` no `WebDemoRun` e no payload de `/api/demo/run`.

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
      → extensão dirige a aba ChatGPT logada, responde {content, provider: "chatgpt"}
      → BrowserReply(content, provider="chatgpt")
      → normalize_browser_provider("chatgpt") → "chatgpt"
  → LLMResponse(model="chatgpt (browser session)") → re-id da resposta
  → drafter expõe o model da minuta final → WebDemoRun.ai_model + audit ai_model (C5)
  → provider_divergence(declared="chatgpt", actual="chatgpt") → None (bate; provider_warning=None)
```

## Testes (por componente)

- **C1:** `route(BROWSER_DEID)` → `provider == LLMProvider.BROWSER`, `deidentify is True`; label de `MODELS[BROWSER]`.
- **C2:** parsing de `JURIS_AI_BROWSER_PROVIDER` = claude / chatgpt / ausente (None).
- **C3:** `browser_model_label("chatgpt")`, `("claude")`, `(None)`.
- **C4:** `normalize_browser_provider`: `"claude"`/`"claude.ai"` → `"claude"`; `"chatgpt"`/`"chatgpt.com"`/`"chat.openai.com"` → `"chatgpt"`; valor inesperado/rótulo legado → `None`. `CompletionResponse` com `provider` flui a `LLMResponse.model` via label canônico; `provider` ausente → cai no label pedido; valor inesperado no wire **não** falha o parse; fake transport devolve `BrowserReply`.
- **C5:** `ai_model` do run = modelo da geração da minuta final (última, com revisão); tese inferida por outro modelo vai a `ai_model_thesis` no audit, nunca ao `ai_model`; com fallback browser→local, `ai_model` reflete o local. Evento de audit contém `ai_model`.
- **C6:** `provider_divergence` (canônicos): declarado≠real → mensagem; == → None; declarado None → None; real None → None. `WebDemoRun`/`/api/demo/run` expõem `ai_model`, `ai_browser_provider_declared`, `provider_warning`.
- **C7:** preferência=chatgpt → passo do ChatGPT na copy; status nomeia o declarado.
- **Extensão:** `content.test.js` — resposta inclui `provider` canônico conforme o host dirigido.
- **PII (invariante):** com `ai_browser_provider="chatgpt"`, o caminho de browser ainda de-identifica fail-closed (`allow_partial=False`); prompt cru nunca sai.

## Escopo da extensão (mudança mínima EM escopo)

A extensão em `docs/browser-extension/` é código real com testes (vitest) e já detecta o provedor internamente (`providerFor(host)` em `selectors.js`). A mudança de contrato é mínima e entra neste recorte:

- `content.js` (~linha 155): incluir `provider` no objeto de resposta (`"claude"` ou `"chatgpt"`, derivado do host que `providerFor` casou).
- Teste correspondente em `content.test.js`.

Sem isso o C4/C6 ficariam com contrato de servidor pronto porém inerte — o aviso de divergência só funcionaria após um update futuro da extensão. Incluir a mudança mínima evita esse estado zumbi. Todo o resto da extensão (seletores, robustez de automação, blockers) permanece fora deste recorte.

## Migração / compatibilidade do rename (hipótese verificada, não assumida)

- `claude_browser` (valor do enum) tem hoje 3 referências no código (`llm_router.py:72,105` + `tests/unit/test_llm_router.py:101`) e **não** é persistido por nenhum caminho conhecido. O plano de implementação DEVE reconfirmar com `rg "claude_browser|CLAUDE_BROWSER"` no momento da execução.
- Rótulos **de exibição** legados (ex.: `"claude.ai (browser session)"`) podem existir em manifests/audits antigos via campos de modelo. **Logs antigos não serão migrados** — são registro histórico fiel. `normalize_browser_provider` trata rótulos legados de UI como não-canônicos (→ `None`), nunca tenta adivinhar provider a partir deles.

## Fora de escopo (YAGNI)

- Backend de API da OpenAI (`src/juris/llm/openai.py`, `openai_api_key`, provider `OPENAI`).
- Preferência por-tenant (fase multi-tenant; hoje é Settings/env, um valor por deploy).
- Robustez/seletores/anti-bloqueio da extensão Chrome (só a mudança mínima de contrato acima entra).
- Store persistente de "último provedor visto" para o status (divergência é por-run).
- Migração de logs/manifests antigos.

## Riscos herdados (ADR-0018, registrados)

- **ToS.** Dirigir sessão logada do ChatGPT por automação pode conflitar com o ToS da OpenAI (mesmo risco do Claude browser; menor para uso próprio do escritório). A extensão deve degradar graciosamente para o fallback local.
- **Sem DPA** em plano consumidor: a postura LGPD repousa sobre de-id + opt-out de treino, não contrato — aceitável no piloto, revisitar em multi-tenant.
- **Fragilidade** de automação de UI: a extensão precisa falhar visível e cair para o local.
