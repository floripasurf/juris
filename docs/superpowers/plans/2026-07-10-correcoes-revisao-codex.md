# Correções da Revisão Codex — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar tarefa a tarefa. Steps usam checkbox (`- [ ]`).

**Goal:** Corrigir os 9 achados da revisão externa (Codex) do juris/CAUSIA, do mais crítico (busca semântica inativa no runtime piloto) aos de higiene (arquivos grandes), sem regressão nos gates de CI.

**Architecture:** O runtime do piloto é SQLite-first (ADR-0020): `LocalFTSStore` (FTS5) é dense+sparse store, agente local split-trust via WebSocket reverso, deploy single Mac Mini atrás de Cloudflare Tunnel. As correções respeitam essa arquitetura — não reintroduzem Postgres/Qdrant no caminho ativo.

**Tech Stack:** Python 3.12, `uv`, FastAPI, SQLite/FTS5, `sentence-transformers` (BGE-M3, embeddings normalizados), `numpy`, `pytest`, `ruff`, `mypy --strict`.

## Global Constraints

Cada tarefa herda implicitamente:
- **Gates de CI** (todos devem ficar verdes): `uv run ruff check src/juris tests scripts/scan_secrets.py`; `uv run mypy src/juris`; `uv run pytest tests/unit -q`; `uv run --with pip-audit pip-audit --local --strict`.
- **Regras ruff ativas:** E, F, I, N, B, UP, S, A, C4, RET, SIM. Sem `except` nu (especificar tipo); `BLE001` (except Exception amplo) só com `# noqa: BLE001` e justificativa.
- **Sem `print()` para log** — usar `structlog`/`get_logger`. Type hints em toda assinatura. Docstrings Google-style em API pública.
- **Isolamento de tenant é inegociável** — toda query nova carrega `tenant_id`; `tenant_id=None` = só seed público.
- **Determinismo em caminho legal-crítico** — regras de prazo/feriado são baseadas em regras, testáveis, sem LLM.
- **Honestidade de copy** — nunca escrever "criptografado em repouso" nem "nunca sai do seu computador".
- **Testes vivem ao lado da feature**; TDD (teste falha primeiro). Commits pequenos `type(scope): subject`, trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Não commitar/rodar em `config/tenants.json` gerado por teste no cwd (quarentenar se surgir).

---

## Task 1 — Busca semântica real no runtime piloto (Alto, central) [#1]

**Problema:** `web/demo_service.py:432` usa `LocalFTSStore` como dense **e** sparse store. `repertory/retrieval/hybrid.py` computa o embedding da query e chama `self._dense.search(query_embedding, ...)`, mas `repertory/vector_store.py:560` (`LocalFTSStore.search`) **retorna `[]`** e `upsert` (linha 521) **ignora os embeddings** (não há coluna de vetor no schema). Resultado: mesmo com BGE carregado e obrigatório, a recuperação prática é lexical (FTS). Para um produto que fundamenta minutas, o motor semântico precisa existir de fato.

**Decisão de abordagem (recomendada):** persistir os embeddings no próprio SQLite e implementar `search()` como similaridade por produto interno (os embeddings do BGE já são normalizados → cosseno = dot product), varredura densa em `numpy` sobre as linhas visíveis ao tenant. Na escala do piloto (milhares de chunks) isso é <50ms e mantém o piloto SQLite-first. Alternativas rejeitadas para o piloto: `sqlite-vec` (dependência nativa extra) e ativar Qdrant (contraria ADR-0020; fica como caminho de escala futuro, já codado).

**Files:**
- Modify: `src/juris/repertory/vector_store.py` (schema de `chunks` + `upsert` + `search` do `LocalFTSStore`, ~483-578)
- Modify: `src/juris/cli/main.py` (comando de backfill de embeddings, ou reuso do ingest)
- Test: `tests/unit/repertory/test_local_fts_dense.py` (novo)
- Test: `tests/unit/repertory/test_hybrid_dense_ativo.py` (novo — prova hybrid não-lexical-só)

**Interfaces:**
- Consome: `LegalEmbedder.embed_texts`/`embed_single` (retornam vetores normalizados), `DocumentChunk`, `SearchResult`.
- Produz: `LocalFTSStore.search(query_embedding, top_k, tenant_id, *, include_estilo, tenant_only, area) -> list[SearchResult]` agora retorna resultados densos reais; `upsert` persiste embeddings.

- [ ] **Step 1: Teste falho — upsert persiste embedding e search densa recupera o chunk mais próximo**

```python
# tests/unit/repertory/test_local_fts_dense.py
from pathlib import Path

from juris.repertory.chunking import DocumentChunk
from juris.repertory.vector_store import LocalFTSStore


def _chunk(cid: str, texto: str) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=cid, source_id="s1", source_type="acordao", texto=texto,
        titulo="t", tribunal="STJ", hierarquia=3, uso="fundamento",
    )  # ajuste os campos ao DocumentChunk real


def test_dense_search_recupera_por_similaridade(tmp_path: Path) -> None:
    store = LocalFTSStore(tmp_path / "rep.db")
    chunks = [_chunk("a", "honorários advocatícios sucumbenciais"),
              _chunk("b", "prescrição intercorrente tributária")]
    embeddings = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]  # normalizados
    store.upsert(chunks, embeddings, tenant_id=None)

    hits = store.search([0.96, 0.28, 0.0], top_k=1, tenant_id=None)
    assert len(hits) == 1
    assert hits[0].source_id == "s1"
    assert hits[0].chunk_id == "a"  # mais próximo do vetor da query
```

Run: `uv run pytest tests/unit/repertory/test_local_fts_dense.py -v`
Expected: FAIL (`search` retorna `[]`).

- [ ] **Step 2: Migração de schema — coluna `embedding BLOB` idempotente**

No `LocalFTSStore.__init__` (após o `CREATE TABLE chunks`), adicionar migração defensiva para bancos existentes:

```python
# dentro de __init__, após criar a tabela chunks
cols = {row[1] for row in conn.execute("PRAGMA table_info(chunks)")}
if "embedding" not in cols:
    conn.execute("ALTER TABLE chunks ADD COLUMN embedding BLOB")
```

E incluir `embedding BLOB` no `CREATE TABLE IF NOT EXISTS chunks (...)` para bancos novos.

- [ ] **Step 3: `upsert` persiste o embedding (float32 bytes)**

Substituir o comportamento "embeddings ignored for FTS": serializar cada vetor com `numpy` e gravar na coluna nova.

```python
import numpy as np
# ...
def upsert(self, chunks, embeddings, tenant_id=None):
    ...
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        blob = np.asarray(embedding, dtype=np.float32).tobytes() if embedding else None
        # incluir `blob` no INSERT da tabela chunks (coluna embedding)
    ...
```

Manter o índice FTS existente inalterado (sparse continua funcionando).

- [ ] **Step 4: implementar `search(query_embedding)` — dot product sobre linhas visíveis**

Reusar exatamente o mesmo WHERE de visibilidade/uso/área do `search_text` (constantes de módulo, tenant sempre bindado — nunca interpolar), selecionando `embedding` além dos metadados. Decodificar com `np.frombuffer(blob, dtype=np.float32)`, computar `float(q @ v)` (embeddings normalizados), ordenar desc, cortar `top_k`, e montar `SearchResult` com o mesmo mapeamento de campos (source_type/uso/score) que `search_text`. Linhas com `embedding IS NULL` são ignoradas (não indexadas semanticamente ainda).

Run: `uv run pytest tests/unit/repertory/test_local_fts_dense.py -v` → PASS.

- [ ] **Step 5: Teste — hybrid deixa de ser lexical-só**

```python
# tests/unit/repertory/test_hybrid_dense_ativo.py
# Monta HybridRetriever(dense=store, sparse=store, embedder=FakeEmbedder, reranker=None-ish)
# com um FakeEmbedder determinístico, ingere 2 chunks, e assere que uma query
# SEM overlap lexical com o chunk-alvo (só semântico) ainda o recupera —
# provando que o caminho denso contribui, não só o FTS.
```

Run: `uv run pytest tests/unit/repertory/test_hybrid_dense_ativo.py -v` → deve passar só com a busca densa ativa.

- [ ] **Step 6: Backfill dos embeddings do corpus existente**

Adicionar (ou estender) um comando CLI que recomputa embeddings para chunks com `embedding IS NULL` em lote, respeitando `LegalEmbedder` (fail-closed em prod). Documentar no runbook: rodar o backfill uma vez antes de confiar na busca semântica. `juris repertory ingest` re-ingerindo do zero também popula, mas o backfill evita reprocessar texto.

- [ ] **Step 7: Gates + commit**

Run: `uv run ruff check src/juris tests scripts/scan_secrets.py && uv run mypy src/juris && uv run pytest tests/unit -q`
Commit: `fix(retrieval): busca densa real no LocalFTSStore (embeddings persistidos + cosseno) — ativa semântica no piloto`

---

## Task 2 — Feriado nacional 20/11 + expandir calendários estaduais (Alto/Médio) [#3, #8]

**Problema:** `prazo/calendar.py:43` (`feriados_nacionais`) omite o Dia da Consciência Negra (20/11), que a **Lei 14.759/2023** tornou feriado nacional **a partir de 2024** (hoje só existe como estadual do RJ, linha 97). E `prazo/calendar.py:93` cobre ~7 UFs; vários TJs/TRTs ignoram feriados locais. Direção do erro: feriado desconhecido = dia útil → prazo fecha cedo demais (falso alarme), mas mina a confiança.

**Files:**
- Modify: `src/juris/prazo/calendar.py` (`feriados_nacionais` + tabela estadual)
- Test: `tests/unit/test_calendar.py` (ou o arquivo de calendário existente)

**Interfaces:** consome `Feriado`, `TipoFeriado`; nenhuma assinatura muda.

- [ ] **Step 1: Teste falho — 20/11 é nacional a partir de 2024, não antes**

```python
def test_consciencia_negra_nacional_desde_2024(cal) -> None:
    assert cal.is_feriado(date(2024, 11, 20)) is True
    assert cal.is_feriado(date(2025, 11, 20)) is True
    # antes da lei permanece dia útil no plano nacional
    assert cal.is_feriado(date(2023, 11, 20)) is False  # exceto onde já era estadual (RJ)
```

Run: `uv run pytest tests/unit/test_calendar.py -k consciencia -v` → FAIL.

- [ ] **Step 2: Adicionar o feriado nacional condicionado ao ano**

Em `feriados_nacionais(year)`, acrescentar, ao final da lista:

```python
if year >= 2024:  # Lei 14.759/2023
    feriados.append(Feriado(date(year, 11, 20), "Dia da Consciência Negra", TipoFeriado.NACIONAL))
```

Remover a duplicidade estadual do RJ para anos >= 2024 (evitar contagem dupla; nacional já cobre) — ou garantir que a agregação deduplica por data.

Run: `uv run pytest tests/unit/test_calendar.py -k consciencia -v` → PASS.

- [ ] **Step 3: Teste + dados — completar as UFs da carteira ativa**

Escrever teste que assere um feriado estadual conhecido para cada UF adicionada, e preencher a tabela estadual (mínimo: as UFs dos 13 tribunais MNI integrados + TRTs mapeados no `engine._tribunal_to_uf`). Onde a lei estadual for incerta, deixar a UF sem entradas (baseline federal) e registrar no docstring, em vez de adivinhar. Nunca inventar feriado.

- [ ] **Step 4: Gates + commit**

Commit: `fix(prazo): 20/11 (Consciência Negra) como feriado nacional desde 2024 + amplia calendários estaduais`

---

## Task 3 — Permissão 0600 em tenants.json / agents.json (Alto) [#2]

**Problema:** `web/trial_access.py:353` (`_locked_json`) cria/escreve JSONs com `path.open("a+")` sem garantir `0600`. Com umask 022, `tenants.json`/`agents.json` nascem 0644 (legíveis por grupo/outros). `agents.json` guarda token bruto de relay. O padrão seguro já existe no próprio arquivo (linha 331 usa `os.open(..., 0o600)` para o lock), mas o writer de dados não.

**Files:**
- Modify: `src/juris/web/trial_access.py` (`_locked_json` e qualquer outro writer de tenants/agents)
- Test: `tests/unit/web/test_trial_access.py`

- [ ] **Step 1: Teste falho — arquivo recém-criado é 0600**

```python
def test_locked_json_cria_arquivo_0600(tmp_path) -> None:
    from juris.web.trial_access import _locked_json
    p = tmp_path / "tenants.json"
    with _locked_json(p) as data:
        data["x"] = 1
    assert (p.stat().st_mode & 0o777) == 0o600
```

Run: FAIL (nasce 0644 sob umask 022).

- [ ] **Step 2: Garantir 0600 na origem**

Antes de abrir para escrita, criar o arquivo com `os.open(path, os.O_CREAT | os.O_RDWR, 0o600)` (ou `path.touch(mode=0o600)` + `os.chmod` para arquivos já existentes com modo aberto). Aplicar em `_locked_json` e replicar em qualquer writer de `agents.json`. Não afrouxar arquivos já 0600.

Run: PASS. Rodar também os testes de erasure/purge que tocam esses arquivos (`tests/unit/ops/test_erasure.py`, `tests/unit/cli/test_tenant_cmd.py`) para garantir não-regressão.

- [ ] **Step 3: Gates + commit**

Commit: `fix(web): tenants.json/agents.json nascem 0600 (token de relay não fica legível por grupo/outros)`

---

## Task 4 — IP real do cliente atrás de proxy para rate limit (Médio/alto) [#4]

**Problema:** `web/app.py:264, 602, 673` usam `request.client.host` sem normalizar `CF-Connecting-IP`/`X-Forwarded-For`. Atrás do Cloudflare Tunnel, isso vira o IP do proxy → todos os usuários colapsam num IP (rate limit por IP inútil ou agressivo demais). Já existe leitura de `x-forwarded-proto` (linha 165) para o scheme, mas não para o IP do cliente.

**Files:**
- Create: `src/juris/web/client_ip.py` (helper `client_ip(request/ws) -> str`)
- Modify: `src/juris/web/app.py` (trocar os 3+ usos de `request.client.host` pelo helper)
- Modify: `src/juris/config.py` (flag `JURIS_TRUSTED_PROXY` — só confiar no header quando atrás de proxy conhecido)
- Test: `tests/unit/web/test_client_ip.py` (novo)

- [ ] **Step 1: Teste falho — CF-Connecting-IP tem precedência quando proxy confiável**

```python
def test_client_ip_usa_cf_connecting_ip_atras_de_proxy_confiavel():
    # request com client.host = "127.0.0.1" (túnel) e header CF-Connecting-IP = "203.0.113.9"
    assert client_ip(req, trusted_proxy=True) == "203.0.113.9"

def test_client_ip_ignora_header_sem_proxy_confiavel():
    # sem trusted_proxy, headers são spoofáveis → usar client.host
    assert client_ip(req, trusted_proxy=False) == "127.0.0.1"
```

Run: FAIL (helper não existe).

- [ ] **Step 2: Implementar `client_ip`**

Ordem quando `trusted_proxy=True`: `CF-Connecting-IP` → primeiro IP de `X-Forwarded-For` (split por vírgula, strip) → `request.client.host`. Quando `False` (default, para não confiar em header spoofável): sempre `request.client.host`. Validar que o valor extraído parece um IP (senão cai no fallback). Nunca colocar o IP em URL/query.

- [ ] **Step 3: Ligar nos 3 pontos + config**

Trocar `request.client.host` por `client_ip(request, trusted_proxy=settings.trusted_proxy)` nas chaves de rate limit (`invalid:`, `trial:`, `agent-pairing:`) e no WS. `settings.trusted_proxy` lê `JURIS_TRUSTED_PROXY` (default False; ligar em prod no deploy Cloudflare).

Run: `uv run pytest tests/unit/web -q` → todos verdes.

- [ ] **Step 4: Gates + commit**

Commit: `fix(web): rate limit usa CF-Connecting-IP/XFF atrás de proxy confiável (não colapsa usuários no IP do túnel)`

---

## Task 5 — Supervisor de reconexão do relay do agente local (Médio) [#5]

**Problema:** `api/local_agent.py:177` inicia thread daemon; `:821` abre o WebSocket e, se cair, sai. Sem reconexão com backoff, estado visível, nem retomada sem novo pareamento → uma queda de rede derruba o canal reverso até reinício manual.

**Files:**
- Modify: `src/juris/api/local_agent.py` (loop supervisor do WS reverso)
- Test: `tests/unit/api/test_local_agent_relay_supervisor.py` (novo)

- [ ] **Step 1: Teste falho — o supervisor reconecta com backoff após queda**

Testar o loop de reconexão com um fake de conexão que falha N vezes e depois conecta: assere que houve reconexão, que o backoff cresce (limitado por um teto), e que o token/pareamento é reusado (não exige re-pareamento). Usar relógio injetável/`asyncio` fake — sem `sleep` real.

- [ ] **Step 2: Implementar loop supervisor**

Envolver a conexão do WS num loop `while running:` com backoff exponencial com jitter e teto (ex.: 1s→2s→...→30s), reset do backoff após conexão estável por T segundos, log estruturado de estado (`relay_reconnecting`/`relay_connected`), e reuso do token existente. Falhas de conexão capturam exceção específica de rede (não `except Exception` nu). Expor o estado atual (conectado/tentando/desligado) para o `/api/agent-health` já existente.

- [ ] **Step 3: Gates + commit**

Commit: `feat(agent): supervisor de reconexão com backoff no canal reverso (retoma sem novo pareamento)`

---

## Task 6 — Origem www + robustez de onboarding navegador→agente (Médio) [#6]

**Problema:** `api/local_agent.py:40` (`_BROWSER_PAIRING_ORIGINS`) inclui `causia.com.br`/`app.causia.com.br` mas **não** `https://www.causia.com.br`; `web/app.py:190` libera `connect-src` para `127.0.0.1:8765`. Chrome aceita localhost, mas Safari/Edge/PNA podem quebrar o onboarding no host `www`.

**Files:**
- Modify: `src/juris/api/local_agent.py` (allowlist de origem)
- Modify: `src/juris/web/app.py` (CSP connect-src, se o host `www` for canônico)
- Test: `tests/unit/api/test_local_agent.py` (ou o que cobre origem de pareamento)

- [ ] **Step 1: Confirmar o host canônico**

Verificar qual host o site realmente serve em produção (`causia.com.br` vs `www.causia.com.br`) — DNS/deploy. Isso decide se `www` entra na allowlist ou se o correto é redirecionar `www`→apex. **Ponto de decisão para o dono do produto** (não adivinhar): documentar a escolha antes de codar.

- [ ] **Step 2: Teste + fix da allowlist**

Se `www` for válido, adicionar `https://www.causia.com.br` a `_BROWSER_PAIRING_ORIGINS` com teste que assere aceitação da origem `www` e rejeição de origem não-listada.

- [ ] **Step 3 (investigação, não-bloqueante): PNA/CORS cross-browser**

Registrar como follow-up a validação real em Safari/Edge do fluxo Private Network Access (preflight `Access-Control-Request-Private-Network`). Se quebrar, o agente local precisa responder ao preflight PNA com o header apropriado — escopo de investigação própria, fora deste plano mínimo.

- [ ] **Step 4: Gates + commit**

Commit: `fix(agent): aceita origem www.causia.com.br no pareamento navegador→agente`

---

## Task 7 — .env.example alinhado aos contratos de produção (Médio) [#7]

**Problema:** `.env.example:56` não lista flags críticas recentes → risco de deploy incompleto.

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Auditar as flags reais e documentá-las**

Fazer `grep -rhoE "JURIS_[A-Z_]+" src/juris | sort -u` e garantir que o `.env.example` cobre pelo menos: `JURIS_RATE_LIMIT_FAIL_CLOSED`, `JURIS_REQUIRE_EMBEDDINGS`, `JURIS_REQUIRE_TENANTS`, `JURIS_TRIAL_MAX_ACTIVE`, `JURIS_TRIAL_MAX_NEW_PER_DAY`, `JURIS_TRUSTED_PROXY` (nova da Task 4), `JURIS_RATE_LIMIT_REDIS_URL`/broker de relay, caminhos de `tenants.json`/`agents.json`, e `ENVIRONMENT`. Cada uma com comentário de 1 linha (para que serve, default, se é obrigatória em prod). **Nunca** colocar valores reais de segredo — só placeholders.

- [ ] **Step 2: Commit** (sem gate de teste; é doc)

Commit: `docs(env): .env.example cobre flags de produção (rate limit, embeddings, tenants, proxy, broker)`

---

## Task 8 — Quebra incremental de god-files (Baixo/médio, deferível) [#9]

**Problema:** `cli/main.py` ~3381 linhas (48 comandos), `web/app.py` ~1651 (44 rotas), `api/local_agent.py` ~854 — blast radius alto, revisão de segurança e testes focados difíceis. Não é bug; é dívida de manutenibilidade. **Executar por último e só se houver janela** — cada movimento deve ser puramente mecânico e verificado por suíte verde.

**Abordagem (padrão que o projeto já usa em `cli/commands/{agent,doctor,tenant}.py` e `web/{processos,demo}_service.py`):**

- [ ] **Step 1: `cli/main.py` → `cli/commands/*`** — mover grupos de comandos por domínio (repertory, review, draft, demo, signing/filing, cloud) para módulos em `cli/commands/`, registrando via o mesmo mecanismo Typer já usado. Um domínio por commit; rodar `uv run pytest tests/unit/cli -q` após cada.
- [ ] **Step 2: `web/app.py` → routers por domínio** — extrair rotas de filing, corpus, connect, agent-relay, pilot-feedback para `APIRouter` incluídos via `include_router`, sem mudar contratos de rota. Um router por commit; `uv run pytest tests/unit/web -q` após cada.
- [ ] **Step 3:** cada extração é refactor sem mudança de comportamento — nenhum teste novo, mas a suíte inteira deve permanecer verde e o mapa de rotas/comandos idêntico.

Commits: `refactor(cli): move comandos <domínio> para cli/commands/<domínio>.py` / `refactor(web): extrai rotas de <domínio> para router próprio`

---

## Ordem de execução e priorização

1. **Task 1** (Alto, central — o motor de valor) →
2. **Task 3** (Alto, segurança de token) →
3. **Task 2** (Alto/Médio, risco legal de prazo) →
4. **Task 4** (Médio/alto, rate limit em prod) →
5. **Task 5** (Médio, robustez do agente) →
6. **Task 6** e **Task 7** (Médio, onboarding/deploy) →
7. **Task 8** (deferível, higiene).

Tasks 1–4 fecham os riscos reais de produto/segurança/legal e devem ir antes de novos pilotos. Tasks 6 e 8 têm pontos de decisão do dono do produto (host canônico `www`; apetite por refatorar god-files agora) — confirmar antes de executá-las.

## Self-review (checklist do autor)

- Cobertura: cada um dos 9 achados tem tarefa (Tasks 1–8; #3 e #8 juntos na Task 2; #9 na Task 8). ✓
- Sem placeholders vagos: código concreto nas tarefas não-triviais (1,2,3,4); specs precisas + comando nas mecânicas. ✓
- Consistência de tipos: `client_ip(...) -> str`, `LocalFTSStore.search(...) -> list[SearchResult]`, `settings.trusted_proxy: bool`. ✓
