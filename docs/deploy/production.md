# Produção multi-tenant — configuração + onboarding

O maior risco em produção não é falta de feature, é **má configuração** que derruba
silenciosamente o isolamento ou o split-trust. Este runbook fecha isso: valide com
`juris doctor` antes de subir, e onboarde cada escritório com o checklist abaixo.

## 1. Configuração segura (variáveis de ambiente)

```bash
# Fail-closed: sem isso o orquestrador aceita o tenant "public" (aberto).
export JURIS_REQUIRE_TENANTS=1

# Registro de tenants — {tenant_id: api_key}. Guarde SÓ o hash (nunca a chave crua).
export JURIS_TENANTS_FILE=/etc/juris/tenants.json

# Split-trust remoto (Fase 2): cada escritório → seu próprio agente.
export JURIS_AGENT_MODE=remote
export JURIS_AGENTS_FILE=/etc/juris/agents.json

# Storage/saída controlados pelo servidor (isolados por tenant automaticamente).
export JURIS_HOME=/var/lib/juris
export JURIS_OUT_ROOT=/var/lib/juris/out
```

Permissões (segredos são owner-only):

```bash
chmod 600 /etc/juris/tenants.json /etc/juris/agents.json
chmod 700 /var/lib/juris
```

### `JURIS_TENANTS_FILE` — chaves **hashadas**

```json
{
  "escritorio-alfa": "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "escritorio-beta": "sha256:2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae"
}
```

Gere cada entrada (a chave crua é mostrada **uma vez** — entregue ao escritório):

```bash
juris tenant new escritorio-alfa      # imprime a chave crua + a entrada (hash) p/ o arquivo
juris tenant hash-key <chave-existente> # só o hash, se já tiver a chave
```

O escritório envia a chave crua em cada request: `X-API-Key: <chave-crua>`.

### `JURIS_AGENTS_FILE` — um agente por escritório

```json
{
  "escritorio-alfa": { "url": "wss://alfa.tunnel.juris.dev/ws/agent-relay", "token": "<token-pareado>" },
  "escritorio-beta": { "url": "wss://beta.tunnel.juris.dev/ws/agent-relay", "token": "<token-pareado>" }
}
```

## 2. Validação pré-go-live

```bash
juris doctor                 # valida require_tenants, tenants file + hashes, bindings, permissões
juris doctor --tenant escritorio-alfa   # + health operacional do tenant
```

`juris doctor` sai com código ≠ 0 se qualquer verificação bloqueante falhar — **coloque
no pipeline de deploy**. Verificações: `require_tenants`, `tenants_file`, `hashed_keys`,
`agent_bindings` (remoto), `storage_private`, permissões dos segredos.

## 3. Onboarding de um escritório

1. **Gerar tenant**
   `juris tenant new escritorio-alfa` → adicione a entrada (hash) ao `JURIS_TENANTS_FILE`;
   entregue a chave crua ao escritório.
2. **Parear o agente** (na máquina do advogado — ver `docs/deploy/agent-install.md`)
   `juris agent pair` → configure `JURIS_AGENT_TOKEN` no agente e o binding no
   `JURIS_AGENTS_FILE`. Para deploy não-co-localizado, o agente disca pra fora:
   `juris agent connect-relay wss://<orquestrador>/ws/agent-relay --tenant escritorio-alfa`.
3. **Testar MNI** (leitura)
   `juris demo <cnj> --source mni --cpf <cpf>` (co-localizado) — em remoto o agente
   resolve o CPF; deve retornar movimentos sem tocar no token na nuvem.
4. **Testar filing (dry-run)** — sem assinar nem contatar o tribunal:
   `POST /api/filing/dry-run` (X-API-Key do escritório) → cadeia de custódia dos hashes.
5. **Testar browser session** (ADR-0018), se usado:
   configure `JURIS_BROWSER_BRIDGE_URL`; `GET /api/ai-session` deve reportar
   `mode: browser_session`.
6. **Health operacional**
   `GET /api/health` (X-API-Key do escritório) → `status: ok` com todos os componentes
   (config/storage/corpus/agent/browser_bridge) verdes.

## 4. Smoke test de isolamento

Antes de liberar um segundo tenant, confirme que **A não enxerga B**. Automatizado em
`tests/unit/web/test_tenant_isolation.py` (processos, filing status, connect jobs). Rode:

```bash
uv run pytest tests/unit/web/test_tenant_isolation.py -q
```

Manualmente: com a chave do escritório B, `GET /api/processos`, `/api/filing/status` e
`/api/connect/<job-do-A>` devem retornar vazio / 404 para qualquer dado do escritório A.

## 5. Health por tenant (operacional contínuo)

`GET /api/health` (autenticado) retorna, para o tenant do request:

| Componente | O que verifica |
|---|---|
| `config` | tenant reconhecido no registry |
| `storage` | banco do tenant acessível + diretório de filing gravável |
| `corpus` | repertório com chunks suficientes (`read_status`) |
| `agent` | binding presente (remoto) / co-localizado |
| `browser_bridge` | URL do bridge válida (se configurado) |

`status: degraded` quando qualquer componente falha. Monitore por tenant.
