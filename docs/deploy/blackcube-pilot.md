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
saída. Duas camadas de acesso: **Cloudflare Access** (e-mails autorizados) na
frente e a **X-API-Key por tenant** na aplicação (tela de login da SPA).

Pré-requisito de postura: este runbook assume a configuração fail-closed de
`docs/deploy/production.md` §1 (`ENVIRONMENT=prod`, `JURIS_REQUIRE_TENANTS=1`,
chaves hashadas). Antes de caso real com dado de cliente, preencher o pacote
LGPD em `docs/compliance/` (DPA/ROPA/RIPD).

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
#         JURIS_LOCAL_AGENT_TOKEN (pareado com com.juris.agent.plist)
launchctl load ~/Library/LaunchAgents/com.juris.web.plist
curl -s http://127.0.0.1:8000/api/health | head -c 200   # sanity local
```

Piloto co-localizado (Fase 1, ADR-0015): o agente com o token A3 roda **neste
mesmo Mac Mini** via `com.juris.agent.plist` (ver `agent-install.md`). O
orquestrador fala com ele por `ws://127.0.0.1:8765` — nada disso passa pelo tunnel.

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

## 3. Cloudflare Access (porta da frente)

No Zero Trust dashboard → **Access → Applications → Add → Self-hosted**:

- Application domain: `juris.blackcube.dev`
- Policy *Allow* → Include → Emails: o seu + o do advogado piloto
- Session duration: 24h

Enquanto a única credencial da aplicação é a API key, o Access garante que a
superfície pública nem chega a estranhos. **Pitfall (Fase 2):** quando um agente
remoto na máquina do advogado for conectar em `wss://juris.blackcube.dev/ws/agent-relay`,
ele não passa pelo login de browser do Access — criar um **service token** e uma
policy própria para o path `/ws/agent-relay` antes de sair do co-localizado.

## 4. Smoke de go-live

```bash
# sem chave → 401 estruturado (fail-closed valendo na borda pública)
curl -s https://juris.blackcube.dev/api/workbench | grep tenant_invalid

# página abre sem auth para renderizar o login
curl -s https://juris.blackcube.dev/ | grep -c login-overlay

# com a chave do tenant → 200
curl -s -H "X-API-Key: <chave-crua>" https://juris.blackcube.dev/api/workbench | head -c 120
```

No navegador: acessar, passar pelo Access, ver a tela **Acesso do escritório**,
entrar com a chave → Mesa de trabalho carrega. Chave errada deve reabrir o login
com mensagem de erro.

## 5. Operação

- Backup desde o dia 1: `docs/deploy/backup-restore.md` (dados reais de processo).
- Loop noturno/alertas: `com.juris.overnight.plist`.
- Logs: `/tmp/juris-web.log` e `cloudflared` via `log show --predicate 'process == "cloudflared"' --last 1h`.
- Health por tenant: `/api/health?deep=1` (com a chave) e `/api/admin/health`
  (com `JURIS_ADMIN_TOKEN`, se configurado).
