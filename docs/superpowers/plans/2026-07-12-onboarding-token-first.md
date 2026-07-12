# Onboarding Token-First + Loop de Valor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar tarefa a tarefa. Steps usam checkbox (`- [ ]`).

**Goal:** Levar o CAUSIA à jornada-norte "sem cadastro, espeta o token e já carrega processos + insights": destravar o funil (release do agente), reduzir o setup do agente a "PIN + senha PJe" com CPF lido do próprio token, tornar o resultado gerado reabrível/honesto, e dar caminho de conversão dentro do produto.

**Architecture:** Console web SPA (`index.html` único) + FastAPI (`web/app.py`) + agente local FastAPI (`api/local_agent.py`) que guarda credenciais e fala PKCS#11 com o token A3. O manifesto de release (Ed25519) é servido por `/api/agent/latest` lendo `~/juris-pilot/agent-dist/agent-latest.json` no Mac Mini. Artefatos de run ficam em `<out>/<cnj>/` por tenant com `run-manifest.json` (já contém `succeeded/degraded/degradation_reason/errors`).

**Tech Stack:** Python 3.12, `uv`, FastAPI, pydantic, PKCS#11 (`python-pkcs11` via extra `agent`), vanilla JS no `index.html`, pytest.

## Global Constraints

- **Gates de CI (verdes em toda task):** `uv run ruff check src/juris tests scripts/scan_secrets.py` · `uv run mypy src/juris` · `uv run pytest tests/unit -q`.
- **Copy honesta (pinada por teste):** NUNCA escrever "criptografado em repouso" nem "nunca saem do seu computador". Aprovado: "isolados por escritório e apagáveis com certificado". Promessa de credencial: "Suas senhas e o PIN ficam neste computador e não são enviados aos servidores do Causia" — só onde for verdade (agente local).
- **PIN/senha nunca saem do agente local**; nenhum campo novo de credencial em formulário do site (split-trust, ADR-0015/0016).
- **Isolamento por tenant** em toda rota/consulta nova; caminhos de artefato sempre validados dentro do diretório do tenant (padrão de `/api/filing/artifacts/content`, app.py:1344-1375).
- **Sem jargão para o advogado:** nada de "LLM", "grounding", "manifest", "fixture", códigos de evento crus em texto visível; usar/estender `SOURCE_LABELS`/`GROUNDING_LABELS` (index.html:2756-2758).
- CSP faz hash dos scripts inline no boot → reiniciar o server ao testar mudanças no `index.html`.
- Testes de UI = pins de conteúdo/contrato no HTML/JS via `tests/unit/web/test_app.py`-style (fetch da página, assert de strings/estrutura) + testes de endpoint.
- Trial em dev grava `config/tenants.json` no cwd → quarentenar após testes manuais.
- Commits `type(scope): assunto` + trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## Trilha 0 — Destravamento operacional (gated: exige OK/ação do dono)

Estas 3 tarefas não são TDD; são operação com verificação explícita. Sem elas o funil não existe. **Nenhuma execução sem confirmação do dono em cada uma.**

### Task 0.1: Liberar disco no Mac Mini (1,1 GiB livres hoje)

**Onde:** Mac Mini (`raphaellages@100.77.76.64`).

- [ ] **Step 1 (medir):** `df -h /` e `du -sh ~/Library/Caches ~/.cache ~/projects/_worktrees ~/projects/*/.venv ~/projects/*/node_modules 2>/dev/null | sort -rh | head -15` — apresentar o mapa ao dono.
- [ ] **Step 2 (limpar caches — seguros por natureza, mas só com OK):**
  ```bash
  brew cleanup --prune=all
  uv cache clean
  npm cache clean --force
  # cache HuggingFace (rebaixável; modelos são re-baixáveis):
  du -sh ~/.cache/huggingface 2>/dev/null && rm -rf ~/.cache/huggingface/hub/models--*  # listar antes, confirmar itens
  ```
- [ ] **Step 3 (candidatos a quarentena, NUNCA rm):** `.venv`/`node_modules` de projetos arquivados (`_desktop-archive`, `_quarantine` antigos) → mover para `~/Quarantine-disk-2026-07-12/` preservando caminho relativo; listar antes e confirmar com o dono.
- [ ] **Step 4 (verificar):** `df -h /` — meta: ≥ 20 GiB livres. Registrar antes/depois em `~/projects/_ops/remote-workflow.md`.

### Task 0.2: Publicar a primeira release do agente (funil está 404)

**Contexto:** `.github/workflows/agent-release.yml` dispara por tag `agent-v*`, faz PyInstaller (macOS dmg + Windows zip), assina `agent-latest.json` (Ed25519) e publica via `softprops/action-gh-release`. **`gh secret list` está vazio** — o passo humano único nunca foi feito.

- [ ] **Step 1 (humano, dono ou operador com o cofre):** gerar par Ed25519 offline e registrar secrets, exatamente como documentado no cabeçalho do workflow (linhas 1-24):
  ```bash
  uv run python -c "<snippet do cabeçalho do workflow>" > /tmp/pub.pem  # imprime a pública; grava a privada em agent_update_priv.pem
  gh secret set AGENT_UPDATE_PRIVKEY < agent_update_priv.pem
  gh secret set AGENT_UPDATE_PUBKEY < /tmp/pub.pem
  # apagar agent_update_priv.pem localmente após guardar em cofre
  ```
- [ ] **Step 2:** taggear e publicar: `git tag agent-v2026.7.13.1 && git push origin agent-v2026.7.13.1`; acompanhar `gh run watch`.
- [ ] **Step 3 (verificar):** `gh release view agent-v2026.7.13.1` lista `CausiaAgente.dmg`, `CausiaAgente-windows.zip`, `agent-latest.json`; `curl -I https://github.com/floripasurf/juris/releases/latest/download/CausiaAgente.dmg` → 200/302.
- [ ] **Step 4:** baixar o .dmg num Mac limpo e validar o LEIA-ME/Gatekeeper descrito em `packaging/agent/LEIA-ME.txt`.

### Task 0.3: Manifesto no Mini → `/api/agent/latest` deixa de ser 404

- [ ] **Step 1:** no Mini: `mkdir -p ~/juris-pilot/agent-dist && curl -fsSL https://github.com/floripasurf/juris/releases/latest/download/agent-latest.json -o ~/juris-pilot/agent-dist/agent-latest.json`.
- [ ] **Step 2 (verificar):** `curl -fsS https://causia.com.br/api/agent/latest | head -c 200` → JSON do manifesto.
- [ ] **Step 3:** documentar no runbook (`_ops/remote-workflow.md`): a cada release, repetir o Step 1 (ou automatizar num job launchd depois — fora deste plano).

---

## Trilha 1 — Onboarding token-first ("espeta o token")

### Task 1: Endpoint `/token-info` no agente local (CPF/nome lidos do e-CPF)

**Files:**
- Modify: `src/juris/api/local_agent.py`
- Test: `tests/unit/signing/test_local_agent.py` (arquivo existente dos testes do agente)

**Interfaces:**
- Consome: o probe de token já usado por `agent_health` (`_default_token_probe()` → status com `connected`, `cert_valid_until`; `src/juris/mni/token.py` já expõe `subject` e `cpf` parseado do e-CPF).
- Produz: `GET /token-info` (loopback-only, mesma guarda `_assert_browser_agent_request` dos endpoints `/setup`/`/credentials`) → `{"connected": bool, "cpf": str|null, "titular": str|null, "cert_valid_until": str|null}`. `titular` = CN do subject sem o sufixo de CPF; **nunca** retornar PIN/senha/segredos.

- [ ] **Step 1: teste falho**

```python
def test_token_info_retorna_cpf_do_certificado(monkeypatch) -> None:
    from juris.api import local_agent

    class FakeStatus:
        connected = True
        cert_valid_until = "2027-01-01"
        subject = "CN=FULANO DE TAL:12345678900,OU=e-CPF"
        cpf = "12345678900"

    client = _local_client(monkeypatch)  # helper existente do arquivo p/ requests loopback
    monkeypatch.setattr(local_agent, "_default_token_probe", lambda: FakeStatus())
    resp = client.get("/token-info")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is True
    assert body["cpf"] == "12345678900"
    assert body["titular"] == "FULANO DE TAL"
    assert "pin" not in {k.lower() for k in body}


def test_token_info_sem_token_conectado(monkeypatch) -> None:
    from juris.api import local_agent

    class FakeStatus:
        connected = False
        cert_valid_until = None
        subject = None
        cpf = None

    client = _local_client(monkeypatch)
    monkeypatch.setattr(local_agent, "_default_token_probe", lambda: FakeStatus())
    body = client.get("/token-info").json()
    assert body == {"connected": False, "cpf": None, "titular": None, "cert_valid_until": None}
```

Run: `uv run pytest tests/unit/signing/test_local_agent.py -k token_info -v` → FAIL (404).

- [ ] **Step 2: implementar**

```python
def _titular_from_subject(subject: str | None, cpf: str | None) -> str | None:
    """Nome do titular a partir do CN do e-CPF (formato 'CN=NOME:CPF,...')."""
    if not subject:
        return None
    for part in subject.split(","):
        part = part.strip()
        if part.upper().startswith("CN="):
            cn = part[3:]
            if cpf and cn.endswith(f":{cpf}"):
                cn = cn[: -(len(cpf) + 1)]
            return cn.strip() or None
    return None


@app.get("/token-info")
def token_info(request: Request) -> dict[str, object]:
    """CPF/titular lidos do token conectado — para pré-preencher o setup local."""
    _assert_browser_agent_request(request)
    status = _default_token_probe()
    cpf = getattr(status, "cpf", None)
    return {
        "connected": bool(status.connected),
        "cpf": cpf,
        "titular": _titular_from_subject(getattr(status, "subject", None), cpf),
        "cert_valid_until": getattr(status, "cert_valid_until", None),
    }
```

(Ajustar o acesso aos campos ao dataclass real de `mni/token.py` — o implementador deve ler a classe e usar os nomes exatos; se o probe atual não propagar `subject`/`cpf`, estendê-lo para incluir ambos.)

- [ ] **Step 3:** rodar os 2 testes → PASS; suíte do agente inteira → PASS.
- [ ] **Step 4: Commit** `feat(agent): /token-info lê CPF e titular do e-CPF para setup token-first`

### Task 2: Setup do agente pré-preenchido pelo token (só PIN + senha PJe)

**Files:**
- Modify: `src/juris/api/local_agent.py` (HTML/JS da página de setup, ~linhas 280-330)
- Test: `tests/unit/signing/test_local_agent.py`

**Interfaces:** consome `GET /token-info` (Task 1). O form continua postando cpf/senha/pin para `/credentials` — só muda como o CPF é obtido.

- [ ] **Step 1: teste falho (pins de conteúdo da página de setup)**

```python
def test_setup_page_prefill_token_first(monkeypatch) -> None:
    client = _local_client(monkeypatch)
    html = client.get("/setup").text
    assert "token-status" in html                     # área de status do token
    assert "/token-info" in html                      # JS consulta o agente
    assert "Token detectado" in html                  # copy de sucesso
    assert "Conecte o token A3 nesta máquina" in html  # copy de ausência
    assert 'name="cpf"' in html                       # campo continua existindo (readonly qdo detectado)
```

- [ ] **Step 2: implementar no HTML/JS da página de setup:**
  - Ao carregar, `fetch('/token-info')`. Se `connected`: preencher `cpf` (e marcar `readOnly = true`), mostrar banner `Token detectado: <titular> · certificado válido até <data>`, focar o campo PIN.
  - Se não conectado: banner âmbar `Conecte o token A3 nesta máquina e recarregue a página. Sem o token, informe o CPF manualmente.` (campo cpf editável — fallback preservado).
  - Ordem visual dos campos passa a ser: status do token → PIN → senha PJe → (cpf readonly no rodapé do form).
- [ ] **Step 3:** testes → PASS. Teste manual: `uv run juris agent serve` local, abrir `http://127.0.0.1:8765/setup`.
- [ ] **Step 4: Commit** `feat(agent): setup token-first — CPF pré-preenchido do certificado, foco em PIN+senha`

### Task 3: Primeira sincronização automática após salvar credenciais

**Files:**
- Modify: `src/juris/api/local_agent.py` (handler de `/credentials`, ~linha 237)
- Test: `tests/unit/signing/test_local_agent.py`

**Interfaces:** hoje, após salvar credenciais, o advogado precisa voltar ao console e clicar "Conectar / sincronizar". Nova resposta de `/credentials`: `{"ok": true, "sync": "started"|"skipped"}`; a página de setup mostra "Credenciais salvas. Sincronizando seus processos — acompanhe no Causia (aba Acervo)." com link para o console.

- [ ] **Step 1: teste falho** — postar credenciais válidas com um `sync_trigger` fake injetado (monkeypatch em `local_agent._trigger_first_sync`) e assertar que foi chamado 1x com o cpf salvo e que a resposta contém `"sync": "started"`. Segundo teste: falha no trigger NÃO falha o save (`"sync": "skipped"`, credenciais persistidas mesmo assim).
- [ ] **Step 2: implementar** `_trigger_first_sync(cpf: str) -> bool`: dispara em thread daemon o mesmo caminho de sync usado pelo fluxo connect existente do agente (o implementador localiza a função de sync/connect já existente no agente/CLI — `grep -n "sync" src/juris/api/local_agent.py src/juris/cli/commands/agent.py`); captura exceções específicas, loga `agent_first_sync_failed` e retorna False (nunca propaga para o save).
- [ ] **Step 3:** página de setup: no sucesso do POST, trocar o form pela mensagem de conclusão + link `https://causia.com.br` (ou origin salvo do pareamento).
- [ ] **Step 4:** gates + **Commit** `feat(agent): primeira sincronização dispara sozinha após salvar credenciais`

### Task 4: Console — Acervo guia a instalação quando não há agente

**Files:**
- Modify: `src/juris/web/static/index.html` (seção Acervo, guia "Primeiro acesso", ~linhas 1253-1300)
- Test: `tests/unit/web/test_app.py`

- [ ] **Step 1: teste falho (pins):** página do console contém, na seção Acervo: `id="agent-cta"`, o texto `Baixar o Causia Agent`, e o guia numerado com o download como **passo 1** (antes de credenciais). O link de download usa `/api/agent/latest`-aware copy: `href` continua o do GitHub releases (já corrigido pela Trilha 0), e o texto pequeno "Ainda não instalou?" some.
- [ ] **Step 2: implementar:** reordenar o guia: 1) **Baixar e abrir o Causia Agent** (botão primário, macOS/Windows) → 2) Espete o token e abra o agente (o CPF é lido do certificado; você informa só PIN e senha PJe) → 3) Sincronizar (automático ao salvar; botão "Conectar/sincronizar" vira "Sincronizar novamente"). Esconder o guia quando `processosCache.length > 0` (fix do achado ux-code #12).
- [ ] **Step 3:** gates + **Commit** `feat(web): Acervo guia download-primeiro e esconde o guia quando o acervo já existe`

---

## Trilha 2 — Loop de valor (resultado acessível, honesto, persistente)

### Task 5: Artefatos reabríveis a partir da Mesa

**Files:**
- Modify: `src/juris/web/app.py` (workbench, ~linha 1038) — incluir, por artefato recente, a lista de arquivos disponíveis
- Modify: `src/juris/web/static/index.html` (card "Artefatos recentes" ~2900s; reusar o viewer de artefatos do Novo caso)
- Test: `tests/unit/web/test_app.py`

**Interfaces:**
- Backend: o card do workbench passa a incluir `"files": [{"name": "rascunho-pesquisa.md"}, ...]` (nomes vindos do diretório do run, mesmo código de listagem de `filing_artifacts`).
- Frontend: clicar num arquivo do card chama o endpoint **já existente** `POST /api/filing/artifacts/content` (app.py:1344 — validação de path inclusa) e renderiza no mesmo painel/modal de artefatos do Novo caso. Remover o botão "copiar caminho" (caminho de servidor é inútil no browser); manter "auditoria".

- [ ] **Step 1: teste falho (backend):** criar um run-manifest + 2 artefatos num tenant dir de teste; `GET /api/workbench` retorna o artefato recente com `files` contendo os 2 nomes e SEM o campo de caminho absoluto do servidor.
- [ ] **Step 2: implementar backend** (reusar a listagem de `filing_console.filing_artifacts`; nunca expor path absoluto — só `name`).
- [ ] **Step 3: teste falho (pins de UI):** HTML contém `data-artifact-open` no card e NÃO contém `copiar caminho`.
- [ ] **Step 4: implementar frontend:** cada `file.name` vira botão com rótulo amigável (ver Task 7) que abre o conteúdo via `/api/filing/artifacts/content` no viewer existente.
- [ ] **Step 5:** gates + **Commit** `feat(web): artefatos recentes abrem direto da Mesa (fim do copiar-caminho)`

### Task 6: Run persistente entre abas + indicador global honesto

**Files:**
- Modify: `src/juris/web/static/index.html` (fluxo `createDemoRun`/painel de resultado, ~2560-2700)
- Test: `tests/unit/web/test_app.py` (pins)

Sem mudança de backend (o POST síncrono permanece). Toda a persistência é client-side e honesta:

- [ ] **Step 1: teste falho (pins):** HTML contém `id="run-indicator"` (chip global no header) e os textos `Gerando minuta — pode levar alguns minutos` e `Ver resultado`.
- [ ] **Step 2: implementar:**
  - Estado global `activeRun = {status: 'running'|'done'|'error', startedAt, cnj, resultHtmlCacheKey}` em variável de módulo (não sessionStorage — morre com a aba, o que é correto).
  - Chip no header (ao lado de "IA: local"): `⏳ Gerando (2:31)` com timer decorrido; ao concluir vira `✓ Resultado pronto — Ver` (clicável → volta ao painel); em erro, `⚠ Falha na geração — Ver detalhes`.
  - O painel de resultado renderiza do cache `activeRun` ao reentrar na aba Novo caso (não re-dispara o POST).
  - O `finally` do fetch atualiza o chip mesmo se o usuário estiver noutra aba.
- [ ] **Step 3:** gates + verificação manual (iniciar run → trocar de aba → voltar). **Commit** `feat(web): run em andamento persiste entre abas com indicador global e timer`

### Task 7: Honestidade do resultado degradado + rótulos amigáveis de artefato

**Files:**
- Modify: `src/juris/web/app.py` (workbench: propagar `degraded`/`degradation_reason`/`succeeded` do run-manifest — campos JÁ gravados, artifacts.py:349-352)
- Modify: `src/juris/web/static/index.html`
- Test: `tests/unit/web/test_app.py`

- [ ] **Step 1: teste falho (backend):** manifest com `degraded: true, degradation_reason: "..."` → `GET /api/workbench` inclui `"degraded": true, "degradation_reason": "..."` no artefato recente.
- [ ] **Step 2: teste falho (UI pins):** HTML contém `ARTIFACT_LABELS` e `Minuta não gerada` e NÃO contém regressão dos jargões: `run-manifest.json` como rótulo visível de aba.
- [ ] **Step 3: implementar:**
  - **Card da Mesa:** quando `degraded`, badge âmbar `Minuta não gerada — <motivo em linguagem de advogado>` no lugar de "revisão sem apontamentos". O motivo usa o `degradation_reason` (já escrito em linguagem de advogado pelo orchestrator desde 3f544bf).
  - **Painel de resultado:** banner equivalente no topo quando degradado.
  - **Rótulos de abas de artefato:** dicionário `ARTIFACT_LABELS = {"rascunho-pesquisa.md": "Rascunho de pesquisa", "draft.md": "Minuta", "prazos.md": "Prazos", "resumo.md": "Resumo do caso", "reviewer-report.md": "Revisão", "audit-summary.md": "Auditoria", "run-manifest.json": "Dados técnicos", "audit.jsonl": "Trilha técnica"}` aplicado em `tab.textContent` (index.html:2676) e nos botões da Task 5; nomes fora do dicionário caem no nome do arquivo.
- [ ] **Step 4:** gates + **Commit** `fix(web): resultado degradado é dito com todas as letras; artefatos com nomes de gente`

### Task 8: Auditoria em linguagem humana

**Files:**
- Modify: `src/juris/web/static/index.html` (modal de auditoria, ~1980-2050)
- Test: `tests/unit/web/test_app.py`

- [ ] **Step 1: teste falho (pins):** HTML contém `AUDIT_EVENT_LABELS` e `Início da geração` e não exibe `DEMO.STARTED` cru.
- [ ] **Step 2: implementar:** dicionário `AUDIT_EVENT_LABELS = {"demo.started": "Início da geração", "draft.context_built": "Leitura do processo", "draft.thesis_chosen": "Definição da tese", "research": "Pesquisa de jurisprudência", "draft.template_scaffold": "Estrutura da peça", "draft.reviewed": "Revisão automática", "draft.blocked": "Minuta bloqueada", "demo.finished": "Fim da geração"}`; eventos desconhecidos mostram o código original em `<code>` discreto. `llm:qwen3:8b` → `IA local (qwen3)` via mapeamento simples do prefixo. Manter "✓ Cadeia íntegra" mas com subtítulo: `Integridade do registro — não indica sucesso da minuta`.
- [ ] **Step 3:** gates + **Commit** `fix(web): auditoria legível por advogado (eventos e modelo com rótulos)`

---

## Trilha 3 — Conversão dentro do produto

> **CHECKPOINT DO DONO (antes das Tasks 9-10):** confirmar (a) faixa de preço pública — proposta abaixo usa a de `docs/pilot/pilot-terms-pt.md:114-122`; (b) identidade a exibir (nome/OAB do responsável); (c) canal: WhatsApp (número) e/ou e-mail em domínio próprio (`contato@causia.com.br`). Sem confirmação, as tasks 9-10 NÃO devem ser executadas com os valores-proposta.

### Task 9: Tela "Contratar" dentro do console (fim do mailto cru)

**Files:**
- Modify: `src/juris/web/static/index.html` (chip `Teste: 30 dias · Contratar`, ~2170-2200)
- Test: `tests/unit/web/test_app.py`

- [ ] **Step 1: teste falho (pins):** HTML contém `id="contratar-modal"`, `Plano piloto`, `R$` e o chip não é mais um `<a href="mailto:...>` direto.
- [ ] **Step 2: implementar:** clique no chip abre modal (mesmo padrão de focus-trap dos modais existentes) com: faixa de preço (proposta: `Piloto: R$ 1.500–3.000/mês por escritório, ou R$ 300–500 por petição — valores fechados na conversa`), o que está incluído (3 bullets da mesa/prazos/minutas), e dois botões: `Chamar no WhatsApp` (link `https://wa.me/<numero-confirmado>?text=Quero%20contratar%20o%20Causia`) e `Enviar e-mail` (mailto para o endereço confirmado — fallback, não protagonista). Registrar clique em audit local (`contratar.opened`) para métrica do piloto.
- [ ] **Step 3:** gates + **Commit** `feat(web): tela Contratar com preço e WhatsApp dentro do produto`

### Task 10: Preço + identidade na landing

**Files:**
- Modify: `src/juris/web/static/index.html` (seção "Uma mesa de trabalho...", ~1178-1195, e rodapé ~1196-1210)
- Test: `tests/unit/web/test_app.py`

- [ ] **Step 1: teste falho (pins):** landing contém `R$` na seção de plano e o rodapé contém `OAB` e não contém `lages.raphael@gmail.com` visível como contato principal.
- [ ] **Step 2: implementar:** no bloco "30 dias gratuitos", acrescentar card `Depois do teste` com a faixa confirmada + "sem fidelidade durante o piloto". Rodapé: `Causia · <Nome do responsável confirmado> — OAB/<UF confirmada> <número> · contato@causia.com.br` (e-mail de domínio próprio com redirect — configurar no provedor DNS é passo do dono, fora do repo).
- [ ] **Step 3:** gates + **Commit** `feat(web): preço e identidade na landing (fim da objeção silenciosa)`

### Task 11: Cobertura de tribunais declarada + fix onboarding

**Files:**
- Modify: `src/juris/web/static/index.html` (seção "Nossa tecnologia", ~1160-1177; campo Tribunal do Novo caso, ~1601)
- Modify: `docs/pilot/onboarding.md` (linha 18 — remove `tjsp` do exemplo)
- Test: `tests/unit/web/test_app.py`

- [ ] **Step 1: teste falho (pins):** landing contém `Tribunais atendidos hoje` e `TST`; Novo caso usa `<select id="tribunal">` com `<option value="tjmg">TJ de Minas Gerais (TJMG)</option>` (não input texto livre); onboarding.md não contém `tjsp`.
- [ ] **Step 2: implementar:** lista visível na landing derivada do registro real (`src/juris/mni/tribunais.py` — 13 tribunais; escrever a lista estática com nomes por extenso e nota "cobertura em expansão; seu tribunal não está aqui? fale com a gente"). Campo Tribunal vira `<select>` com os mesmos 13 + opção "outro (me avise)". Corrigir o exemplo do onboarding.md.
- [ ] **Step 3:** gates + **Commit** `fix(web): cobertura de tribunais declarada e seleção por nome (fim do código interno)`

### Task 12: E-mail opcional para expiração/recuperação do teste

**Files:**
- Modify: `src/juris/web/app.py` (novo `POST /api/trial/contact`, rate-limited como expensive)
- Modify: `src/juris/web/trial_access.py` (persistir `contact_email` opcional no registro do trial; validação de formato; NUNCA obrigatório)
- Modify: `src/juris/web/static/index.html` (card de boas-vindas do trial: campo opcional "Quer um aviso antes de expirar? (e-mail, opcional)")
- Test: `tests/unit/web/test_trial_access.py`, `tests/unit/web/test_app.py`

- [ ] **Step 1: teste falho:** `POST /api/trial/contact {"email": "a@b.com"}` autenticado grava o e-mail no registro do tenant do trial; e-mail inválido → 422; sem auth → 401; o card de boas-vindas contém `opcional` e `avisar antes de expirar`.
- [ ] **Step 2: implementar** (armazenamento + UI). O envio do aviso em si usa a infra SMTP existente (`config.py:106-109`) num job — **fora deste plano** (registrar em `docs/engineering_sprints.md` como follow-up "job de aviso de expiração"); o valor imediato é a recuperação assistida (operador consegue reenviar a chave a quem pediu).
- [ ] **Step 3:** gates + **Commit** `feat(web): e-mail opcional no trial para aviso de expiração e recuperação`

---

## Trilha 4 — Polish de confiança e clareza

### Task 13: Retry nos carregamentos + empty states orientadores

**Files:**
- Modify: `src/juris/web/static/index.html` (`showView` ~2231, mensagens de erro ~3273/3386, `renderPrazos` ~3237)
- Test: `tests/unit/web/test_app.py`

- [ ] **Step 1: teste falho (pins):** HTML contém `data-retry` e `Tentar novamente`; e a Agenda vazia com acervo vazio contém `Conecte seu acervo`.
- [ ] **Step 2: implementar:** (a) todo estado "Não foi possível carregar..." ganha botão `Tentar novamente` que re-invoca o `load*()` da seção; (b) `showView(name)` re-dispara o `load*()` da seção se o último load falhou; (c) Agenda vazia: se `processosCache` também vazio → "Sem prazos porque nenhum processo foi conectado ainda. **Conecte seu acervo** →" (link para Acervo); senão → "Nenhum prazo pendente — tudo em dia."
- [ ] **Step 3:** gates + **Commit** `fix(web): erro de carregamento tem retry e vazios explicam o próximo passo`

### Task 14: De-jargonização dos 6 textos + hashes explicados

**Files:**
- Modify: `src/juris/web/static/index.html`
- Test: `tests/unit/web/test_app.py` (pins de presença dos novos textos e ausência dos antigos)

Trocas exatas (achados ux-code #3-#5, evidência por linha):
- [ ] 1565 `Override de prazo` → `Ajustar prazo manualmente (uso excepcional)`
- [ ] 2565 `Ajuste os dados ou o provedor LLM e tente novamente.` → `Confira o número do processo e tente novamente. Se o erro continuar, verifique a conexão da IA na aba Acessos.`
- [ ] 1991 `audit.jsonl não encontrado` → `Este caso ainda não tem trilha de auditoria.`
- [ ] 2034 fallback `"grounding falhou"` → `"citações não confirmadas"`
- [ ] 3606 `signed hash:` → `hash do assinado:`
- [ ] 3573-3653: adicionar nota única acima da cadeia de custódia: `Códigos abaixo são impressões digitais dos arquivos — comprovam que nada foi alterado depois da assinatura.`
- [ ] 1979 `Vice-campeãs` → `Teses alternativas`
- [ ] Gates + **Commit** `fix(web): linguagem de advogado nos textos que vazavam engenharia`

### Task 15: Formulários — máscara CNJ, labels, autocomplete, defaults seguros

**Files:**
- Modify: `src/juris/web/static/index.html`
- Test: `tests/unit/web/test_app.py`

- [ ] **Step 1: teste falho (pins):** campo `numero_cnj` sem `value=` fixo e com `placeholder="0000000-00.0000.0.00.0000"` + `pattern`; `#library-area` tem `<label>`; `fl_senha` tem `autocomplete="current-password"`.
- [ ] **Step 2: implementar:**
  - CNJ: `pattern="\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}"` + `title="Número CNJ completo, ex.: 0001234-56.2026.8.13.0001"` nos 4 campos de CNJ (1586, 1511, 1386, 1292); validação inline no `submit` com mensagem `Número CNJ incompleto — confira os 20 dígitos.`; o Novo caso troca `value="0001234-..."` por `placeholder` (o fluxo "Explorar com dados de exemplo" continua pré-preenchendo via JS — comportamento atual preservado).
  - Labels: `<label class="visually-hidden">` para `#library-area`, `#library-search-form`, `#access-key-form`, filtros 1302/1316 (criar a classe `.visually-hidden` se não existir).
  - `autocomplete`: alinhar `fl_cpf`→`username`, `fl_senha`→`current-password` (1542/1551 e retry 3645/3647).
  - Selects gêmeos do Protocolo (1521-1537): nota de ajuda sob "Tipo de documento": `Documento = o que vai no sistema do tribunal; Petição = a natureza jurídica da peça. Na dúvida, use o mesmo valor.`
- [ ] **Step 3:** gates + **Commit** `fix(web): CNJ validado, labels acessíveis, senha lembrável e defaults seguros`

### Task 16: Contraste AA + urgência com texto (não só cor)

**Files:**
- Modify: `src/juris/web/static/index.html` (`--muted` linha 22; badges 556-560 e 3253)
- Test: `tests/unit/web/test_app.py`

- [ ] **Step 1: teste falho (pins):** CSS contém `--muted: #5F6169` e o HTML de prazo contém `aria-label` com `urgência`.
- [ ] **Step 2:** trocar `--muted: #7A7D85` → `#5F6169`; badges de prazo ganham prefixo textual (`alta · 15/08`, `média · ...`) e `aria-label="urgência alta, vence em 15/08/2026"`.
- [ ] **Step 3:** gates + **Commit** `fix(web): contraste AA no texto secundário e urgência legível sem cor`

---

## Ordem de execução e dependências

```
Trilha 0 (0.1 → 0.2 → 0.3)  [gated: dono]  ──┐
Trilha 1 (1 → 2 → 3 → 4)                      ├─ 1 e 2 podem correr em paralelo à Trilha 0
Trilha 2 (5 → 6 → 7 → 8)                      │  (código não depende da release)
Trilha 3 (9 → 10 em CHECKPOINT; 11; 12)       │
Trilha 4 (13 → 14 → 15 → 16)  qualquer ordem ─┘
```

Prioridade de valor: **0.2/0.3 (funil vivo) → 5/7 (valor visível e honesto) → 1-4 (token-first) → 13 → 9/10 (após checkpoint) → resto.**

## Fora de escopo (registrado, não esquecido)

- Progresso por etapas real do run (SSE/job assíncrono) — o indicador honesto da Task 6 cobre o essencial; etapas reais exigem re-arquitetar `/api/demo-runs`.
- Job de envio do aviso de expiração (SMTP) — Task 12 só captura o e-mail.
- Integração TJSP/expansão MNI — épica própria.
- Automatizar a cópia do `agent-latest.json` para o Mini a cada release (launchd) — follow-up de ops.

## Self-review (checklist do autor)

- Cobertura: os 10 itens do top de alavancagem do audit têm task (disco=0.1, release=0.2/0.3, artefatos reabríveis=5, honestidade=7, preço=10, identidade=10, retry/vazios=13, progresso=6, jargão=8/14, e-mail=12) + token-first (1-4) que é a visão do dono. ✓
- Sem placeholders: código concreto nas tasks 1, 5-8, 14-16; especificação exata + fonte nas demais; valores de preço/OAB/WhatsApp marcados como CHECKPOINT explícito do dono (não placeholders silenciosos). ✓
- Tipos/nomes consistentes: `/token-info` (agente), `ARTIFACT_LABELS`/`AUDIT_EVENT_LABELS` (UI), `files[].name` no workbench. ✓
- Riscos apontados: acesso a campos reais de `TokenStatus` (Task 1, instrução de verificação), localização da função de sync (Task 3, instrução de grep). ✓
