# Revisão CAUSIA — Plano de Implementação das Pendências (2026-07-05)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar as pendências de engenharia levantadas na revisão de 2026-07-05: consolidar o Git em `main`, portar o fix de segurança órfão, aposentar código vestigial, automatizar backup e watchdog do deploy em produção (causia.com.br no Mac Mini), implementar o clock-skew real do preflight e validar o broker Redis do relay com dois workers.

**Architecture:** O produto está no ar (Mac Mini, `com.causia.web` porta 8100 + Cloudflare Tunnel, auth própria X-API-Key fail-closed). Este plano não muda arquitetura: fecha lacunas operacionais e de higiene sem tocar nos caminhos jurídico-críticos (prazo, assinatura, protocolo) além do preflight. Trabalho maior (notarização, refactor dos módulos-Deus, Sprint 12) fica em planos próprios — ver Trilha C no fim.

**Tech Stack:** Python 3.12 + uv, FastAPI, typer CLI, pytest, launchd (macOS), Redis (broker relay), gh CLI.

## Global Constraints

- Python 3.12+; type hints em toda assinatura; docstrings Google style (CLAUDE.md do repo).
- Sem `except Exception` novo — `BLE001` está ativo no Ruff como gate de CI.
- `mypy src/juris` é hard gate; cobertura `fail_under = 72` (pyproject.toml:179) — não regredir.
- Nunca deletar arquivo permanentemente: mover para `Quarantine/` preservando o caminho relativo (política global do usuário). `Quarantine/` deve estar no `.gitignore`.
- Commits: `type(scope): subject` (ex.: `fix(config): ...`); um commit lógico por task.
- Rodar `uv run pytest -q` e `uv run ruff check . && uv run mypy src/juris` antes de cada commit.
- Baseline verde em 2026-07-05: **1850 passed, 1 skipped, 4 xfailed** em ~56s.
- Segredos nunca em código/fixture; dados reais de processo nunca em teste.
- Branch de trabalho: partir de `feat/mni-mtls-token` (vira `main` na Task 1; a partir daí, feature branches a partir de `main`).

---

## Contexto — o que a revisão encontrou (mapa achado → destino)

| # | Achado | Evidência | Destino |
|---|--------|-----------|---------|
| 1 | Repo sem `main`; default do GitHub é `feat/sprint-14-unified-search`, **297 commits atrás** do trunk real (`feat/mni-mtls-token`); PR #7 aberto apontando para o branch errado | `gh repo view` / `git rev-list` | **Task 1** |
| 2 | PR #3 (fail-closed de URLs dev em prod, auditoria Atlas 2026-05-21) nunca portado; `config.py` segue sem validador | `git cherry` = `+`; `grep validator config.py` = 0 | **Task 2** |
| 3 | PRs #2/#5/#6 mergeados em bases mortas; branches obsoletos acumulando (o adapter CLI-cloud foi superado pelo `browser_session.py`/ADR-0018) | `src/juris/llm/` não tem `cli_cloud`; seeds já estão em `data/corpus/` | **Task 3** |
| 4 | `src/juris/api/orchestrator.py` é vestigial: 30 linhas, `/health` sempre verde (TODO linha 28); backend real é `web/app.py` (43 rotas, `/api/health?deep=1` real). Única referência: `Makefile:24` | relatório de exploração | **Task 4** |
| 5 | `juris backup create` existe e cobre JURIS_HOME/out/repertory/audit/recibos, mas **não há backup agendado** no Mac Mini (nenhum plist de backup em `docs/deploy/`) | `ls docs/deploy/*.plist` | **Task 5** |
| 6 | Sem watchdog nem monitor externo de uptime para causia.com.br (KeepAlive só cobre crash, não hang; tunnel morto ninguém detecta de dentro) | `docs/deploy/blackcube-pilot.md` §5 | **Task 6** |
| 7 | `_check_clock_skew` é placeholder que sempre passa (`signing/preflight.py:293`) — relevante para PAdES/prazo | TODO no código | **Task 7** |
| 8 | Broker Redis do relay (Sprint 8) entregue em código mas **sem smoke com Redis real + 2 workers** — gate declarado antes de habilitar em produção | `engineering_sprints.md` §Próxima sequência | **Task 8** |
| 9 | 6 ingesters stub órfãos (gated por ToS) + 6 fetchers vivos não-cabeados na registry; TST inteiro-teor desligado por default aguardando ToS | `repertory/ingestion/*` TODOs | **Trilha C6 / H3** |
| 10 | Instaladores do agente sem assinatura de SO (Gatekeeper/SmartScreen barram advogado leigo); auto-update valida manifesto Ed25519 mas o swap onedir é no-op | `packaging/agent/macos/build_dmg.sh:2`; `agent/update.py:31-33,66` | **Trilha C1 / H4** |
| 11 | 109 catches largos `# noqa: BLE001`, 9 deles em `api/local_agent.py` (ponte do token A3 — falha silenciosa = prazo perdido sem alarme) | relatório de exploração | **Trilha C2** |
| 12 | Módulos-Deus: `web/static/index.html` 3715 linhas, `cli/main.py` 3369, `web/app.py` 1616 (regra do repo: ~400) | `wc -l` | **Trilha C3** |
| 13 | Qdrant: escopo por tenant implementado, mas pontos legados sem marcador falham fechado — migração necessária **apenas quando** Qdrant for ativado em prod (piloto roda SQLite FTS+HNSW) | `vector_store.py:156` | **Trilha C4** |
| 14 | Piloto real (5–10 casos com A3), pareamento do agente no Mac Mini e decisão de ToS de inteiro teor: bloqueados por dependência humana, não por código | `pilot_runbook.md`; `blackcube-pilot.md` §0/§7 | **Trilha H** |

---

## Trilha A — Tasks de código (este plano)

### Task 1: Consolidar o Git — criar `main` e corrigir o default do GitHub

**Files:**
- Nenhum arquivo de código; operações git/gh no repo `floripasurf/juris`.

**Interfaces:**
- Produces: branch `main` == `feat/mni-mtls-token` atual, default no GitHub. Todas as tasks seguintes partem de `main`.

- [ ] **Step 1: Confirmar que o trunk local está limpo e sincronizado**

```bash
cd ~/Desktop/juris && git checkout feat/mni-mtls-token && git status --short && git fetch origin && git rev-list --count origin/feat/mni-mtls-token..feat/mni-mtls-token
```
Esperado: status vazio e `0` (nada não-pushado).

- [ ] **Step 2: Criar e publicar `main`**

```bash
git branch main feat/mni-mtls-token && git push -u origin main
```
Esperado: `* [new branch] main -> main`.

- [ ] **Step 3: Tornar `main` o default do GitHub**

```bash
gh repo edit floripasurf/juris --default-branch main && gh repo view --json defaultBranchRef -q .defaultBranchRef.name
```
Esperado: `main`.

- [ ] **Step 4: Fechar o PR #7 (conteúdo dele agora É o main)**

```bash
gh pr close 7 --comment "Consolidado: main foi criado a partir de feat/mni-mtls-token (este branch). O diff deste PR está integralmente em main; o alvo (feat/sprint-14-unified-search) era um trunk defasado."
```
Esperado: PR #7 fechado.

- [ ] **Step 5: Trocar o branch de trabalho local para main**

```bash
git checkout main && git branch --show-current
```
Esperado: `main`. (O branch `feat/mni-mtls-token` fica para a Task 3 arquivar.)

---

### Task 2: Portar o fix do PR #3 — URLs dev-default detectadas em prod (sem quebrar o piloto SQLite)

O validador original do PR #3 falha fechado quando `ENVIRONMENT=prod` mantém qualquer URL localhost default (postgres/qdrant/redis/ollama). **Portá-lo literalmente derrubaria o Mac Mini**: o piloto em produção roda SQLite-first e legitimamente não define `DATABASE_URL`/`QDRANT_URL`. Port adaptado: helper puro que lista os "vazamentos", warning estruturado no load em prod, e hard-fail apenas com opt-in `JURIS_STRICT_PROD_URLS=1` (para o deploy docker futuro que realmente usa esses serviços).

**Files:**
- Modify: `src/juris/config.py`
- Test: `tests/unit/test_config_prod_overrides.py` (novo)

**Interfaces:**
- Produces: `Settings.dev_default_leaks() -> list[str]`; env `JURIS_STRICT_PROD_URLS` (bool, default False) no `Settings` como `strict_prod_urls`.
- Consumes: nada de tasks anteriores.

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/unit/test_config_prod_overrides.py`:

```python
"""ENVIRONMENT=prod não pode mascarar env vars esquecidas com defaults localhost (PR #3 portado)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from juris.config import Settings

_PROD_OVERRIDES = {
    "database_url": "postgresql+asyncpg://u:p@db:5432/juris",
    "database_url_sync": "postgresql+psycopg://u:p@db:5432/juris",
    "qdrant_url": "http://qdrant:6333",
    "redis_url": "redis://redis:6379/0",
    "ollama_url": "http://ollama:11434",
}

_URL_ENV_VARS = ("DATABASE_URL", "DATABASE_URL_SYNC", "QDRANT_URL", "REDIS_URL", "OLLAMA_URL", "JURIS_STRICT_PROD_URLS")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _URL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_prod_with_defaults_reports_leaks() -> None:
    settings = Settings(environment="prod", _env_file=None)
    assert sorted(settings.dev_default_leaks()) == [
        "database_url",
        "database_url_sync",
        "ollama_url",
        "qdrant_url",
        "redis_url",
    ]


def test_prod_strict_mode_fails_closed() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(environment="prod", strict_prod_urls=True, _env_file=None)
    for name in ("database_url", "qdrant_url", "redis_url", "ollama_url"):
        assert name in str(exc.value)


def test_prod_strict_mode_passes_with_overrides() -> None:
    settings = Settings(environment="prod", strict_prod_urls=True, _env_file=None, **_PROD_OVERRIDES)
    assert settings.dev_default_leaks() == []


def test_dev_defaults_load_and_report_nothing() -> None:
    settings = Settings(environment="dev", _env_file=None)
    assert settings.dev_default_leaks() == []
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
uv run pytest tests/unit/test_config_prod_overrides.py -q
```
Esperado: FAIL — `AttributeError: 'Settings' object has no attribute 'dev_default_leaks'` (e/ou erro de campo `strict_prod_urls`).

- [ ] **Step 3: Implementar em `src/juris/config.py`**

Adicionar (adaptando o diff original de `origin/fix/require-prod-env-overrides`, commit `6704a79`):

```python
# no topo, junto dos imports existentes:
from pydantic import model_validator  # acrescentar ao import existente de pydantic

# constante de módulo, antes de class Environment:
# URLs que existem só como conveniência de dev. Em prod elas indicam env var
# esquecida; com JURIS_STRICT_PROD_URLS=1 o load falha fechado (deploy docker).
_DEV_DEFAULT_URLS = {
    "database_url": "postgresql+asyncpg://juris:juris_dev@localhost:5432/juris",
    "database_url_sync": "postgresql+psycopg://juris:juris_dev@localhost:5432/juris",
    "qdrant_url": "http://localhost:6333",
    "redis_url": "redis://localhost:6379/0",
    "ollama_url": "http://localhost:11434",
}
```

Dentro de `class Settings`, junto dos demais campos:

```python
    strict_prod_urls: bool = Field(
        default=False,
        validation_alias="JURIS_STRICT_PROD_URLS",
        description="Em prod, falha fechado se alguma URL de backend ainda for o default localhost de dev.",
    )
```

E os métodos (depois de `is_dev`):

```python
    def dev_default_leaks(self) -> list[str]:
        """Nomes de URLs ainda no default localhost de dev quando ENVIRONMENT=prod."""
        if self.environment != Environment.PROD:
            return []
        return [name for name, dev_value in _DEV_DEFAULT_URLS.items() if getattr(self, name) == dev_value]

    @model_validator(mode="after")
    def _warn_or_reject_dev_defaults_in_prod(self) -> "Settings":
        leaked = self.dev_default_leaks()
        if not leaked:
            return self
        if self.strict_prod_urls:
            joined = ", ".join(sorted(leaked))
            msg = (
                f"ENVIRONMENT=prod exige override explícito para: {joined}. "
                "Defina as env vars correspondentes (ex.: DATABASE_URL=...) antes de subir."
            )
            raise ValueError(msg)
        log.warning("prod_dev_default_urls", leaked=sorted(leaked))
        return self
```

Nota: se `config.py` não tiver logger de módulo, criar `log = structlog.get_logger(__name__)` no topo (padrão do repo). Atenção ao `validation_alias`: verificar como os demais campos com prefixo `JURIS_` são declarados no `Settings` (há `env_prefix`/aliases no `SettingsConfigDict`?) e seguir o mesmo padrão para o nome da env var.

- [ ] **Step 4: Rodar os testes novos e a suíte inteira**

```bash
uv run pytest tests/unit/test_config_prod_overrides.py -q && uv run pytest -q
```
Esperado: novos PASS; suíte completa sem regressão (atenção a testes existentes que instanciem `Settings(environment="prod")` — se algum quebrar pelo warning, é só log, não deve quebrar; se quebrar por `strict`, o default False está errado).

- [ ] **Step 5: Doctor cobra em produção (visibilidade operacional)**

Localizar o comando doctor (`grep -n "def doctor" src/juris/cli/main.py src/juris/ops/*.py`) e acrescentar, no bloco de checks de produção (o mesmo que já cobra `JURIS_AUDIT_HMAC_KEY`), um check que chama `settings.dev_default_leaks()` e reporta cada item como warning com a mensagem `URL de backend ainda no default de dev: <nome> (defina a env var ou ative JURIS_STRICT_PROD_URLS=1 no deploy docker)`. Seguir exatamente o formato dos checks vizinhos. Adicionar um teste ao arquivo de testes do doctor existente (localizar com `grep -rln "doctor" tests/unit/`) cobrindo: prod + default → warning presente na saída.

- [ ] **Step 6: Gates e commit**

```bash
uv run ruff check . && uv run mypy src/juris && uv run pytest -q
git add src/juris/config.py tests/unit/test_config_prod_overrides.py src/juris/cli/main.py
git commit -m "fix(config): detectar URLs dev-default em prod (port do PR #3, strict opt-in)"
```

- [ ] **Step 7: Fechar o PR #3 com rastreabilidade**

```bash
gh pr close 3 --comment "Portado para main em <sha do commit acima> com adaptação: o piloto de produção (Mac Mini) é SQLite-first e não define essas URLs, então o fail-closed literal derrubaria o serviço. Em main: warning estruturado + check no doctor por padrão, hard-fail com JURIS_STRICT_PROD_URLS=1 (deploy docker). Crédito: Atlas night safety-audit 2026-05-21."
```

---

### Task 3: Encerrar branches/PRs obsoletos e registrar a decisão do adapter CLI-cloud

**Files:**
- Modify: `docs/engineering_sprints.md` (nota de decisão)

**Interfaces:**
- Consumes: Task 1 (main existe e é default).
- Produces: repositório com um único trunk; histórico preservado via tags `archive/*`.

- [ ] **Step 1: Registrar a decisão sobre o adapter CLI-cloud**

Em `docs/engineering_sprints.md`, ao final da seção "Estado atual", acrescentar:

```markdown
**Decisão (2026-07-05) — adapter CLI-cloud (PRs #2/#6):** o adapter de LLM via
CLI de assinatura (Haiku sem API key) que vivia em `feat/cli-cloud-haiku` /
`feat/llm-cli-cloud-adapter` NÃO foi portado para `main`: o caminho de nuvem por
assinatura foi superado pela sessão de browser do provedor (ADR-0018,
`llm/browser_session.py`), e os seeds de corpus daqueles branches já existem em
`data/corpus/` (súmulas/OJs TST, temas RG STF). Os branches ficam arquivados como
tags `archive/*`; se a demanda "Haiku por assinatura via CLI" voltar, partir do
ADR-0018, não do branch antigo.
```

- [ ] **Step 2: Arquivar branches remotos como tags e removê-los**

```bash
cd ~/Desktop/juris
for b in feat/cli-cloud-haiku feat/llm-cli-cloud-adapter feat/corpus-seeds \
         feat/sprint-14-unified-search feat/sprint-15-demo-pilot \
         fix/require-prod-env-overrides feat/mni-mtls-token; do
  git tag "archive/${b#*/}" "origin/$b" && git push origin "archive/${b#*/}"
done
git push origin --delete feat/cli-cloud-haiku feat/llm-cli-cloud-adapter feat/corpus-seeds \
  feat/sprint-14-unified-search feat/sprint-15-demo-pilot fix/require-prod-env-overrides feat/mni-mtls-token
```
Esperado: 7 tags `archive/*` publicadas; branches remotos removidos (conteúdo preservado nas tags). Pré-condição: Tasks 1 e 2 concluídas (PRs #3 e #7 já fechados) — o GitHub não deixa apagar branch com PR aberto.

- [ ] **Step 3: Limpar branches locais**

```bash
git branch -D feat/sprint-13-corpus-expansion feat/sprint-14-unified-search feat/sprint-15-demo-pilot feat/mni-mtls-token
git fetch --prune && git branch -a
```
Esperado: sobra `main` (+ `archive/*` como tags). O commit único de `feat/sprint-13-corpus-expansion` (`1558f16`) é a versão antiga do Sprint 13 já reimplementada em main — conferir antes com `git show --stat 1558f16` que não há arquivo exclusivo dele; se houver, arquivar como tag também.

- [ ] **Step 4: Commit da nota de decisão**

```bash
git add docs/engineering_sprints.md && git commit -m "docs(sprints): decisão de arquivamento do adapter CLI-cloud + branches"
git push origin main
```

---

### Task 4: Aposentar `api/orchestrator.py` vestigial

O `/health` sempre-verde dele é um risco de observabilidade se alguém subir esse app achando que é o backend. O backend real (`web/app.py`) já tem `/api/health?deep=1` com probe real.

**Files:**
- Move: `src/juris/api/orchestrator.py` → `Quarantine/src/juris/api/orchestrator.py`
- Modify: `Makefile:24`
- Modify: `.gitignore` (garantir `Quarantine/`)

**Interfaces:**
- Produces: `make api` passa a subir o backend real (`juris web`).

- [ ] **Step 1: Confirmar que nada além do Makefile referencia o módulo**

```bash
grep -rn "api.orchestrator\|api/orchestrator" src tests docs docker pyproject.toml Makefile | grep -v __pycache__
```
Esperado: apenas `Makefile:24`. Se aparecer mais alguma referência, atualizá-la no mesmo espírito do Step 3.

- [ ] **Step 2: Mover para Quarantine (política do usuário — nunca deletar)**

```bash
mkdir -p Quarantine/src/juris/api
mv src/juris/api/orchestrator.py Quarantine/src/juris/api/orchestrator.py
grep -qx "Quarantine/" .gitignore || echo "Quarantine/" >> .gitignore
git add -u && git add .gitignore
```

- [ ] **Step 3: Corrigir o alvo `api` do Makefile**

Trocar a linha 24:

```makefile
# antes:
	uv run uvicorn juris.api.orchestrator:app --reload --port 8000
# depois:
	uv run juris web --port 8000
```

Verificar flags reais com `uv run juris web --help` (o comando existe em `cli/main.py:2789`); se o nome do parâmetro de porta for outro (ex.: `--porta`), usar o real.

- [ ] **Step 4: Suíte + commit**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy src/juris
git commit -m "chore(api): aposenta orchestrator vestigial (health sempre-verde); make api usa o backend real"
```
Esperado: suíte igual ao baseline (nenhum teste importava o módulo).

---

### Task 5: Backup diário automatizado no Mac Mini

`juris backup create` já cobre JURIS_HOME, JURIS_OUT_ROOT, repertory.db, audit e recibos com manifesto SHA-256 (`cli/main.py:3155`, default de saída `${JURIS_BACKUP_DIR:-$JURIS_HOME/backups}`). Falta agendar e rotacionar.

**Files:**
- Create: `scripts/backup_daily.sh`
- Create: `docs/deploy/com.causia.backup.plist`
- Modify: `docs/deploy/blackcube-pilot.md` (§5 Operação — instrução de instalação)
- Test: `tests/unit/test_backup_daily_script.py` (novo — valida o contrato do script via bash -n e opções)

**Interfaces:**
- Consumes: CLI `juris backup create -o <dir>` (existente).
- Produces: job launchd `com.causia.backup` diário às 03:45 (antes do purge das 04:30), retenção de 14 arquivos com expirados movidos para `.expired/` (nunca `rm` — política de quarentena).

- [ ] **Step 1: Escrever `scripts/backup_daily.sh`**

```bash
#!/bin/sh
# Backup diário do CAUSIA no Mac Mini. Chamado pelo launchd com.causia.backup
# com as MESMAS env vars de com.causia.web (JURIS_HOME, JURIS_OUT_ROOT, ...).
# Retenção: mantém os 14 .tar.gz mais recentes; expirados vão para .expired/
# (purge manual — nada é deletado automaticamente).
set -eu

APP_DIR="${CAUSIA_APP_DIR:-$HOME/juris-pilot/app}"
BACKUP_DIR="${JURIS_BACKUP_DIR:-$HOME/juris-pilot/backups}"
KEEP="${CAUSIA_BACKUP_KEEP:-14}"

mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR"

"$APP_DIR/.venv/bin/juris" backup create -o "$BACKUP_DIR"

mkdir -p "$BACKUP_DIR/.expired"
# lista por mtime decrescente; move do (KEEP+1)-ésimo em diante
ls -t "$BACKUP_DIR"/*.tar.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | while IFS= read -r old; do
  mv "$old" "$BACKUP_DIR/.expired/"
  [ -f "$old.sha256" ] && mv "$old.sha256" "$BACKUP_DIR/.expired/" || true
done

echo "backup_daily ok: $(ls "$BACKUP_DIR"/*.tar.gz 2>/dev/null | wc -l | tr -d ' ') arquivos ativos"
```

Conferir o nome real do arquivo de checksum gerado (`juris backup create` imprime `Checksum: ...` — ajustar a extensão no script se não for `.sha256`).

```bash
chmod +x scripts/backup_daily.sh && sh -n scripts/backup_daily.sh && echo SINTAXE-OK
```
Esperado: `SINTAXE-OK`.

- [ ] **Step 2: Teste de contrato do script**

Criar `tests/unit/test_backup_daily_script.py`:

```python
"""Contrato do backup_daily.sh: sintaxe válida, retenção sem rm, chmod 700."""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backup_daily.sh"


def test_script_exists_and_is_valid_sh() -> None:
    assert SCRIPT.exists()
    subprocess.run(["sh", "-n", str(SCRIPT)], check=True)


def test_script_never_deletes_only_quarantines() -> None:
    body = SCRIPT.read_text()
    assert "rm " not in body and "rm\t" not in body
    assert ".expired" in body
    assert "chmod 700" in body
```

```bash
uv run pytest tests/unit/test_backup_daily_script.py -q
```
Esperado: PASS.

- [ ] **Step 3: Escrever `docs/deploy/com.causia.backup.plist`**

Modelar em `docs/deploy/com.causia.purge.plist` (mesmas env vars/paths `REPLACE_WITH_PATH_TO`); diferenças: `Label` = `com.causia.backup`, `ProgramArguments` = `[/bin/sh, REPLACE_WITH_PATH_TO/app/scripts/backup_daily.sh]`, `StartCalendarInterval` = `Hour 3, Minute 45`, `StandardOutPath/StandardErrorPath` → `logs/backup.log`. Copiar o esqueleto XML do purge e trocar apenas esses campos (mantém consistência de convenção do Mac Mini).

- [ ] **Step 4: Documentar no runbook**

Em `docs/deploy/blackcube-pilot.md` §5 (Operação), depois do bloco do purge, acrescentar:

```markdown
- **Backup diário (`com.causia.backup`):** roda `scripts/backup_daily.sh` às 03:45
  (antes do purge), grava `.tar.gz` + checksum em `~/juris-pilot/backups/`
  (chmod 700) e mantém os 14 mais recentes; expirados vão para
  `backups/.expired/` (purge manual). Instalar igual ao purge:
  `cp docs/deploy/com.causia.backup.plist ~/Library/LaunchAgents/` → editar os
  `REPLACE_WITH_PATH_TO` → `launchctl bootstrap gui/$(id -u) ...`. Testar com
  `sh scripts/backup_daily.sh` manual e conferir `juris backup restore` num
  diretório temporário (docs/deploy/backup-restore.md). Cópia offsite: rsync do
  diretório `backups/` para o MacBook via Tailscale, semanal (manual por ora).
```

- [ ] **Step 5: Gates + commit**

```bash
uv run pytest -q && uv run ruff check .
git add scripts/backup_daily.sh docs/deploy/com.causia.backup.plist docs/deploy/blackcube-pilot.md tests/unit/test_backup_daily_script.py
git commit -m "ops(backup): job diário com.causia.backup com retenção quarentenada"
```

- [ ] **Step 6 (operacional, no Mac Mini via Tailscale): instalar e validar**

```bash
ssh raphaels-mac-mini 'cd ~/juris-pilot/app && git pull && sh scripts/backup_daily.sh'
# depois: cp do plist, editar paths, launchctl bootstrap, e conferir ~/juris-pilot/backups/
```
Esperado: `backup_daily ok: 1 arquivos ativos` na primeira execução.

---

### Task 6: Watchdog local + monitor externo de uptime

KeepAlive do launchd só religa processo morto; não cobre processo pendurado nem tunnel caído. Duas camadas: (a) watchdog local que faz probe HTTP no 8100 e `kickstart` se falhar; (b) monitor externo (fora do Mac Mini) para detectar queda do tunnel/DNS — passo humano de 10 min.

**Files:**
- Create: `scripts/causia_watchdog.sh`
- Create: `docs/deploy/com.causia.watchdog.plist`
- Modify: `docs/deploy/blackcube-pilot.md` (§5)
- Test: `tests/unit/test_watchdog_script.py`

**Interfaces:**
- Consumes: `/api/health` do web app (sem chave → 401 estruturado; **qualquer resposta HTTP conta como vivo** — o que o watchdog detecta é hang/morte, não auth).
- Produces: launchd `com.causia.watchdog` a cada 5 min.

- [ ] **Step 1: Escrever `scripts/causia_watchdog.sh`**

```bash
#!/bin/sh
# Watchdog do CAUSIA: se a web local (8100) não responder HTTP em 10s por
# 2 execuções seguidas, kickstart no serviço. Qualquer status HTTP = vivo
# (401 sem chave é o esperado); o alvo é hang/morte, não auth.
set -u

PORT="${CAUSIA_WEB_PORT:-8100}"
LABEL="${CAUSIA_WEB_LABEL:-com.causia.web}"
STATE="${TMPDIR:-/tmp}/causia_watchdog_failcount"

http_code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "http://127.0.0.1:${PORT}/api/health" || echo 000)

if [ "$http_code" != "000" ]; then
  rm -f "$STATE" 2>/dev/null || true
  exit 0
fi

fails=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 ))
echo "$fails" > "$STATE"
if [ "$fails" -ge 2 ]; then
  echo "$(date '+%F %T') watchdog: web sem resposta (${fails}x) — kickstart ${LABEL}"
  launchctl kickstart -k "gui/$(id -u)/${LABEL}"
  echo 0 > "$STATE"
fi
```

(Único `rm` é do arquivo de contador efêmero em TMPDIR — não é dado do projeto.)

```bash
chmod +x scripts/causia_watchdog.sh && sh -n scripts/causia_watchdog.sh && echo SINTAXE-OK
```

- [ ] **Step 2: Teste de contrato**

Criar `tests/unit/test_watchdog_script.py`:

```python
"""Contrato do causia_watchdog.sh: sintaxe, threshold de 2 falhas, kickstart."""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "causia_watchdog.sh"


def test_script_exists_and_is_valid_sh() -> None:
    assert SCRIPT.exists()
    subprocess.run(["sh", "-n", str(SCRIPT)], check=True)


def test_script_uses_two_strike_kickstart() -> None:
    body = SCRIPT.read_text()
    assert "launchctl kickstart" in body
    assert '-ge 2' in body
    assert "/api/health" in body
```

```bash
uv run pytest tests/unit/test_watchdog_script.py -q
```
Esperado: PASS.

- [ ] **Step 3: Plist `com.causia.watchdog.plist`**

Novamente modelar no esqueleto do purge: `Label` = `com.causia.watchdog`, `ProgramArguments` = `[/bin/sh, REPLACE_WITH_PATH_TO/app/scripts/causia_watchdog.sh]`, `StartInterval` = `300` (em vez de `StartCalendarInterval`), logs → `logs/watchdog.log`.

- [ ] **Step 4: Runbook §5 + monitor externo**

Acrescentar ao `blackcube-pilot.md` §5:

```markdown
- **Watchdog local (`com.causia.watchdog`):** probe em `127.0.0.1:8100/api/health`
  a cada 5 min; 2 falhas seguidas → `launchctl kickstart` da web. Instalar como
  os demais plists. Cobre hang; crash já é coberto pelo KeepAlive.
- **Monitor externo (detecta tunnel/DNS caído — o watchdog não vê isso):**
  registrar https://causia.com.br/ e https://causia.com.br/api/health num
  monitor fora da rede (ex.: UptimeRobot free, intervalo 5 min, alerta para
  lages.raphael@gmail.com). Critério: qualquer HTTP < 500 é UP (a raiz responde
  200 com a landing; /api/health sem chave responde 401 estruturado — ambos
  provam web+tunnel vivos).
```

- [ ] **Step 5: Gates + commit**

```bash
uv run pytest -q && uv run ruff check .
git add scripts/causia_watchdog.sh docs/deploy/com.causia.watchdog.plist docs/deploy/blackcube-pilot.md tests/unit/test_watchdog_script.py
git commit -m "ops(watchdog): kickstart local em hang + runbook de monitor externo"
```

- [ ] **Step 6 (operacional):** instalar plist no Mac Mini (mesmo fluxo da Task 5 Step 6) e criar o monitor no UptimeRobot (humano, ~10 min — ver Trilha H, item H5).

---

### Task 7: Clock-skew real no preflight de assinatura

Substituir o placeholder `_check_clock_skew` (`signing/preflight.py:293`) por medição real: comparar UTC local com o header `Date` de um `HEAD` no endpoint do tribunal. Não-bloqueante em v1 (severity `warning`); relevante porque skew grande compromete timestamps PAdES e o cálculo "protocolei dentro do prazo?".

**Files:**
- Modify: `src/juris/signing/preflight.py` (função `_check_clock_skew` + assinatura de `run_preflight`)
- Modify: `src/juris/signing/filing.py:203` e `src/juris/cli/main.py:3277` (callers — passar a URL do tribunal)
- Test: `tests/unit/test_preflight_clock_skew.py` (novo)

**Interfaces:**
- Produces: `run_preflight(..., tribunal_url: str | None = None)`; `_check_clock_skew(tribunal_url, timeout_seconds=3.0) -> PreflightCheck` com `name="clock_skew"`, `severity="warning"`, `passed=False` somente quando skew medido > 120s.
- Consumes: `PreflightCheck` existente (`preflight.py:58` — campos `name/passed/severity/message/retryable`; severity é `Literal["blocker","warning"]`).

- [ ] **Step 1: Testes que falham**

Criar `tests/unit/test_preflight_clock_skew.py`:

```python
"""Clock skew do preflight: mede contra o header Date do tribunal, warning-only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from juris.signing.preflight import _check_clock_skew


class _FakeTransport(httpx.BaseTransport):
    def __init__(self, server_now: datetime) -> None:
        self._server_now = server_now

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Date": format_datetime(self._server_now)})


def _patch_head(monkeypatch: pytest.MonkeyPatch, server_now: datetime) -> None:
    transport = _FakeTransport(server_now)

    def fake_head(url: str, **kwargs: object) -> httpx.Response:
        with httpx.Client(transport=transport) as client:
            return client.head(url)

    monkeypatch.setattr("juris.signing.preflight.httpx.head", fake_head)


def test_skew_pequeno_passa(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_head(monkeypatch, datetime.now(UTC) + timedelta(seconds=5))
    check = _check_clock_skew("https://mni.exemplo.jus.br/ws")
    assert check.name == "clock_skew"
    assert check.passed is True
    assert check.severity == "warning"


def test_skew_grande_gera_warning_reprovado(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_head(monkeypatch, datetime.now(UTC) + timedelta(seconds=600))
    check = _check_clock_skew("https://mni.exemplo.jus.br/ws")
    assert check.passed is False
    assert check.severity == "warning"
    assert "skew" in check.message.lower() or "relógio" in check.message.lower()


def test_sem_url_mantem_comportamento_atual() -> None:
    check = _check_clock_skew(None)
    assert check.passed is True


def test_tribunal_inacessivel_nao_bloqueia(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_head(url: str, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr("juris.signing.preflight.httpx.head", raise_head)
    check = _check_clock_skew("https://mni.exemplo.jus.br/ws")
    assert check.passed is True
    assert "indispon" in check.message.lower()
```

```bash
uv run pytest tests/unit/test_preflight_clock_skew.py -q
```
Esperado: FAIL — assinatura atual de `_check_clock_skew()` não aceita argumento.

- [ ] **Step 2: Implementar**

Em `signing/preflight.py` (adicionar `import httpx` e `from email.utils import parsedate_to_datetime` no topo; `datetime`/`UTC` já devem existir — conferir):

```python
_CLOCK_SKEW_WARN_SECONDS = 120.0


def _check_clock_skew(tribunal_url: str | None = None, *, timeout_seconds: float = 3.0) -> PreflightCheck:
    """Compara o relógio local (UTC) com o header ``Date`` do endpoint do tribunal.

    Warning-only em v1: skew > 120s reprova o check como aviso, sem bloquear o
    filing. Sem URL ou com tribunal inacessível, degrada para o comportamento
    anterior (passa com aviso de indisponibilidade).
    """
    if not tribunal_url:
        return PreflightCheck(
            name="clock_skew",
            passed=True,
            severity="warning",
            message="Clock skew não verificado (URL do tribunal ausente).",
        )
    try:
        response = httpx.head(tribunal_url, timeout=timeout_seconds, follow_redirects=True)
        server_date = parsedate_to_datetime(response.headers["Date"])
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return PreflightCheck(
            name="clock_skew",
            passed=True,
            severity="warning",
            message="Clock skew indisponível (tribunal não respondeu ao probe).",
        )
    skew_seconds = abs((datetime.now(UTC) - server_date).total_seconds())
    if skew_seconds > _CLOCK_SKEW_WARN_SECONDS:
        return PreflightCheck(
            name="clock_skew",
            passed=False,
            severity="warning",
            message=f"Relógio local difere do tribunal em {skew_seconds:.0f}s — verifique NTP antes de protocolar.",
        )
    return PreflightCheck(
        name="clock_skew",
        passed=True,
        severity="warning",
        message=f"Clock skew ok ({skew_seconds:.0f}s).",
    )
```

Em `run_preflight` (linha 303): acrescentar parâmetro `tribunal_url: str | None = None` (com docstring) e trocar a chamada interna `_check_clock_skew()` por `_check_clock_skew(tribunal_url)`.

- [ ] **Step 3: Passar a URL nos dois callers**

Em `signing/filing.py:203` e `cli/main.py:3277`: os dois já têm o identificador do tribunal em mãos; obter a config via registry (`from juris.mni.tribunais import get_tribunal`; conferir com `grep -n "class.*Tribunal\|wsdl\|base_url" src/juris/mni/tribunais.py | head` qual atributo carrega a URL — usar o endpoint de consulta/WSDL) e passar `tribunal_url=<atributo>`. Se o call site não tiver acesso trivial à config, passar `None` (comportamento atual preservado) e anotar no docstring do caller.

- [ ] **Step 4: Confirmar que warning reprovado não bloqueia filing**

```bash
grep -n "passed\|blocker" src/juris/signing/preflight.py | sed -n '/def _aggregate\|all(\|any(/p'
uv run pytest tests/unit -k "preflight" -q
```
Verificar na agregação de `PreflightResult` que só `severity="blocker"` com `passed=False` impede o submit; se a agregação tratar qualquer `passed=False` como bloqueio, ajustar o check para `passed=True` com mensagem de alerta (manter os testes coerentes — trocar a asserção de `passed is False` por mensagem contendo o skew).

- [ ] **Step 5: Gates + commit**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy src/juris
git add src/juris/signing/preflight.py src/juris/signing/filing.py src/juris/cli/main.py tests/unit/test_preflight_clock_skew.py
git commit -m "feat(signing): clock skew real no preflight (HEAD Date do tribunal, warning-only)"
```

---

### Task 8: Smoke do broker Redis do relay com 2 workers (gate do Sprint 8)

O broker (`JURIS_RELAY_BROKER`, `api/relay.py`) está entregue em código com pub/sub por tenant e dedupe `SET NX`, mas o doc de sprints exige smoke com **Redis real + dois workers** antes de habilitar em produção. Produto: script executável + seção de runbook + Sprint 8 marcado como concluído.

**Files:**
- Create: `scripts/smoke_relay_broker.py` (modelado em `scripts/remote_smoke.py`)
- Modify: `docs/deployment.md` (seção "Broker do relay — smoke")
- Modify: `docs/engineering_sprints.md` (Sprint 8 → concluído com data)

**Interfaces:**
- Consumes: `RelayHub`/broker em `src/juris/api/relay.py` (broker ativa com env `JURIS_RELAY_BROKER=redis://...`); fake-agent e fiação de `scripts/remote_smoke.py` (agente com `_FakeMNI`, token de pareamento, credenciais locais fake); rota `/ws/agent-relay` e `/api/agent-health` do web app.
- Produces: `uv run python scripts/smoke_relay_broker.py` sai 0 quando: agente conectado ao worker A é alcançado por request entrando no worker B via broker; sai ≠0 com diagnóstico caso contrário.

- [ ] **Step 1: Ler as duas referências antes de escrever**

Ler `scripts/remote_smoke.py` inteiro (como o fake agent é montado e como se valida "nenhuma credencial no wire") e `src/juris/api/relay.py` linhas 420–520 (como o broker é ativado e o fail-closed sem broker). Anotar: nome exato da rota de handshake do relay, formato do token de pareamento por tenant, e qual chamada de API dispara operação que atravessa o relay (`/api/agent-health` faz probe de alcançabilidade — `engineering_sprints.md` Sprint 3).

- [ ] **Step 2: Subir Redis efêmero para o smoke**

```bash
docker run -d --name smoke-redis -p 6399:6379 redis:7-alpine && docker ps --filter name=smoke-redis --format '{{.Status}}'
```
Esperado: `Up ...`.

- [ ] **Step 3: Escrever `scripts/smoke_relay_broker.py`**

Estrutura (reusar as classes/helpers do `remote_smoke.py` — importar de lá o que for reutilizável em vez de duplicar):

1. Config comum via env: `JURIS_RELAY_BROKER=redis://127.0.0.1:6399/0`, `JURIS_REQUIRE_TENANTS=1`, `tenants.json` e binding de agente temporários (tenant `smoke-broker`), tudo em `tempfile.TemporaryDirectory()`.
2. Subir **dois** uvicorn do web app real em threads (portas 8181 e 8182), como o `remote_smoke.py` faz com um.
3. Conectar o fake agent (mesmo padrão `_FakeMNI` + credenciais `agent-*` locais) ao **worker A** via `/ws/agent-relay` com o token de pareamento.
4. Fazer a chamada autenticada (X-API-Key do tenant) em **worker B**: `GET /api/agent-health` e em seguida uma leitura MNI fake ponta-a-ponta (mesma operação do remote_smoke), assertando que a resposta veio do agente conectado no A.
5. Repetir a chamada com `request_id` idêntico para exercitar o dedupe (`SET NX`) — segunda submissão não pode duplicar a operação no agente (contador no fake).
6. Assert final de segurança herdado do remote_smoke: nenhum CPF/senha/PIN nos frames capturados.
7. `finally`: derrubar servers e imprimir `SMOKE BROKER OK`.

Executar:

```bash
JURIS_RELAY_BROKER=redis://127.0.0.1:6399/0 uv run python scripts/smoke_relay_broker.py; echo "exit=$?"
```
Esperado: `SMOKE BROKER OK` e `exit=0`.

- [ ] **Step 4: Documentar em `docs/deployment.md`**

Acrescentar seção:

```markdown
## Broker do relay — smoke obrigatório antes de multi-worker

Pré-condição para rodar a web com >1 worker/processo em modo remoto:
`JURIS_RELAY_BROKER=redis://...` configurado e o smoke abaixo verde
(agente conectado num worker atendendo request que entra por outro):

    docker run -d --name smoke-redis -p 6399:6379 redis:7-alpine
    JURIS_RELAY_BROKER=redis://127.0.0.1:6399/0 uv run python scripts/smoke_relay_broker.py

Sem broker, o RelayHub falha fechado por design (single-worker ou
JURIS_RELAY_STICKY=1 são as alternativas).
```

- [ ] **Step 5: Atualizar o doc de sprints**

Em `docs/engineering_sprints.md`, seção "Próxima sequência proposta", item Sprint 8: trocar "Falta smoke com Redis real e dois workers antes de habilitar em produção." por "**Concluído (2026-07-05):** smoke real em `scripts/smoke_relay_broker.py` (Redis 7 + 2 workers + dedupe de request_id); runbook em docs/deployment.md."

- [ ] **Step 6: Limpeza + gates + commit**

```bash
docker rm -f smoke-redis
uv run pytest -q && uv run ruff check . && uv run mypy src/juris
git add scripts/smoke_relay_broker.py docs/deployment.md docs/engineering_sprints.md
git commit -m "test(relay): smoke do broker Redis com 2 workers fecha o gate do Sprint 8"
git push origin main
```

---

## Trilha H — Dependências humanas (não-código; nenhuma task acima bloqueia nelas)

Ordem sugerida — H1 destrava H2, que destrava H3:

- **H1 — Parear o agente A3 no Mac Mini** (`blackcube-pilot.md` §7): plugar o token físico no Mini, instalar módulo PKCS#11, baixar/parear o agente pelo console, gerar `agents.json` e reexecutar `golive_mac_mini.sh`. Até lá o site roda agent-free (§6). *Esforço: ~1h presencial.*
- **H2 — Rodar o piloto real** (`pilot_runbook.md`): 5–10 casos com MNI real + LLM, registrar feedback na aba Piloto, gerar `juris pilot summary` / `juris pilot report -o piloto.md`. **É o deliverable que prova valor pago** — nenhuma task de código substitui. Preencher antes o pacote LGPD (`docs/compliance/`: DPA/ROPA/RIPD). *Esforço: distribuído em 1–2 semanas de uso real.*
- **H3 — Decisão de ToS para inteiro teor** (`data/tos_compliance_log.md`): escolher a fonte (mais simples: acórdãos que o escritório já possui; alternativa: LexML/dados abertos). Destrava `JURIS_TST_INTEIRO_TEOR_ENABLED` (retunar seletores contra amostra real — `escavacao/tst.py:30`) e o destino dos ingesters gated. *Decisão jurídica/comercial.*
- **H4 — Apple Developer ID (US$ 99/ano) e, se for atacar Windows a sério, certificado Authenticode**: pré-requisito da Trilha C1. Sem isso o Gatekeeper/SmartScreen continuam sendo o maior atrito de onboarding do advogado. *Decisão de compra.*
- **H5 — Criar o monitor externo de uptime** (Task 6 Step 6): UptimeRobot free com https://causia.com.br/ e /api/health, alerta por e-mail. *~10 min.*

## Trilha C — Trabalho maior: planos próprios (NÃO iniciar junto; um plano por item)

Cada item abaixo merece brainstorming + plano dedicado quando for priorizado:

- **C1 — Assinatura e notarização do agente + auto-update efetivo.** Depende de H4. Escopo: `codesign` + `notarytool` + `stapler` no `agent-release.yml` (macOS), Authenticode (Windows), e implementar o swap onedir real do auto-update (`agent/update.py:31-33` — hoje valida manifesto Ed25519 mas não aplica `.dmg`/`.zip`; lembrar do follow-up documentado: não reusar basenames v1, skew exe/_internal). É o desbloqueio de adoção número 1 pós-piloto.
- **C2 — Hardening dos catches largos no caminho crítico.** 109 `# noqa: BLE001`; começar pelos 9 de `api/local_agent.py` (ponte do token A3 — falha silenciosa ali = petição não protocolada sem alarme): tipar exceções, emitir evento de audit + alerta em vez de retornar `None/[]`. Depois `agents/drafter.py` (6) e `web/app.py` (5). Requer leitura sítio-a-sítio; ganho direto de confiabilidade jurídica.
- **C3 — Quebrar os módulos-Deus.** `web/static/index.html` (3715 — extrair JS para módulos em `/static/`, atenção aos hashes de script na CSP), `cli/main.py` (3369 — mover comandos para `cli/commands/` já existente), `web/app.py` (1616 — APIRouter por domínio). Mecânico mas grande; fazer por fatias com a suíte verde entre cada uma.
- **C4 — Qdrant em produção.** Só quando o volume justificar sair do SQLite FTS+HNSW: comando de migração reingerindo pontos legados com payload de tenant (hoje falham fechado por design — `vector_store.py:156`), smoke de isolamento entre 2 tenants, e runbook. Não fazer antes: o piloto não precisa.
- **C5 — Sprint 12: entendimento de documento** (acórdão/decisão/intimação recebidos → fatos estruturados para análise/minuta/corpus). Está explicitamente em "What NOT to build now" do CLAUDE.md (Fase 2) — priorizar somente com evidência do piloto (H2) apontando que é a próxima dor real.
- **C6 — Faxina da ingestão.** Decidir por módulo: 6 stubs gated por ToS ficam (documentam intenção + gate) até H3; já os fetchers vivos órfãos (`stf_sumulas.py`, `stf_repercussao.py`, `stj_repetitivos.py`, `court_noticias.py`, `legal_basis.py`, `pdf_peticoes.py` — 0 referências fora de `ingestion/`) duplicam o pipeline de seeds (`scripts/extract_*.py` → `data/corpus/*.json` → registry): ou cabear na registry sob flag com job de refresh da espinha, ou mover para `Quarantine/`. Recomendação: cabear `stf_sumulas`/`stj_repetitivos` como refresh trimestral da espinha; quarentenar o resto.

---

## Self-review (feito em 2026-07-05)

- Cobertura: os 14 achados da tabela mapeiam para Task 1–8, Trilha H ou Trilha C — sem órfãos.
- Sem placeholders nos steps das Tasks 1–8: código completo onde há código; onde o passo depende de ler API interna primeiro (Task 8 Step 1, Task 7 Step 3), o passo diz exatamente o que ler e o que extrair.
- Consistência de tipos: `PreflightCheck(name, passed, severity, message)` conforme `preflight.py:58`; `dev_default_leaks()` usada igual nos Steps 1/3/5 da Task 2; portas/labels do Mac Mini (8100, `com.causia.*`) conforme `blackcube-pilot.md`.
- Riscos apontados: Task 2 não pode ser o validador literal do PR #3 (derrubaria o piloto SQLite — por isso strict é opt-in); Task 7 verifica a semântica de agregação antes de decidir `passed=False`; Task 3 só roda depois de 1–2 (PRs fechados).
