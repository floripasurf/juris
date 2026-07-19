# Correções da Revisão Completa 18/07 — Implementation Plan (v2, pós-revisão Codex)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar tarefa a tarefa. Steps usam checkbox (`- [ ]`).

**Goal:** Corrigir os achados da revisão de 18/07 nas prioridades ajustadas pela revisão Codex: retry perigoso no peticionamento, gate de grounding na camada de filing, vetores-zero no seed, identidade de citação, alertas por tenant, keepalive, prazo em dobro POR PROCESSO/REGRA, embargos em interlocutória (escopo estreito) e — por último, com flag desligada — cadeia LLM por CLIs de assinatura.

**Architecture:** Runtime SQLite-first (ADR-0020), split-trust (ADR-0015), PII nunca sai crua (ADR-0016, `DeidentifyingLLM` fail-closed). **Base de código: `origin/main` (082139e)** — o runtime em produção (4d2d8ec) está 15 commits ATRÁS, e esse delta inclui billing Fase A (Pix), "Contratar" no produto, e-mail opcional no trial e setup token-first do agente. Todo o trabalho nasce em worktree a partir de origin/main; nada é implementado sobre o checkout de produção.

**Fatos validados ao vivo (18/07):** `luna`/minis indisponíveis na conta ChatGPT (`400 not supported`); funciona `gpt-5.5` + `model_reasoning_effort="low"`. `claude --print --model haiku` OK. BGE-M3 já em cache no Mini; dry-run do backfill confirmou 1761 chunks NULL. Ollama do Mini NÃO tem `qwen3:8b` (causa dos 404 de 15/07).

**Decisões de produto pendentes (gates humanos, não bloqueiam as tasks de código):**
1. **Deploy do delta de 15 commits** — revisar `git log 4d2d8ec..origin/main` antes do próximo restart de produção (inclui billing/self-service; muda o perfil de risco do serviço).
2. **Ligar o backend por assinatura** (`JURIS_DRAFT_BACKEND=cli`) — os termos individuais OpenAI/Anthropic não autorizam claramente servir terceiros via app web. O código entra DESLIGADO por default, com allowlist de tenant; ligar (mesmo canário no escritorio-piloto) é decisão do Raphael, registrada, ciente do risco ToS. Caminho definitivo para SaaS: API/business.

**Tech Stack:** Python 3.12, `uv`, FastAPI, SQLite/FTS5, sentence-transformers (BGE-M3), pytest, ruff, mypy --strict.

## Global Constraints

- **Gates de CI** (todos verdes): `uv run ruff check src/juris tests scripts/scan_secrets.py`; `uv run mypy src/juris`; `uv run pytest tests/unit -q`; `uv run --with pip-audit pip-audit --local --strict`.
- **Regras ruff:** E, F, I, N, B, UP, S, A, C4, RET, SIM. Sem `except` nu; `BLE001` só com noqa justificado.
- **Sem `print()` para log** — structlog. Type hints em tudo. Docstrings Google-style em API pública.
- **Isolamento de tenant inegociável**; `tenant_id=None` = só seed público.
- **PII nunca sai crua** — LLM cloud sempre atrás de `DeidentifyingLLM` fail-closed.
- **Determinismo em caminho legal-crítico** — prazo/feriado/gate de grounding sem LLM.
- **Honestidade de copy.** Nunca logar endereço de e-mail/PII bruto em warning (domínio + contagem, no máximo).
- **TDD; testes ao lado da feature.** Commits `type(scope): subject`, trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- **Local de trabalho:** worktree `~/projects/_worktrees/juris/correcoes-1807` no Mac Mini (branch `fix/correcoes-revisao-1807` a partir de origin/main). O checkout de produção `~/projects/juris-pilot/app` não é tocado por tasks de código.
- **Contrato de erro HTTP estruturado:** `HTTPException(status_code=..., detail={"code": ..., "message": ...})` — `code` NUNCA como kwarg de HTTPException.

---

## Task P — Preparação (branch, delta, backups) [ordem 1]

**Sem código de produto.** Prepara o terreno e preserva o plano em Git.

- [x] **Step 1: Worktree a partir de origin/main**

```bash
ssh raphaellages@100.77.76.64
cd ~/projects/juris-pilot/app && git fetch origin
git worktree add ~/projects/_worktrees/juris/correcoes-1807 -b fix/correcoes-revisao-1807 origin/main
cd ~/projects/_worktrees/juris/correcoes-1807 && uv sync --frozen
uv run pytest tests/unit -q   # baseline verde antes de qualquer mudança
```

- [x] **Step 2: Commitar este plano no branch** (`docs/superpowers/plans/2026-07-18-correcoes-revisao-completa.md`). Commit: `docs(plan): correções da revisão 18/07 (v2 pós-Codex)`.

- [x] **Step 3: Revisar o delta não implantado** — `git log --stat 4d2d8ec..origin/main` e produzir resumo de 10 linhas (o que muda em produção no próximo restart) para decisão humana nº 1. NÃO fazer deploy nesta task.

- [x] **Step 4: Backups pré-mutação de produção** (pré-requisito da Task 0A):

```bash
sqlite3 ~/projects/juris-pilot/home/repertory.db ".backup ~/projects/juris-pilot/backups/repertory-pre-backfill-$(date +%Y%m%d).db"
cp ~/Library/LaunchAgents/com.causia.web.plist ~/projects/juris-pilot/backups/com.causia.web.plist.bak-$(date +%Y%m%d)
```

---

## Task 0A — Runbook de produção imediato [ordem 2]

- [x] **Step 1: Destravar drafts HOJE (independente da cadeia CLI):**

```bash
ssh raphaellages@100.77.76.64 'zsh -lc "ollama pull qwen3:8b"'   # modelo default do código atual
```

- [x] **Step 2: Backfill de embeddings** (backup da Task P feito):

```bash
cd ~/projects/juris-pilot/app
JURIS_HOME=/Users/raphaellages/projects/juris-pilot/home .venv/bin/juris repertory backfill-embeddings
sqlite3 ~/projects/juris-pilot/home/repertory.db "SELECT COUNT(*), SUM(embedding IS NULL) FROM chunks;"
# espera: 1761|0
```

- [x] **Step 3: Flags no plist** `com.causia.web.plist`, em `EnvironmentVariables`:
  - `JURIS_TRUSTED_PROXY` = `1` (efetiva: rate limit por usuário real atrás do túnel)
  - `JURIS_REQUIRE_EMBEDDINGS` = `1` (só após Step 2 verificado)
  - `JURIS_RATE_LIMIT_FAIL_CLOSED` = `1` (**hoje é no-op sem Redis** — o limiter em memória não tem backend que falhe; fica como preparo documentado do caminho Redis)

- [x] **Step 4: Recarga REAL do serviço** (kickstart não relê EnvironmentVariables):

```bash
launchctl bootout gui/501/com.causia.web
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.causia.web.plist
launchctl print gui/501/com.causia.web | grep -A3 "JURIS_TRUSTED_PROXY\|JURIS_REQUIRE_EMBEDDINGS"   # confirma env novo
```

- [x] **Step 5: Smoke** — público e autenticado:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8100/health        # espera 200
KEY=$(cat ~/projects/juris-pilot/escritorio-piloto.api-key)
curl -s -H "X-API-Key: $KEY" http://127.0.0.1:8100/api/health | head -c 300  # espera JSON ok
tail -20 ~/projects/juris-pilot/logs/web.err                                  # sem stacktrace novo
```

---

## Task 5 — Peticionamento sem retry cego [ordem 3 — a mais urgente de código]

**Problema:** `@mni_retry` decora `entregar_manifestacao` (`mni/operations/peticionamento.py:30`), NÃO-idempotente: timeout após o tribunal processar = petição em dobro.

**Files:**
- Modify: `src/juris/mni/operations/peticionamento.py`
- Modify: `src/juris/signing/filing.py` (estado `delivery_uncertain` distinto)
- Modify: `src/juris/web/filing_console.py` (serialização distingue o estado)
- Test: `tests/unit/mni/test_peticionamento_sem_retry.py` (novo)

**Interfaces:**
- Produz: `entregar_manifestacao` sem decorator de retry; `FilingResult.error_code: str | None` (novo campo, `"delivery_uncertain"` quando a entrega falhou APÓS o envio começar; `None`/outros códigos nos demais passos); serialização expõe `error_code`.

- [x] **Step 1: Teste falho — exceção retryável do decorator atual NÃO é retentada.** Antes de escrever o teste, conferir em `src/juris/mni/retry.py` quais classes são retentadas (transporte/timeout; `Fault` com code em `NON_RETRYABLE_FAULT_CODES` NÃO é). O fake deve lançar uma classe retryável (ex.: `zeep.exceptions.TransportError` ou `requests.Timeout` — a que o decorator captura):

```python
def test_entregar_manifestacao_nao_retenta_em_falha_de_transporte() -> None:
    calls = {"n": 0}
    client = _fake_client(calls, raises=TransportError("timeout"))
    with pytest.raises(TransportError):
        entregar_manifestacao(client, "123", "s", "0001", b"%PDF", "manifestacao")
    assert calls["n"] == 1
```

- [x] **Step 2: Remover `@mni_retry`** + docstring: "Sem retry automático: a entrega não é idempotente; em timeout, VERIFICAR no tribunal antes de reenviar." Consultas MNI mantêm `mni_retry`.

- [x] **Step 3: Estado distinto no orchestrator** — no ramo de erro do passo de entrega em `FilingOrchestrator.file`, auditar `filing.delivery_uncertain` e retornar `FilingResult(..., error_code="delivery_uncertain", error="Falha na entrega ao tribunal. ATENÇÃO: a petição PODE ter sido protocolada — confira o processo no tribunal antes de tentar novamente.")`. Falhas de render/preflight/assinatura (antes do envio) mantêm códigos próprios — a UI precisa distinguir "não foi" de "pode ter ido".

- [x] **Step 4: Serialização + UI** — `serialize_filing_result` inclui `error_code`; `index.html` mostra o aviso de verificação quando `error_code == "delivery_uncertain"` (sem botão de reenvio imediato).

- [x] **Step 5: Testes → PASS. Gates + commit**

Commit: `fix(mni): entrega de petição sem retry automático + estado delivery_uncertain distinto`

---

## Task 3 — Gate de grounding no DOMÍNIO de filing [ordem 4]

**Problema:** nada reverifica grounding antes de assinar/protocolar. **Ajuste Codex:** o gate vive em `FilingOrchestrator` (cobre web, CLI e caminho remoto/agente — auditável onde a assinatura acontece), não só no endpoint. O manifest JÁ carrega o veredito (`demo/artifacts.py:370-373`: `grounding_status`, `grounding_blocked_reason`, ...) — reusar, não duplicar.

**Files:**
- Modify: `src/juris/signing/filing.py` (`FilingRequest` + gate no `file()`)
- Modify: `src/juris/web/filing_console.py` (resolver manifest → evidência)
- Modify: `src/juris/web/app.py` (`FilingPayload` + wiring; 409 estruturado)
- Modify: `src/juris/cli/main.py` (comando `juris file`: resolve evidência do manifest do caso)
- Modify: `src/juris/web/static/index.html` (form envia artefato; override com justificativa; rótulo "documento externo")
- Test: `tests/unit/signing/test_filing_grounding_gate.py` (novo)

**Interfaces:**
- Produz:

```python
@dataclass(frozen=True, slots=True)
class GroundingEvidence:
    """Veredito de grounding transportado até o ato de protocolo."""
    status: str                          # "verified" | "blocked" | "unknown"
    draft_sha256: str                    # sha256 do markdown verificado
    revisao_humana_obrigatoria: bool = False

# FilingRequest ganha:
grounding: GroundingEvidence | None = None
grounding_override: bool = False
grounding_override_reason: str = ""
```

`FilingOrchestrator.file()` (passo 0, antes do render): deixa passar SOMENTE se (a) `grounding.status == "verified"` E `grounding.draft_sha256 == sha256(request.draft_markdown)` E `not revisao_humana_obrigatoria`; OU (b) `grounding_override=True` com `len(reason.strip()) >= 20` → audita `filing.grounding_override` (actor="lawyer", details com reason) e segue. Caso contrário retorna `FilingResult(success=False, error_code="grounding_required", ...)` + audit `filing.blocked_ungrounded`. `skip_preflight` NÃO pula este gate.

- [x] **Step 1: Testes falhos — 5 contratos no orchestrator** (montar orchestrator com fakes já usados nos testes existentes de filing):
  1. evidência verified + hash igual → pipeline segue (chega ao render);
  2. hash divergente → `error_code="grounding_required"`, audit `filing.blocked_ungrounded`, NADA assinado;
  3. `revisao_humana_obrigatoria=True` → `error_code="revisao_humana_obrigatoria"`;
  4. `grounding=None` (manifest antigo/documento externo) → `grounding_required`;
  5. override com reason ≥ 20 chars → segue + audit `filing.grounding_override`; reason curto → `grounding_required` (não aceita override vazio).

- [x] **Step 2: Implementar no orchestrator** (gate determinístico, ~30 linhas + dataclass). `revisao_humana_obrigatoria` vem para o manifest nesta task: em `demo/artifacts.py`, ao lado de `grounding_status` (linha ~370), acrescentar `"revisao_humana_obrigatoria": bool(draft.estrategia and draft.estrategia.revisao_humana_obrigatoria)` — compat: leitor trata ausência como `False` para manifests antigos, mas ausência de `grounding_status` vira `status="unknown"` (= exige override).

- [x] **Step 3: Resolver evidência nos chamadores** — helper em `filing_console.py`:

```python
def grounding_evidence_from_manifest(out_root: Path, output_dir: str, artifact_name: str) -> GroundingEvidence | None:
    """Carrega o veredito do manifest do caso (path confinado a out_root, mesmo esquema de filing_artifacts)."""
```

`FilingPayload` ganha `output_dir: str | None`, `artifact_name: str | None`, `override_grounding: bool = False`, `override_reason: str = Field(default="", max_length=_MAX_SHORT_TEXT)`. `submit_filing` monta `FilingRequest` com a evidência resolvida (ou `None`); em `error_code="grounding_required"`/`"revisao_humana_obrigatoria"` responde `HTTPException(status_code=409, detail={"code": <error_code>, "message": <texto para advogado>})`. `juris file` (CLI) resolve o manifest do diretório do caso que já recebe hoje; sem manifest → precisa de `--override-grounding --reason "..."`.

- [x] **Step 4: UI** — form de protocolo envia `output_dir`/`artifact_name` do artefato escolhido (o form já é semeado por `filing_artifacts`). Em 409: painel com duas saídas explícitas — "Voltar e revisar" (default) e "Protocolar mesmo assim (registrado em auditoria)" com textarea de justificativa; para markdown colado sem artefato, o mesmo painel com rótulo "Documento externo (não gerado pela Causia)".

- [x] **Step 5: Testes (incl. suíte de filing existente) → PASS. Gates + commit**

Commit: `feat(filing): gate de grounding no orchestrator — verified+hash ou override auditado, em todos os caminhos de protocolo`

---

## Task 4 — Vetores-zero → NULL + reparo + `--embed` explícito [ordem 5]

**Ajustes Codex:** dry-run não pode mutar; contrato genérico não pode quebrar Qdrant; `--embed` explícito (sem mágica por `ENVIRONMENT`).

**Files:**
- Modify: `src/juris/repertory/ingestion/seed_loader.py`, `registry.py`
- Modify: `src/juris/repertory/vector_store.py` (`LocalFTSStore` + guarda no `QdrantVectorStore.upsert`)
- Modify: `src/juris/cli/main.py`
- Test: `tests/unit/repertory/test_zero_embedding_repair.py` (novo)

**Interfaces:**
- Produz: `LocalFTSStore.count_zero_embeddings() -> int` (somente leitura); `LocalFTSStore.null_out_zero_embeddings() -> int` (mutador); `QdrantVectorStore.upsert` levanta `ValueError` para embedding vazio/zerado ("ingestão sem embedder não é suportada no Qdrant"); `repertory ingest --embed` (default False).

- [x] **Step 1: Testes falhos** — (a) `upsert` com `[[0.0]*8]` → `count_zero_embeddings()==1` e `missing_embedding_count()==0` (o bug); (b) `null_out_zero_embeddings()` → 1 reparado, `missing_embedding_count()==1`; (c) seed loader sem embedder grava NULL (SELECT embedding IS NULL); (d) `QdrantVectorStore.upsert` com `[]` levanta ValueError (mock do client, sem Qdrant real).

- [x] **Step 2: Placeholders NULL** nos dois ramos sem embedder (`seed_loader.py:130-133`, `registry.py:220-227`): `placeholder = [[] for _ in all_chunks]` (o `LocalFTSStore.upsert` já converte `[]`→NULL — mesmo caminho da escavação). A guarda do Qdrant (Step 1d) garante que esse contrato não vira zero-vector silencioso lá.

- [x] **Step 3: Reparo e contagem no store** — `count_zero_embeddings` (SELECT + `np.frombuffer` + `not any(...)`, sem UPDATE) e `null_out_zero_embeddings` (UPDATE ... SET embedding=NULL nos ids zerados; commit; retorna contagem).

- [x] **Step 4: CLI** — em `repertory_backfill_embeddings`: no `--dry-run`, reportar `count_zero_embeddings()` SEM mutar ("N vetores-zero legados seriam reparados"); no run real, `null_out_zero_embeddings()` ANTES de `missing_embedding_count()`. Em `repertory ingest`: `--embed` (bool, default False) instancia `LegalEmbedder()` e passa ao loader/`ingest_source` (conferir kwarg exato nas assinaturas); sem `--embed`, imprimir lembrete "chunks sem embedding — rode backfill-embeddings".

- [x] **Step 5: Testes → PASS. Gates + commit**

Commit: `fix(retrieval): NULL como placeholder, reparo de vetores-zero (dry-run só informa) e ingest --embed explícito`

---

## Task 6 — Identidade real na citação em prosa [ordem 6]

**Ajustes Codex:** usar os campos REAIS do resultado (`source_id`, `texto` — não existe `titulo`); normalizar números com pontos (REsp 1.234.567); testar com os formatos efetivos do seed (súmula, tema, repetitivo, OJ).

**Files:**
- Modify: `src/juris/repertory/citation_lookup.py`
- Test: `tests/unit/repertory/test_citation_identity.py` (novo)

**Interfaces:**
- Produz: `_extract_citation_ref(normalized: str) -> tuple[str | None, str | None]` (número sem pontuação, órgão minúsculo); `resolve_narrative_citation` retorna `(True, source_id)` só com número E órgão confirmados no candidato.

- [x] **Step 1: Levantar os formatos reais** — `sqlite3 <repertory de teste> "SELECT DISTINCT source_id FROM chunks LIMIT 40"` ou grep em `data/corpus/` para padrões de `source_id` do seed (ex.: súmulas STF/STJ/TST, temas de repercussão geral, repetitivos, OJs alfanuméricas). Registrar 6+ exemplos no teste.

- [x] **Step 2: Testes falhos**

```python
def test_extract_ref_formatos_reais() -> None:
    assert _extract_citation_ref("sumula 297 do stj") == ("297", "stj")
    assert _extract_citation_ref("resp 1.234.567/sp do stj") == ("1234567", "stj")
    assert _extract_citation_ref("tema 1234 do stf") == ("1234", "stf")
    assert _extract_citation_ref("oj 394 da sdi-1 do tst") == ("394", "tst")
    assert _extract_citation_ref("jurisprudencia pacifica") == (None, None)

def test_resolve_rejeita_orgao_errado(fake_repertory_top1_stf) -> None:
    found, sid = resolve_narrative_citation("Súmula 297 do STJ", fake_repertory_top1_stf)
    assert (found, sid) == (False, None)

def test_resolve_aceita_match_em_source_id_ou_texto(fake_repertory_certo) -> None:
    found, sid = resolve_narrative_citation("Súmula 297 do STJ", fake_repertory_certo)
    assert found is True
```

- [x] **Step 3: Implementar** — número: primeiro grupo `[\d.]+` após marcador (`sumula|tema|repetitivo|oj|enunciado|resp|re\b|rr\b`), com `.replace(".", "")`; órgão: primeiro token do conjunto de tribunais do corpus (derivar do registry de ingestão, não hardcode solto). Aceitar candidato `r` se score ≥ threshold E número aparece em `r.source_id` (normalizado sem pontos) OU no início de `r.texto` (primeiros ~200 chars, dígitos normalizados) E órgão idem. Sem número/órgão extraíveis → `(False, None)` (prosa vaga não vira "verificado"; o chamador já trata como issue).

- [x] **Step 4: Testes → PASS. Gates + commit**

Commit: `fix(citation): identidade (número+órgão) obrigatória na resolução de citação em prosa`

---

## Task 7 — Alertas por tenant (call-sites completos) [ordem 7]

**Ajustes Codex:** atualizar TAMBÉM `juris alerts send` (`cli/main.py:2559` chama sem `db`); estados distintos "SMTP ausente" × "sem destinatário"; tolerar entrada legada string (`escritorio-piloto` é string hoje) e migrá-la pelo normalizador existente (`trial_access.py:464-467`); nunca logar endereço bruto.

**Files:**
- Modify: `src/juris/web/trial_access.py`, `src/juris/alerts/pending.py`, `src/juris/cli/main.py`
- Test: `tests/unit/alerts/test_per_tenant_recipients.py` (novo)

**Interfaces:**
- Produz: `alert_emails_for_tenant(tenant_id: str, *, path: Path | None = None) -> list[str]` (entrada string legada → `[]`, sem crash); `alert_email_config_from_settings(settings=None, *, to_addresses: list[str] | None = None)`; `send_pending_deadline_alerts(*, db: LocalDB, ...)` (keyword obrigatório); `PendingAlertDeliverySummary.no_recipients: bool` (novo, distinto de `smtp_configured=False`); subcomando `juris tenant alert-emails <tenant_id> [--add X] [--remove X] [--list]`.

- [x] **Step 1: Testes falhos** — (a) helper lê lista do tenants.json de objeto; (b) entrada string legada → `[]` sem exceção; (c) `--add` sobre entrada legada migra para objeto PRESERVANDO o hash da chave (reusar o normalizador de `trial_access.py:464-467`) — assert que autenticação com a chave antiga continua válida; (d) `to_addresses=[...]` ignora o global; (e) chamada sem `db` → `TypeError`; (f) summary distingue `no_recipients` de `smtp_configured`.

- [x] **Step 2: Implementar** — helper com o mesmo lock/leitura do registry; validação leve de formato (contém `@` e domínio), inválidos ignorados com `logger.warning("alert_email_invalido", tenant_id=..., dominio=<parte pós-@ ou "malformado">)` — nunca o endereço completo. `overnight --send-alerts`: por tenant, `recipients = alert_emails_for_tenant(tid)`; vazio → summary `no_recipients=True` + warning `alert_sem_destinatario` e NÃO envia; fallback ao global `alert_to_addresses` SOMENTE para `escritorio-piloto` (não regredir o piloto). `alerts send` (cli:2552-2559): resolver o `db` do tenant explícito (mesmo mecanismo de resolução de tenant do comando; se o comando é single-tenant local, passar o `LocalDB` do `JURIS_HOME` corrente explicitamente) e destinatários pela mesma regra.

- [x] **Step 3: Testes (incl. suíte de alerts/cli existente) → PASS. Gates + commit**

Commit: `feat(alerts): destinatários por tenant com migração de entrada legada + estados operacionais distintos`

---

## Task 10 — Keepalive do relay (servidor + cliente + medição correta) [ordem 8]

**Ajustes Codex:** medir DELTA por janela (o log é cumulativo — 558 já acumulados); configurar também o LADO CLIENTE (o supervisor em `api/local_agent.py` usa defaults do websockets: 20s/20s); unit test do launch é possível com monkeypatch.

**Files:**
- Modify: `src/juris/cli/main.py:2872` (uvicorn.run)
- Modify: `src/juris/api/local_agent.py` (kwargs do connect do relay)
- Test: `tests/unit/cli/test_web_ws_keepalive.py` (novo)

- [x] **Step 1: Teste falho — kwargs do uvicorn**

```python
def test_juris_web_configura_keepalive_ws(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: captured.update(kw))
    _invoke_cli(["web", "--host", "127.0.0.1", "--port", "0"])
    assert captured["ws_ping_interval"] == 25.0
    assert captured["ws_ping_timeout"] == 75.0
```

- [x] **Step 2: Implementar** — `uvicorn.run(..., ws_ping_interval=25.0, ws_ping_timeout=75.0)` + no connect do relay reverso do agente (`api/local_agent.py`, no supervisor): `ping_interval=25, ping_timeout=75` (entra na próxima release do agente; documentar no CHANGELOG do agente).

- [x] **Step 3: Medição correta (pós-deploy, runbook)** —

```bash
BASE=$(grep -c "keepalive ping timeout" ~/projects/juris-pilot/logs/web.err)
# 24h depois:
NOW=$(grep -c "keepalive ping timeout" ~/projects/juris-pilot/logs/web.err)
echo "delta 24h: $((NOW - BASE))"   # meta: <10 (era ~100/dia)
```

Registrar antes/depois no PR, junto com `/api/agent-health` do escritorio-piloto.

- [x] **Step 4: Gates + commit**

Commit: `fix(web,agent): keepalive WS 25s/75s nos dois lados do relay`

---

## Task 8 — Prazo em dobro POR PROCESSO/REGRA (redesenho) [ordem 9]

**Ajustes Codex incorporados:** nada de multiplicador global de deployment; cada `PrazoRule` declara se admite dobra (exceções dos arts. 180 §2º/183 §2º/186 §4º — prazo próprio — e regras incompatíveis como o fluxo comum do art. 523); CLT fora (não dobrar regra trabalhista); modelagem por processo com default opcional por tenant; `Prazo` carrega `rule` — anotação via `dataclasses.replace` na regra; benefício depende de intimação pessoal — a flag é configuração EXPLÍCITA do operador, nunca inferência (docstring).

**Files:**
- Modify: `src/juris/prazo/rules.py` (`PrazoRule.admite_dobro`)
- Modify: `src/juris/prazo/engine.py` (`compute_prazo`/`compute_prazos`)
- Modify: `src/juris/config.py` (`parte_representada` default `""` — default do deployment single-tenant; docstring: em multi-tenant vira registro por tenant/processo)
- Modify: call-sites de `compute_prazos` (`grep -rn "compute_prazos(" src/juris` — jobs, workbench, demo) para aceitar/propagar o parâmetro por processo
- Test: `tests/unit/prazo/test_prazo_em_dobro.py` (novo)

**Interfaces:**
- Produz: `PrazoRule(..., admite_dobro: bool = True)` — `False` em: "Pagamento voluntário (cumprimento)" (art. 523 — regime da Fazenda é outro, arts. 534-535), "Prazo judicial genérico" (prazo fixado pelo juiz = prazo próprio, exceção expressa dos §§) e TODAS as `CLT_RULES`; `compute_prazos(..., parte_representada: str = "") -> ...` com valores válidos `{"", "fazenda", "mp", "defensoria"}` (inválido → ValueError); dobra aplicada por regra: `rule_efetiva = dataclasses.replace(rule, dias_uteis=rule.dias_uteis * 2, base_legal=f"{rule.base_legal} c/c {_DOBRO_BASE_LEGAL[parte]} (em dobro)")` SOMENTE quando `parte_representada` setada E `rule.admite_dobro`.

- [x] **Step 1: Testes falhos**

```python
def test_apelacao_dobra_para_fazenda(cal) -> None:
    prazos = compute_prazos([_sentenca()], cal, TODAY, CNJ, parte_representada="fazenda")
    ap = _by_nome(prazos, "Apelação")
    assert ap.dias_uteis_total == 30 and "art. 183" in ap.rule.base_legal.lower()

def test_prazo_judicial_generico_nao_dobra(cal) -> None:      # prazo próprio (§2º)
    ...

def test_cumprimento_nao_dobra(cal) -> None:                  # art. 523 fora
    ...

def test_clt_nao_dobra(cal) -> None:                          # DL 779 fora do escopo
    ...

def test_reabertura_pos_ed_dobra(cal) -> None:                # _REOPENED × 2
    ...

def test_parte_invalida_levanta(cal) -> None:
    with pytest.raises(ValueError):
        compute_prazos([_sentenca()], cal, TODAY, CNJ, parte_representada="banco")
```

- [x] **Step 2: Implementar** — `_DOBRO_BASE_LEGAL = {"fazenda": "art. 183 CPC", "mp": "art. 180 CPC", "defensoria": "art. 186 CPC"}`; a substituição da regra acontece em `compute_prazos` antes de chamar `compute_prazo` (que fica intocado — recebe a regra já dobrada). Docstring do parâmetro: "Benefício exige intimação pessoal (arts. 180/183/186) e NÃO cobre prazos próprios (§§ 2º/4º) — configuração explícita do operador para o ente representado; nunca inferido dos autos. Art. 229 não se aplica a autos eletrônicos (§2º) e não é modelado."

- [x] **Step 3: Call-sites** — propagar `parte_representada=get_settings().parte_representada` nos jobs/workbench/demo (default `""` = comportamento atual). Por-processo/por-tenant real (registro no tenants.json ou no processo) fica como follow-up EXPLÍCITO no docstring — o parâmetro da API já permite.

- [x] **Step 4: Testes (incl. suíte prazo inteira) → PASS. Gates + commit**

Commit: `feat(prazo): prazo em dobro por regra e por chamada (arts. 180/183/186, com exceções de prazo próprio)`

---

## Task 9 — Embargos em interlocutória (escopo ESTREITO) [ordem 10]

**Ajustes Codex:** nem toda DECISAO_RECORRIVEL admite agravo — reabrir SOMENTE quando a decisão original geraria a regra do agravo (codigo_tpu=385, único match específico hoje); demais casos → revisão manual (nunca fabricar recurso); pareamento ED↔decisão correto (ED de decisão posterior não pode interromper a anterior); art. 1.026 interrompe prazo de RECURSO, apenas regras `TipoAcao.RECORRER`.

**Files:**
- Modify: `src/juris/prazo/engine.py`
- Test: `tests/unit/prazo/test_embargos_interlocutoria.py` (novo; espelhar `test_prazo_engine.py:210-266`)

**Interfaces:**
- Produz: `_REOPENED_AGRAVO_AFTER_ED_RULE` (15 dias úteis, `TipoAcao.RECORRER`, base `"Art. 1.015 c/c Art. 1.026 CPC"`); helper genérico `_embargos_interruption_for(analysis, dated_analyses)` (renomeia o atual `_embargos_interruption_for_sentence`; a detecção por regex/TPU 199 já é agnóstica); o bloco de interrupção roda para `SENTENCA` (regra reaberta = apelação, como hoje) e para `DECISAO_RECORRIVEL` **com `codigo_tpu == 385`** (regra reaberta = agravo); `DECISAO_RECORRIVEL` sem TPU 385 + ED detectados → `RevisaoManual(motivo="ed_sobre_decisao_recurso_incerto")`.

- [x] **Step 1: Estudar o pareamento existente** — ler `_embargos_interruption_for_sentence` completo e seu uso de `dated_analyses`: o ED considerado deve ser POSTERIOR à decisão e ANTERIOR à próxima decisão recorrível da mesma categoria (janela). Se o pareamento atual for só "primeiro ED após", escrever teste que o force: duas interlocutórias A e B com ED após B — A NÃO pode ser interrompida.

- [x] **Step 2: Testes falhos** — (a) interlocutória TPU 385 + ED pendente → agravo suprimido + `prazo_interrompido_embargos_pendentes`; (b) + julgamento do ED publicado → `reabertura-agravo-ed` 15 dias úteis da intimação; (c) interlocutória sem TPU 385 + ED → revisão manual `ed_sobre_decisao_recurso_incerto` (nenhum prazo fabricado); (d) pareamento: ED depois da decisão B não interrompe a decisão A; (e) regressão: cenários de sentença de `test_prazo_engine.py:210-266` intactos.

- [x] **Step 3: Implementar** — extrair o corpo do bloco de `engine.py:289-333` para `_handle_embargos_interruption(..., *, reopened_rule: PrazoRule | None) -> bool`; `reopened_rule=None` → só suprime e manda para revisão manual (caso c). Chamada para SENTENCA com a regra da apelação; para DECISAO_RECORRIVEL: `reopened_rule = _REOPENED_AGRAVO_AFTER_ED_RULE if analysis.codigo_tpu == 385 else None`. `movimento_id` reaberto: `f"{analysis.movimento_id}:reabertura-agravo-ed"`. Docstring: "Acórdão/RE/REsp sem categoria própria no CategoriaSemantica — fora do escopo; art. 1.026 interrompe apenas prazos recursais."

- [x] **Step 4: Testes → PASS. Gates + commit**

Commit: `feat(prazo): interrupção por ED em interlocutória agravável (TPU 385); demais decisões vão a revisão manual`

---

## Task 1 — `LocalCliLLM`: modelo/effort/binário + validação estrutural + processo são [ordem 11]

**Ajustes Codex:** validar ESTRUTURA contra o schema (não só `json.loads`) — sem dep nova (projeto não tem jsonschema): checar tipo raiz + chaves `required`; teste de timeout com kill do GRUPO de processos; teste limpa o arquivo temporário do codex.

**Files:**
- Modify: `src/juris/llm/local_cli.py`
- Test: `tests/unit/llm/test_local_cli.py`

**Interfaces:**
- Produz: `LocalCliLLM(provider, model=None, timeout_seconds=180.0, cwd=None, reasoning_effort=None, binary=None)`; `complete` levanta `RuntimeError` quando `schema` pedido e a saída não é JSON válido OU viola a estrutura (raiz não-objeto quando `type: object`; chave de `required` ausente); subprocesso criado com `start_new_session=True` e timeout mata via `os.killpg`.

- [x] **Step 1: Testes falhos**

```python
def test_codex_command_modelo_effort_binario() -> None:
    llm = LocalCliLLM(provider="codex", model="gpt-5.5", reasoning_effort="low",
                      binary="/opt/homebrew/bin/codex")
    command, stdin = llm._command_and_stdin(prompt="p", system=None, schema=None,
                                            max_tokens=64, temperature=0.0)
    try:
        assert command[0] == "/opt/homebrew/bin/codex"
        i = command.index("-m"); assert command[i + 1] == "gpt-5.5"
        j = command.index("-c"); assert command[j + 1] == 'model_reasoning_effort="low"'
        assert stdin == "p"
    finally:
        _codex_output_file(command).unlink(missing_ok=True)   # teste não vaza tmp

@pytest.mark.asyncio
async def test_schema_json_valido_mas_estrutura_errada_levanta(monkeypatch) -> None:
    llm = LocalCliLLM(provider="claude")
    async def fake_run(command, *, stdin): return '{"outra_chave": 1}'
    monkeypatch.setattr(llm, "_run", fake_run)
    with pytest.raises(RuntimeError, match="schema"):
        await llm.complete("p", schema={"type": "object", "required": ["tese"],
                                        "properties": {"tese": {"type": "string"}}})

@pytest.mark.asyncio
async def test_timeout_mata_grupo_de_processos() -> None:
    llm = LocalCliLLM(provider="claude", timeout_seconds=0.2,
                      binary="/bin/sh")  # sh -c sleep como processo real
    # monkeypatch _command_and_stdin para ["/bin/sh", "-c", "sleep 5"]; espera TimeoutError
    # e assert de que o processo não sobrevive (poll via os.killpg(..., 0) → ProcessLookupError)
```

- [x] **Step 2: Implementar** — kwargs novos; ramo codex ganha `-m`/`-c` (claude já tem `--model`); `binary or "codex"`/`binary or "claude"`. `_validate_structured(schema, structured)`: raiz dict quando `type=="object"`; toda chave em `schema.get("required", [])` presente — senão `RuntimeError(f"{self.model_name} violou o schema: ...")` (também quando `json.loads` falha). `_run`: `create_subprocess_exec(..., start_new_session=True)`; no timeout, `os.killpg(os.getpgid(process.pid), signal.SIGKILL)` com fallback `process.kill()` se o grupo já morreu.

- [x] **Step 3: Testes → PASS. Gates + commit**

Commit: `feat(llm): LocalCliLLM com modelo/effort/binário, validação estrutural de schema e kill de grupo em timeout`

---

## Task 2 — Cadeia por assinatura DESLIGADA por default (canário gated) [ordem 12]

**Ajustes Codex:** flag off por default; allowlist exclusiva de tenant; concorrência global 1; cwd = tempdir vazio; ToS é decisão humana ANTES de ligar (registrada no header do plano); RAM: Ollama 14B como último recurso compete com BGE-M3/reranker — último recurso passa a ser o modelo pequeno `qwen2.5:3b` (já instalado) e o 14B fica documentado como opção manual.

**Files:**
- Modify: `src/juris/config.py`, `src/juris/web/demo_service.py`, `.env.example`
- Test: `tests/unit/web/test_demo_service_llm_chain.py` (novo)

**Interfaces:**
- Produz (config):

```python
draft_backend: str = Field("ollama", validation_alias="JURIS_DRAFT_BACKEND")   # ollama | cli
cli_llm_tenants: str = Field("", validation_alias="JURIS_CLI_LLM_TENANTS")     # allowlist CSV; vazia = ninguém
cli_llm_model: str = Field("gpt-5.5", validation_alias="JURIS_CLI_LLM_MODEL")
cli_llm_effort: str = Field("low", validation_alias="JURIS_CLI_LLM_EFFORT")
cli_fallback_model: str = Field("haiku", validation_alias="JURIS_CLI_FALLBACK_MODEL")
codex_bin: str = Field("codex", validation_alias="JURIS_CODEX_BIN")
claude_bin: str = Field("claude", validation_alias="JURIS_CLAUDE_BIN")
ollama_model: str = Field("qwen3:8b", validation_alias="JURIS_OLLAMA_MODEL")
```

- Produz (demo_service): `_build_cli_chain() -> AbstractLLM`; `_build_llm(*, use_cloud: bool, tenant_id: str | None = None)` usa a cadeia SOMENTE se `draft_backend == "cli"` E `tenant_id` na allowlist; semáforo módulo-level `_CLI_LLM_SEMAPHORE = asyncio.Semaphore(1)` aplicado por um wrapper `_SerializedLLM(AbstractLLM)` em volta da cadeia (concorrência global 1 — trial não enfileira atrás do canário porque trial nem entra na allowlist); `LocalCliLLM` instanciado com `cwd=Path(tempfile.mkdtemp(prefix="juris-cli-llm-"))` vazio.

- [x] **Step 1: Testes falhos** — (a) `_build_cli_chain` compõe `DeidentifyingLLM(codex)` → `FallbackLLM` → `DeidentifyingLLM(haiku)` → `OllamaLLM` local (sem de-id, on-device); (b) `_build_llm(tenant_id="trial_x")` com backend cli e allowlist `escritorio-piloto` → retorna Ollama (não a cadeia); (c) `_build_llm(tenant_id="escritorio-piloto")` → cadeia serializada; (d) duas chamadas concorrentes na cadeia executam em série (fake LLM com evento asyncio; asserta não-sobreposição).

- [x] **Step 2: Implementar** — builder conforme interface (de-id com `default_ner_redactor()` fail-closed nos dois ramos cloud; justificativa do Ollama local sem de-id = mesmo racional `fallback_is_local` de `_build_ai_of_preference_llm`). Call-sites de `_build_llm` em demo_service passam o `tenant_id` do run (já disponível no contexto do run). Registrar warning estruturado `cli_llm_canary_used` (tenant, modelo) a cada uso — dá visibilidade de carga na assinatura.

- [x] **Step 3: `.env.example`** — as 8 flags com 1 linha cada; nas flags de cadeia, comentário: `# NÃO ligar sem decisão registrada de ToS (ver plano 2026-07-18 §Decisões)`.

- [x] **Step 4: Testes → PASS. Gates + commit**

Commit: `feat(draft): cadeia por CLI de assinatura gated (flag off, allowlist, concorrência 1, cwd vazio)`

---

## Task 0B — Canário em produção (somente após decisão ToS do Raphael) [ordem 13]

- [x] Deploy do branch (após PR/merge e decisão humana nº 1 sobre o delta): atualizar `~/projects/juris-pilot/app` por fast-forward, `uv sync --frozen`, bootout/bootstrap.
- [x] SE decisão ToS = sim: no plist, `PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin`, `JURIS_DRAFT_BACKEND=cli`, `JURIS_CLI_LLM_TENANTS=escritorio-piloto`, `JURIS_OLLAMA_MODEL=qwen2.5:3b`; bootout/bootstrap + `launchctl print` para confirmar.
- [x] Smoke autenticado: 1 caso demo no tenant piloto; conferir `ai_model` do run = `codex_cli_subscription:gpt-5.5` e ausência de `demo_draft_failed`; 1 caso num tenant trial → deve continuar em Ollama.
- [x] Observação 24h: delta de keepalive (Task 10 Step 3), `cli_llm_canary_used` count, RAM (`memory_pressure`), latência de draft nos logs.

---

## Ordem de execução (consolidada)

1. **Task P** (worktree em origin/main + plano em git + backups + resumo do delta)
2. **Task 0A** (ollama pull + backfill + flags + bootout/bootstrap + smoke)
3. **Task 5** → 4. **Task 3** → 5. **Task 4** → 6. **Task 6** → 7. **Task 7** → 8. **Task 10**
9. **Task 8** → 10. **Task 9**
11. **Task 1** → 12. **Task 2** (flag OFF)
13. **Task 0B** (canário; depende das decisões humanas nº 1 e nº 2)

## Self-review (v2)

- Os 4 bloqueios do Codex têm resposta: base origin/main + revisão do delta (Task P); Task 2 gated (flag off, allowlist, semáforo 1, cwd vazio, ToS = gate humano); gate de grounding movido para `FilingOrchestrator` com evidência transportável e override auditado no domínio; prazo em dobro por regra (`admite_dobro`) + por chamada, com exceções legais explícitas. ✓
- Correções de contrato verificadas no código real: manifest reusa `grounding_status` existente (`demo/artifacts.py:370`); `Prazo.rule.base_legal` via `dataclasses.replace`; `SearchResult`/resultado sem `titulo` (match por `source_id`/`texto`); `HTTPException(detail={"code",...})`; `alerts send` sem db incluído na Task 7; entrada legada string testada; `/health` público no smoke; bootout/bootstrap no runbook; dry-run do backfill não muta; medição de keepalive por delta. ✓
- Fora de escopo explícito: WhatsApp, auto-update onedir, ADR-0017, dobro CLT (DL 779), acórdão/RE/REsp em embargos, billing (já existe em origin/main, não implantado). ✓
