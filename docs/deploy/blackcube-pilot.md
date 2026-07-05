# Piloto online — causia.com.br (Mac Mini + Cloudflare Tunnel)

> **Domínio de produção (02/07/2026):** o produto chama-se **Causia** e vive em
> `causia.com.br` + `app.causia.com.br` (zona própria no Cloudflare; registros
> CNAME → `<tunnel-id>.cfargotunnel.com`, proxied). `juris.blackcube.dev` foi o
> endereço de validação e pode ser aposentado após a transição. Para rotear DNS
> de uma zona nova via `cloudflared tunnel route dns`, o `cert.pem` precisa ter
> sido autorizado NAQUELA zona — senão ele cria um registro-lixo na zona antiga
> (`dominio.com.br.zonaantiga.dev`); prefira criar o CNAME no dashboard.

Publica o console web para o advogado usar do navegador dele, sem abrir porta no
Mac Mini: `juris web` escuta só em 127.0.0.1 e o `cloudflared` faz o caminho de
saída. Controle de acesso = **X-API-Key por tenant** (auth fail-closed do app) +
CSP/headers/HSTS + WAF Cloudflare. (Cloudflare Access foi removido — ver §3.)

Pré-requisito de postura: este runbook assume a configuração fail-closed de
`docs/deploy/production.md` §1 (`ENVIRONMENT=prod`, `JURIS_REQUIRE_TENANTS=1`,
chaves hashadas). Antes de caso real com dado de cliente, preencher o pacote
LGPD em `docs/compliance/` (DPA/ROPA/RIPD).

## 0. Go-live — migração MacBook → Mac Mini (turnkey)

> **FEITO (03/07/2026, via Tailscale ssh `raphaels-mac-mini` 100.77.76.64).**
> causia.com.br agora roda no **Mac Mini** (always-on). Detalhes reais da execução:
> - O Mac Mini é host compartilhado (finep/credito/leite/secont/escora via tunnels
>   próprios) — **porta 8000 já ocupada** pelo transparencia-es, então Causia usa
>   **porta 8100**.
> - Serviços launchd (padrão `com.<app>.*` do Mac Mini): **`com.causia.web`**
>   (8100, prod, `~/juris-pilot/`) e **`com.causia.tunnel`** (tunnel `juris`
>   49e67dad via `~/.cloudflared/config.causia.yml` → 8100). RunAtLoad+KeepAlive.
> - Dados migrados por rsync/Tailscale: `tenants.json`, `.hmac_key`, `home/`
>   (repertory.db com 1761 chunks do corpus TST, tenant dbs, audit). Sem
>   `agents.json` (agente A3 ainda não pareado — modo co-localizado até a §7).
> - Cutover: parado `com.cloudflare.juris` + `com.juris.web` no MacBook; conector
>   do Mac Mini reconectou limpo (4 conexões). Outros apps do Mac Mini intactos.
> - **Pendente:** parear o agente A3 no Mac Mini (§7) — precisa do token físico
>   plugado lá. Até então, use o caminho agent-free (§6).
>
> O texto abaixo é o procedimento genérico (para repetir/entender), com o script
> `scripts/golive_mac_mini.sh` automatizando a parte determinística.

**No Mac Mini**, com o layout `~/juris-pilot/` (mesma convenção do
`doctor_juris_pilot.sh`):

```bash
# 1) traga o código e rode o script (idempotente — pode repetir)
git clone --branch feat/mni-mtls-token <repo> ~/juris-pilot/app   # 1ª vez
sh ~/juris-pilot/app/scripts/golive_mac_mini.sh
# ele: sync, cria dirs 700, gera HMAC, escreve/instala o launchd da web,
#      e imprime o que falta (tenant, tunnel, agente). Rode de novo após criar
#      tenants.json / agents.json.

# 2) tenant do piloto (a chave crua aparece uma vez — entregue ao advogado)
cd ~/juris-pilot/app && uv run juris tenant new escritorio-piloto
printf '{ "escritorio-piloto": "sha256:<hash>" }' > ~/juris-pilot/tenants.json
chmod 600 ~/juris-pilot/tenants.json
sh ~/juris-pilot/app/scripts/golive_mac_mini.sh     # reexecuta → sobe a web
```

**Mover o tunnel do MacBook para o Mac Mini** (cutover):

```bash
# no MacBook: empacote as credenciais do tunnel 'juris'
cd ~/.cloudflared && tar czf ~/cf-juris.tgz cert.pem config.yml \
  49e67dad-57d2-4e84-a1d2-3d8baad4ddf3.json         # <TUNNEL_ID>.json
# copie cf-juris.tgz para o Mac Mini (AirDrop/scp), e no Mac Mini:
mkdir -p ~/.cloudflared && tar xzf ~/cf-juris.tgz -C ~/.cloudflared
sudo cloudflared service install && cloudflared tunnel info juris
# PARE o tunnel no MacBook (cutover limpo): launchctl bootout do cloudflared lá,
# ou desligue o serviço. O DNS já aponta para o tunnel 'juris' — nada muda na zona.
```

**Agente local A3 (co-localizado no Mac Mini)** — ver §7. Depois do agente:
gere `~/juris-pilot/agents.json` e reexecute o script (a web passa a `remote`,
escondendo CPF/PIN/senha no navegador).

**Validar:** `cd ~/juris-pilot/app && uv run juris doctor` e o smoke da §4.

## 1. Preparar o orquestrador no Mac Mini

> **Onde clonar (aprendido no deploy de validação):** o checkout do serviço
> NÃO pode ficar em `~/Desktop`, `~/Documents` ou `~/Downloads` — o TCC do
> macOS bloqueia essas pastas para processos launchd e o Python pendura num
> `open()` eterno, sem log. Clone para um caminho neutro (ex.:
> `~/juris-pilot/app`), separado do checkout de desenvolvimento.

```bash
git clone --branch <branch> <repo-dev-ou-remoto> ~/juris-pilot/app
cd ~/juris-pilot/app && uv sync --frozen

# tenant do escritório piloto (a chave crua aparece UMA vez — entregue ao advogado)
uv run juris tenant new escritorio-piloto      # → entrada hashada p/ tenants.json

mkdir -p <path>/juris-home
printf '%s\n' '{ "escritorio-piloto": "sha256:<hash>" }' > <path>/tenants.json
chmod 600 <path>/tenants.json

uv run juris doctor                             # valida a config antes de subir
```

Serviço launchd (web em **8000**; o agente local usa 8765):

```bash
cp docs/deploy/com.juris.web.plist ~/Library/LaunchAgents/
# editar: WorkingDirectory, JURIS_TENANTS_FILE, JURIS_HOME, JURIS_AUDIT_HMAC_KEY,
#         JURIS_AGENTS_FILE (um binding por tenant)
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.juris.web.plist
curl -s http://127.0.0.1:8000/api/health | head -c 200   # sanity local
```

Piloto split-trust co-localizado (ADR-0015): o agente com o token A3 roda **neste
mesmo Mac Mini** via `com.juris.agent.plist` (ver `agent-install.md`), mas o
orquestrador continua em `JURIS_AGENT_MODE=remote`. Com
`JURIS_REQUIRE_TENANTS=1`, configure `/path/agents.json` em vez do fallback global:

```json
{"escritorio-piloto":{"url":"ws://127.0.0.1:8765","token":"<token pareado>"}}
```

`chmod 600 /path/agents.json`. Assim a UI não pede CPF/PIN/senha no navegador; o
agente resolve tudo localmente e o tunnel publica apenas o console web.

## 2. Cloudflare Tunnel

```bash
brew install cloudflared
cloudflared tunnel login                        # abre o browser na conta blackcube.dev
cloudflared tunnel create juris
cloudflared tunnel route dns juris juris.blackcube.dev
```

`~/.cloudflared/config.yml`:

```yaml
tunnel: <TUNNEL_ID>
credentials-file: /Users/<user>/.cloudflared/<TUNNEL_ID>.json
ingress:
  - hostname: juris.blackcube.dev
    service: http://127.0.0.1:8000
  - service: http_status:404
```

```bash
sudo cloudflared service install                # launchd, sobe no boot
cloudflared tunnel info juris                   # confirma conector ativo
```

## 3. Acesso — auth própria do app (Cloudflare Access foi REMOVIDO)

> **Decisão (03/07/2026): produto PÚBLICO.** O Cloudflare Access chegou a ser
> criado via API, mas era incompatível com o modelo do produto: é um portão por
> cookie de navegador (SSO) e trancava (a) a landing pública de conversão e
> (b) o login por header `X-API-Key` — `/api/*` com chave válida voltava 302 para
> o login do Access porque o navegador do cliente não tinha sessão. A app Access
> `436a9177…` foi **deletada**; o controle de acesso é a **auth própria do app**:
> fail-closed por tenant (`JURIS_REQUIRE_TENANTS=1`), chave hashada, rate-limit,
> CSP/headers/HSTS e o WAF/bot-protection da Cloudflare na frente. Landing pública
> converte; cliente entra com a chave. **Não reative Access nestes hosts** sem antes
> resolver o conflito (ex.: Access só num host administrativo separado).

## 4. Smoke de go-live

```bash
# sem chave → 401 estruturado (fail-closed valendo na borda pública)
curl -s https://causia.com.br/api/workbench | grep tenant_invalid

# página pública (landing) abre sem auth
curl -s https://causia.com.br/ | grep -c "Começar teste anônimo"

# com a chave do tenant → 200
curl -s -H "X-API-Key: <chave-crua>" https://causia.com.br/api/workbench | head -c 120
```

No navegador: acessar `https://causia.com.br`, ver a landing pública; "Começar
teste anônimo" emite uma chave e entra, ou "Já tenho uma chave" → entrar com a
chave do escritório → Mesa de trabalho. Chave errada reabre o login com erro.

## 5. Operação

- Backup desde o dia 1: `docs/deploy/backup-restore.md` (dados reais de processo).
- Loop noturno/alertas: `com.juris.overnight.plist`.
- **Purge diário de trials expirados (`com.causia.purge`):** trial expirado perde
  ACESSO na hora (`tenants.json`), mas os DADOS (`juris.db`, artefatos, corpus)
  só são apagados por `juris tenant purge-expired`, que lê o ledger
  `pending-erasure.json` (ao lado de `JURIS_TENANTS_FILE`), varre `tenants.json`
  por trials ainda expirados-mas-presentes, e apaga cada tenant pendente com
  certificado (nunca apaga um tenant presente e não-expirado, mesmo que
  apareça, por engano, no ledger). Instalar:
  ```bash
  cp docs/deploy/com.causia.purge.plist ~/Library/LaunchAgents/
  # editar: os mesmos REPLACE_WITH_PATH_TO de com.causia.web (tenants.json,
  # agents.json, juris-home, out)
  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.causia.purge.plist
  ```
  Roda diariamente às 04:30 (`StartCalendarInterval`), chamando
  `~/juris-pilot/app/.venv/bin/juris tenant purge-expired --yes` com as mesmas
  env vars de `com.causia.web`. Testar manualmente com
  `juris tenant purge-expired --dry-run --json` antes de instalar o launchd.
  Certificados de erasure ficam em
  `${JURIS_HOME:-~/.juris}/compliance-erasure.jsonl` (mesmo arquivo do
  `erase-data` manual — ver `docs/deploy/data-erasure.md`; entradas obsoletas
  do ledger descartadas também deixam evento `tenant.erasure.stale-dropped` aí).
  Entradas `failed` permanentemente inválidas (ex.: id `public` ou malformado
  no ledger) mantêm o job em **exit 1 a cada noite por design** — isso sinaliza
  reparo manual, não retry: inspecione com
  `juris tenant purge-expired --dry-run --json` e edite/remova a entrada
  inválida direto no `pending-erasure.json` (mantenha chmod 600).
- **Backup diário automatizado (`com.causia.backup`):** roda
  `scripts/backup_daily.sh` às **03:45** (antes do purge das 04:30, para que um
  trial purgado seja capturado na íntegra naquela noite), grava
  `juris-backup-<ts>.tar.gz` + `.sha256` em `~/juris-pilot/backups/` (chmod 700,
  manifesto + SHA-256 por arquivo cobrindo `JURIS_HOME`, `JURIS_OUT_ROOT`,
  `repertory.db`, audit e recibos) e mantém os **14 mais recentes**; expirados
  vão para `backups/.expired/` (purge manual — nada é deletado pelo job). Instalar
  igual ao purge:
  ```bash
  cp docs/deploy/com.causia.backup.plist ~/Library/LaunchAgents/
  # editar: os mesmos REPLACE_WITH_PATH_TO de com.causia.web + JURIS_BACKUP_DIR e CAUSIA_APP_DIR
  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.causia.backup.plist
  ```
  Ajustar a retenção com `CAUSIA_BACKUP_KEEP` (default 14). Testar antes com
  `sh scripts/backup_daily.sh` manual e conferir que `juris backup restore`
  reidrata um `.tar.gz` num diretório temporário (`docs/deploy/backup-restore.md`).
  **Cópia offsite (recomendado):** `rsync` semanal do diretório `backups/` para o
  MacBook via Tailscale — o backup local não protege contra perda do próprio Mini.
- Logs: `<path>/logs/web.log` (dir **chmod 700**, nunca `/tmp` — pode conter
  contexto operacional). O access log do uvicorn fica **desligado** (registraria
  CNJ/termos de busca em texto puro); só habilite com `JURIS_WEB_ACCESS_LOG=1` se
  precisar depurar, e nunca em produção. `cloudflared` via
  `log show --predicate 'process == "cloudflared"' --last 1h`.
- Segurança de borda (automática no app): CSP com hash de script (sem
  `unsafe-inline`), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`,
  `Permissions-Policy` e HSTS em host público HTTPS. Fontes self-hosted
  (`/static/assets/fonts/`) — nenhuma chamada a Google Fonts. `/api/ai-session`
  e `/api/agent-mode` exigem chave de tenant.
- Health por tenant: `/api/health?deep=1` (com a chave) e `/api/admin/health`
  (com `JURIS_ADMIN_TOKEN`, se configurado).

## 6. Prova rápida do produto (sem token)

Antes do A3, valide o valor com o caminho agent-free: no console, empty-state da
Mesa → **"Explorar com dados de exemplo"** gera 6 artefatos de um caso fixture
(sem agente), com preview formatado e **Baixar .docx**. Serve para o advogado ver
o produto na primeira sessão enquanto o token não está configurado.

## 7. Agente local A3 (co-localizado no Mac Mini)

O agente é o guardião do token (ADR-0015): resolve CPF/senha PJe/PIN localmente
e expõe só um WebSocket em `127.0.0.1:8765`. Nada de segredo vai para a nuvem.
Detalhe completo em `docs/deploy/agent-install.md`; resumo do caminho
**recomendado** (instalador empacotado — o advogado instala sozinho, sem editar
plist nem abrir terminal):

1. **Token + driver**: plugue o e-CPF A3 e instale o módulo PKCS#11 (SafeNet/eToken).
2. **Instalar o agente**: no console (causia.com.br) → **Acervo → "Baixar o
   agente"** → escolha macOS ou Windows.
   - **macOS**: abra o `.dmg` e arraste "Causia Agente" para Aplicativos. Na
     **primeira vez**, clique com o botão direito em "Causia Agente" → Abrir →
     Abrir (o aviso de "desenvolvedor não identificado" é esperado — o app
     ainda não é assinado, ver `agent-install.md`). O agente instala sozinho o
     LaunchAgent (`com.causia.agent`, `RunAtLoad`+`KeepAlive`) na primeira
     execução e passa a subir sempre que a máquina liga — **sem `cp`/`launchctl`
     manual**.
   - **Windows**: baixe e extraia o `.zip`, rode `install.bat` (sem admin, sem
     porta de entrada). O SmartScreen pode avisar sobre `.exe` não assinado —
     "Mais informações" → "Executar assim mesmo".
3. **Parear pelo próprio console**: **Acervo → Conectar agente local**. O
   navegador fala com `http://127.0.0.1:8765` (loopback; CORS + Private Network
   Access já tratados) e configura CPF/PJe/PIN **direto no agente**, sem passar
   pelo servidor. Fallback "comando técnico" se o navegador não alcançar o agente.
4. **Ligar o modo remoto na web** (piloto co-localizado no Mac Mini): gere o
   binding do tenant e reexecute o go-live:
   ```bash
   printf '{"escritorio-piloto":{"url":"ws://127.0.0.1:8765","token":"<token pareado>"}}' \
     > ~/juris-pilot/agents.json && chmod 600 ~/juris-pilot/agents.json
   sh ~/juris-pilot/app/scripts/golive_mac_mini.sh   # web sobe em JURIS_AGENT_MODE=remote
   ```
   Com isso a UI para de pedir CPF/PIN/senha no navegador — o agente resolve tudo.
5. **Validar ponta a ponta**: `uv run juris consulta <cnj> --tribunal tjmg` (leitura
   MNI real via token) e, no console, gerar minuta com `source=mni`.

### Apêndice — instalação manual (técnicos)

Caminho anterior ao instalador empacotado, mantido para debug/CI ou para quem
prefere editar o plist à mão em vez de baixar o `.dmg`/`.zip`:

```bash
cp ~/juris-pilot/app/docs/deploy/com.juris.agent.plist ~/Library/LaunchAgents/
# edite: JURIS_AGENT_TOKEN (pareamento), JURIS_AGENT_CPF/SENHA/PIN, caminho PKCS#11
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.juris.agent.plist
uv run juris agent health --url ws://127.0.0.1:8765   # token conectado; cert válido
```
