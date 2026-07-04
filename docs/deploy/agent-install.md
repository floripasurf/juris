# Installing the juris local agent (split-trust, ADR-0015)

The **local agent** runs on the lawyer's machine — where the A3 token is plugged
in. It holds every secret (token PIN, PJe senha) and exposes only a **loopback**
WebSocket/reverse channel the cloud orchestrator talks to. The orchestrator never
receives a token, PIN or password. This runbook ties together: serve → relay →
native host → extension.

## 0. Prerequisites

- `juris` checked out + `uv sync` done on the lawyer's machine.
- The A3 token driver (PKCS#11 module, e.g. SafeNet eToken) installed.
- Chrome, for the browser-session AI (optional).

## 1. Pair the orchestrator and the agent

On either machine:

```bash
uv run juris agent pair
```

It prints a token. Use the **same value** on both sides:

- **Agent** (this machine): `JURIS_AGENT_TOKEN=<token>`
- **Orchestrator**: `JURIS_AGENT_MODE=remote` + `JURIS_AGENTS_FILE=<agents.json>`,
  with the tenant entry pointing to `ws://<reachable-agent-address>:8765` and the
  same token.

> **Reachability:** the agent binds **127.0.0.1 only**, so `<reachable-agent-address>`
> is *not* the lawyer's public IP. See **§7 Connectivity** — co-located it's
> `127.0.0.1`; for a real cloud orchestrator it's the local end of a secure tunnel.

For the anonymous Causia trial, the orchestrator issues this token for the trial
tenant and shows a command like:

```bash
JURIS_AGENT_TOKEN=<token> juris agent connect-relay wss://causia.com.br/ws/agent-relay --tenant <trial_id>
```

That mode uses the reverse channel: the agent dials out to Causia, so no inbound
port is opened on the lawyer's machine.

## 2. Caminho empacotado (instalador — recomendado)

Desde o CI de release (`.github/workflows/agent-release.yml`), o agente é
distribuído como binário empacotado (PyInstaller onedir) para macOS e Windows —
ninguém mais precisa clonar o repo, rodar `uv sync` ou editar plist à mão. O
console oferece o download direto (Acervo → "Baixar o agente").

**O que o instalador faz:**

- **macOS** (`CausiaAgente.dmg`): arraste "Causia Agente.app" para Aplicativos.
  Na primeira execução do binário empacotado (`sys.frozen` + macOS), o próprio
  agente grava `~/Library/LaunchAgents/com.causia.agent.plist` (a partir do
  template embutido em `Contents/Resources/`), roda `launchctl load -w` e
  encerra o processo atual — o launchd assume a partir daí. O LaunchAgent usa
  `RunAtLoad`+`KeepAlive` (sobe no login e reinicia se cair) e escreve logs em
  `~/Library/Logs/causia-agent.log` (stdout) e `causia-agent.err` (stderr) —
  nunca em `/tmp`. Ver `_ensure_launch_agent` em `src/juris/agent/main.py`.
- **Windows** (`CausiaAgente-win.zip`): `install.bat` copia o binário para
  `%LOCALAPPDATA%\CausiaAgente`, registra autostart via
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (sem admin, sem serviço)
  e já sobe o agente. `uninstall.bat` reverte tudo (`taskkill`, remove a chave
  de registro, apaga a pasta).
- Em ambos os casos o agente só liga **loopback** (`127.0.0.1:8765`) e **nunca
  abre porta de entrada** — não precisa mexer em firewall.

**Kill-switch** (`JURIS_AGENT_NO_LAUNCHD`): qualquer valor não-vazio nessa env
var pula a instalação do LaunchAgent inteira (ver `_ensure_launch_agent`).
Usado por smokes/CI para rodar o binário empacotado sem grudar um serviço
persistente na máquina de dev — é assim que se valida o binário localmente:

```bash
JURIS_AGENT_NO_LAUNCHD=1 JURIS_AGENT_TOKEN=teste JURIS_AGENT_PORT=8768 ./dist/causia-agent/causia-agent &
sleep 4 && curl -s http://127.0.0.1:8768/health   # {"status":"ok",...}
kill %1
```

**Auto-update** (`src/juris/agent/update.py`): a cada start, o agente consulta
o manifesto assinado publicado em `GET /api/agent/latest` (servido a partir de
`JURIS_AGENT_DIST_DIR/agent-latest.json` — ver `src/juris/web/agent_dist.py`).
O manifesto (`{version, sha256, url, signature_alg, signature}`) é assinado
Ed25519 pelo CI de release; a chave pública fica **embutida no binário** via
`src/juris/agent/_release_meta.py` (gerado em build-time por
`scripts/write_release_meta.py`, nunca commitado — está no `.gitignore`), lida
em tempo de chamada por `_resolve_public_key()`. Um servidor comprometido não
consegue empurrar binário malicioso: a chave privada só existe nos secrets do
CI (`AGENT_UPDATE_PRIVKEY`), nunca no servidor nem no cliente.

**v1 é intencionalmente conservador**: a `url` do manifesto aponta para o
instalador (`.dmg`), não para o binário cru. `_is_raw_binary_url()` só permite
a troca automática quando o último segmento da URL é exatamente `causia-agent`
(macOS/Linux) ou `causia-agent.exe` (Windows) — hoje isso nunca acontece, então
o auto-update **verifica a assinatura mas não troca nada** (no-op seguro). O
swap real do binário onedir é um follow-up planejado (ver checklist do
primeiro release, no fim deste documento).

**Esquema de versão**: `AAAA.M.D.seq` (ano completo, mês e dia sem zero à
esquerda, sequência do dia — permite mais de um release no mesmo dia). A tag
que dispara o CI é `agent-vAAAA.M.D.seq` (ex.: `agent-v2026.7.4.1`); o job
extrai a versão com `VER="${GITHUB_REF_NAME#agent-v}"` e usa a mesma string em
três lugares que precisam bater exatamente: `AGENT_VERSION` embutido,
`CFBundleVersion` do `.app`/`.dmg` e `version` do manifesto assinado — essa
igualdade é o que impede o agente de entrar em loop de re-update contra a
própria versão.

## 3. Caminho manual — rodar como serviço (macOS launchd, técnicos)

```bash
cp docs/deploy/com.juris.agent.plist ~/Library/LaunchAgents/
# edit it: ProgramArguments, WorkingDirectory, JURIS_AGENT_TOKEN, optional local
#          CPF/SENHA/PIN, PKCS#11 path, and owner-only log paths
mkdir -p ~/juris-pilot/logs && chmod 700 ~/juris-pilot/logs
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.juris.agent.plist
```

The agent binds **127.0.0.1 only** (`juris agent serve` rejects any other host).
Logs must stay in an owner-only directory, not `/tmp`. Validate it:

```bash
uv run juris agent health --url ws://127.0.0.1:8765
# → Agente vX.Y — token: conectado; cert válido até: AAAA-MM-DD
```

## 4. Native messaging host (browser-session AI)

Register the host so Chrome can launch it (see `docs/browser-extension/`):

```bash
# com.juris.host.json → ~/Library/Application Support/Google/Chrome/NativeMessagingHosts/
# set "path" to the juris native-host binary and "allowed_origins" to the extension id
```

## 5. Chrome extension

```bash
cd docs/browser-extension && npm install && npm run package
# chrome://extensions → Developer mode → Load unpacked (this folder)
```

Log into Claude.ai/ChatGPT and disable training/history (onboarding §3.5).

## 6. Verify end to end

From the orchestrator (remote mode), a `juris demo <cnj> --source mni` read — or the
web "connect" (including the **nightly sync**) — now flows: orchestrator →
the tenant's `JURIS_AGENTS_FILE` binding (loopback or tunnel, §7) → token op at the agent → reply,
with **no PIN/senha leaving the agent**. `scripts/remote_smoke.py` proves the wiring
over a real socket without a token.

## 7. Connectivity (cloud → agent)

The agent binds **127.0.0.1 only** — never the public network. So a cloud
orchestrator **cannot** reach `ws://<lawyer-public-ip>:8765` directly: the home
machine is behind NAT/firewall, and exposing the port would defeat the loopback
guarantee. Bridge the gap one of these ways:

- **Co-located (Phase 1, today).** Orchestrator + agent on the same machine (the
  firm's Mac Mini). In `JURIS_AGENTS_FILE`, set the firm's `url` to
  `ws://127.0.0.1:8765`. No tunnel needed — this is the pilot setup and what
  `scripts/remote_smoke.py` exercises.
- **Secure tunnel (multi-tenant).** Run a tunnel that maps a private cloud-side
  hostname to the agent's loopback port, authenticated and encrypted — e.g.
  **Cloudflare Tunnel** (the daemon runs on the lawyer's machine and dials *out*, so
  no inbound port is opened). The orchestrator then uses the tunnel hostname as
  the tenant binding URL. The pairing token still gates every request.
- **Reverse channel (trial/default SaaS).** The **agent dials out** to the cloud
  relay (`/ws/agent-relay`) and the orchestrator routes MNI/signing/filing through
  that live connection. This removes the inbound-NAT problem and is the default
  path for anonymous Causia trials.

In every case the security properties hold: loopback bind, paired token, secrets
resolved at the agent.

## Security checklist

- [ ] Agent bound to 127.0.0.1 (never 0.0.0.0).
- [ ] `JURIS_AGENT_TOKEN` set; orchestrator's tenant binding token matches.
- [ ] Token PIN / PJe senha only in the agent's env — never in the orchestrator.
- [ ] `juris file` / `/api/connect` in remote mode do **not** prompt for or store PIN/senha.
- [ ] Cloud → agent only via co-located loopback, secure tunnel, or reverse channel
      (§7) — never a public-facing agent port.

## Checklist do primeiro release real (`agent-v*`)

Antes de empurrar a primeira tag de release (o CI de `.github/workflows/agent-release.yml`
só publica algo de verdade depois disso):

1. **Gerar o par de chaves Ed25519 offline** e registrar os secrets do repo
   (comandos exatos no cabeçalho do próprio workflow):
   ```bash
   uv run python -c "
   from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
   from cryptography.hazmat.primitives import serialization as s
   k = Ed25519PrivateKey.generate()
   open('agent_update_priv.pem', 'wb').write(
       k.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption())
   )
   print(k.public_key().public_bytes(s.Encoding.PEM, s.PublicFormat.SubjectPublicKeyInfo).decode())
   "
   gh secret set AGENT_UPDATE_PRIVKEY < agent_update_priv.pem
   gh secret set AGENT_UPDATE_PUBKEY   # colar a PEM pública impressa acima
   # apagar agent_update_priv.pem da máquina local depois de guardar num cofre.
   ```
2. **Push da tag**: `git tag agent-v<AAAA.M.D.seq> && git push origin agent-v<AAAA.M.D.seq>`.
3. **Conferir na 1ª execução** (workflow `agent-release` no Actions):
   - **(i)** o passo "Assert `_release_meta` válido" passou **nos dois runners**
     (macOS e Windows) — se falhar num deles, esse binário saiu sem auto-update.
   - **(ii)** o Release publicado tem **exatamente 3 assets**: `CausiaAgente.dmg`,
     `CausiaAgente-win.zip`, `agent-latest.json`.
   - **(iii)** **baixar o binário buildado** (não só confiar no assert do CI) e
     confirmar que ele importa `_release_meta` de verdade — isto é, que o
     auto-update está **ativo de verdade** no cliente, não só que o job de
     build passou:
     ```bash
     JURIS_AGENT_NO_LAUNCHD=1 ./causia-agent &   # onedir extraído do .dmg/.zip
     sleep 4 && curl -s http://127.0.0.1:8765/health
     # não deve haver stacktrace de import em _release_meta nos logs
     ```
   - **(iv)** **layout do `.zip` Windows**: extraia e confira que a raiz tem
     `causia-agent/` (pasta, com `causia-agent.exe` + `_internal/` dentro) e,
     soltos ao lado, `install.bat`, `uninstall.bat`, `LEIA-ME.txt` — é o
     contrato que `install.bat` (`%~dp0causia-agent`) espera.
   - **(v)** **copiar `agent-latest.json`** para `JURIS_AGENT_DIST_DIR` do Mac
     Mini (o endpoint público `GET /api/agent/latest` serve dali — ver
     `src/juris/web/agent_dist.py`); sem isso o endpoint responde 404 e o
     console não mostra a versão publicada.
   - **(vi)** **smoke com o token A3 real**, rodado pelo dono contra
     `causia.com.br` com o token físico pareado:
     ```bash
     JURIS_AGENT_TOKEN=<pareado> ./dist/causia-agent/causia-agent &
     sleep 4
     curl -s -H "X-API-Key: <chave>" https://causia.com.br/api/agent-health \
       | python3 -c "import json,sys;print(json.load(sys.stdin)['status'])"
     kill %1
     ```
     Esperado: `ready` (o agente empacotado, sem repo/venv, fecha a cadeia split-trust).

**Follow-ups conhecidos** (não bloqueiam o 1º release, mas ficam documentados
para não se perder):

- **Assinatura de código**: macOS Developer ID (`codesign` + `notarytool`) e
  Windows Azure Trusted Signing (mais barato que certificado EV) — reduz o
  aviso de "desenvolvedor não identificado"/SmartScreen. Até lá, os passos de
  "abrir mesmo assim" no LEIA-ME e neste runbook seguem necessários.
- **Swap real de onedir**: hoje o auto-update é um no-op seguro (v1 só verifica
  a assinatura, nunca troca o binário — ver §2). O swap de verdade precisa
  apontar a `url` do manifesto para um asset avulso com o basename cru exato
  (`causia-agent` / `causia-agent.exe`) em vez do `.dmg`/`.zip` — o workflow
  atual não publica esse asset avulso.
- **`version_info.txt` hardcoded**: `packaging/agent/version_info.txt` fixa
  `filevers`/`ProductVersion` em `2026.7.4.1` — o "Detalhes" do `.exe` no
  Explorer do Windows pode divergir da tag real até esse arquivo virar gerado
  (mesmo padrão do `_release_meta.py`).
