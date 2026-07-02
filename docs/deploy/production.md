# Produção multi-tenant — configuração + onboarding

O maior risco em produção não é falta de feature, é **má configuração** que derruba
silenciosamente o isolamento ou o split-trust. Este runbook fecha isso: valide com
`juris doctor` antes de subir, e onboarde cada escritório com o checklist abaixo.

## 1. Configuração segura (variáveis de ambiente)

```bash
# Fail-closed: sem isso o orquestrador aceita o tenant "public" (aberto).
# `ENVIRONMENT=prod` também força esse comportamento no runtime.
export ENVIRONMENT=prod
export JURIS_REQUIRE_TENANTS=1

# Registro de tenants — {tenant_id: api_key}. Guarde SÓ o hash (nunca a chave crua).
export JURIS_TENANTS_FILE=/etc/juris/tenants.json

# Split-trust remoto (Fase 2): cada escritório → seu próprio agente.
export JURIS_AGENT_MODE=remote
export JURIS_AGENTS_FILE=/etc/juris/agents.json

# Storage/saída controlados pelo servidor (isolados por tenant automaticamente).
export JURIS_HOME=/var/lib/juris
export JURIS_OUT_ROOT=/var/lib/juris/out
export JURIS_BACKUP_DIR=/var/backups/juris

# Segredo para assinar a âncora HMAC dos audit logs. Gere com:
# python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
export JURIS_AUDIT_HMAC_KEY=<segredo-longo>

# Opcional: trust bundle explícito para o caminho MNI mTLS via OpenSSL/PKCS#11.
# Se omitido, o OpenSSL usa a store padrão e ainda verifica host/cadeia.
export MNI_SERVER_CA_PEM_PATH=/etc/ssl/certs/ca-certificates.crt
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

Antes de manutenção no Mac do operador, rode também
`scripts/backup_local_engine.sh` para arquivar as peças gitignored do engine local
(`ranking.py` e testes privados). Ver
`docs/deploy/local-engine-backup.md`.

Antes de deploy, migração de corpus ou manutenção do agente, rode o backup
operacional dos artefatos sensíveis:

```bash
juris backup create
shasum -a 256 -c "$JURIS_BACKUP_DIR"/juris-backup-*.tar.gz.sha256
```

O backup cobre `JURIS_HOME`, `JURIS_OUT_ROOT`, `repertory.db`, audit logs e recibos
de protocolo, com `manifest.json` e SHA-256 por arquivo. O restore é sempre feito
em uma árvore de inspeção:

```bash
juris backup restore /var/backups/juris/juris-backup-YYYYMMDDTHHMMSSZ.tar.gz /tmp/juris-restore
```

Runbook completo: `docs/deploy/backup-restore.md`.

Para encerramento de piloto ou pedido de apagamento LGPD, use primeiro o dry-run
e depois a execução confirmada:

```bash
juris tenant erase-data escritorio-alfa
juris tenant erase-data escritorio-alfa --execute --confirm ERASE-escritorio-alfa
```

Runbook completo: `docs/deploy/data-erasure.md`.

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
   configure `JURIS_BROWSER_BRIDGE_URL` e `JURIS_BROWSER_BRIDGE_TOKEN`;
   `GET /api/ai-session` deve reportar `mode: browser_session`, e
   `GET /api/health?deep=1` deve validar o token do bridge.
6. **Health operacional**
   `GET /api/health?deep=1` (X-API-Key do escritório) → `status: ok` com todos os
   componentes (config/storage/corpus/agent/relay/browser_bridge) verdes.

## 4. Smoke test de isolamento

Antes de liberar um segundo tenant, confirme que **A não enxerga B**. Automatizado em
`tests/unit/web/test_tenant_isolation.py` (processos, filing status, connect jobs). Rode:

```bash
uv run pytest tests/unit/web/test_tenant_isolation.py -q
```

Manualmente: com a chave do escritório B, `GET /api/processos`, `/api/filing/status` e
`/api/connect/<job-do-A>` devem retornar vazio / 404 para qualquer dado do escritório A.

## 5. Health por tenant (operacional contínuo)

`GET /api/health` (autenticado) retorna, para o tenant do request. Por padrão usa
`deep=true`: testa alcance real do agente remoto e do browser bridge. Use
`?deep=false` apenas para checks rápidos de binding/configuração.

| Componente | O que verifica |
|---|---|
| `config` | tenant reconhecido no registry |
| `storage` | banco do tenant acessível + diretório de filing gravável |
| `corpus` | repertório com chunks suficientes (`read_status`) |
| `agent` | binding presente e, em modo deep, agente alcançável + token A3 conectado |
| `relay` | canal reverso conectado ou transporte direto em uso |
| `browser_bridge` | URL válida e, em modo deep, token/bridge respondendo |

`status: degraded` quando qualquer componente falha. Monitore por tenant.

Para visão administrativa consolidada, configure `JURIS_ADMIN_TOKEN` e use
`GET /api/admin/health?deep=1` com header `x-admin-token`.

## 6. Rotina noturna e entrega de alertas

O comando operacional é:

```bash
juris overnight --all-tenants --send-alerts
```

Em produção split-trust, ele percorre todos os tenants configurados em
`JURIS_TENANTS_FILE`, usa o banco isolado de cada escritório e roteia leitura MNI
para o agente remoto daquele tenant. O orquestrador não recebe CPF, senha nem PIN.
Para uso co-localizado/single-tenant, remova `--all-tenants` e informe
`--cpf <cpf-do-advogado>` como no fluxo local.

Ele executa sync diferencial, análise, cálculo de prazos e entrega de alertas
pendentes por email. Para produção em macOS, use o template
`docs/deploy/com.juris.overnight.plist`:

```bash
cp docs/deploy/com.juris.overnight.plist ~/Library/LaunchAgents/
open ~/Library/LaunchAgents/com.juris.overnight.plist   # preencher REPLACE_*
launchctl load ~/Library/LaunchAgents/com.juris.overnight.plist
launchctl start com.juris.overnight
tail -f /tmp/juris-overnight.err /tmp/juris-overnight.log
```

Configure SMTP antes de habilitar o job:

```bash
export ALERT_SMTP_HOST=smtp.example.com
export ALERT_SMTP_PORT=587
export ALERT_FROM_ADDRESS=juris@example.com
export ALERT_TO_ADDRESSES=advogado@example.com
```

Se o nightly gerar alertas críticos e o SMTP estiver ausente, o comando falha
com código `2`; isso é intencional para não transformar prazo crítico em alerta
silenciosamente perdido. O comando manual `juris alerts send` continua disponível
para reenviar pendências.

## 7. Escala horizontal

O canal reverso do agente ainda mantém conexões em memória por processo. Em
produção multi-worker, use uma destas opções antes de subir mais de um worker:

- single-worker: `WEB_CONCURRENCY=1` ou `JURIS_WEB_WORKERS=1`;
- sticky routing por tenant/agente e `JURIS_RELAY_STICKY=1`;
- broker Redis via `JURIS_RELAY_BROKER=redis://...`.

Para rate limit distribuído, configure `JURIS_RATE_LIMIT_REDIS_URL` ou declare
rate limit no proxy com `JURIS_RATE_LIMIT_PROXY=1`. O app mantém três buckets:
`JURIS_API_RATE_LIMIT_PER_MINUTE` por API key para rotas comuns,
`JURIS_API_EXPENSIVE_RATE_LIMIT_PER_MINUTE` para demo, busca/reingestão de corpus
e protocolo, e `JURIS_WS_AGENT_RELAY_RATE_LIMIT_PER_MINUTE` por tenant/IP para o
handshake de `/ws/agent-relay`. `juris doctor` denuncia multi-worker inseguro e
avisa quando a quota ainda é process-local.
