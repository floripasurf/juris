# Installing the juris local agent (split-trust, ADR-0015)

The **local agent** runs on the lawyer's machine — where the A3 token is plugged
in. It holds every secret (token PIN, PJe senha) and exposes only a **loopback**
WebSocket the cloud orchestrator talks to. The orchestrator never receives a token,
PIN or password. This runbook ties together: serve → pair → native host → extension.

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
- **Orchestrator** (cloud): `JURIS_LOCAL_AGENT_TOKEN=<token>` + `JURIS_AGENT_MODE=remote`
  + `JURIS_LOCAL_AGENT_URL=ws://<agent-host>:8765`

## 2. Run the agent as a service (macOS launchd)

```bash
cp docs/deploy/com.juris.agent.plist ~/Library/LaunchAgents/
# edit it: WorkingDirectory, JURIS_AGENT_TOKEN, JURIS_AGENT_CPF/SENHA/PIN, PKCS#11 path
launchctl load ~/Library/LaunchAgents/com.juris.agent.plist
```

The agent binds **127.0.0.1 only** (`juris agent serve` rejects any other host).
Logs: `/tmp/juris-agent.log`. Validate it:

```bash
uv run juris agent health --url ws://127.0.0.1:8765
# → Agente vX.Y — token: conectado; cert válido até: AAAA-MM-DD
```

## 3. Native messaging host (browser-session AI)

Register the host so Chrome can launch it (see `docs/browser-extension/`):

```bash
# com.juris.host.json → ~/Library/Application Support/Google/Chrome/NativeMessagingHosts/
# set "path" to the juris native-host binary and "allowed_origins" to the extension id
```

## 4. Chrome extension

```bash
cd docs/browser-extension && npm install && npm run package
# chrome://extensions → Developer mode → Load unpacked (this folder)
```

Log into Claude.ai/ChatGPT and disable training/history (onboarding §3.5).

## 5. Verify end to end

From the orchestrator (remote mode), a `juris demo <cnj> --source mni` read — or the
web "connect" — now flows: cloud → `ws://agent:8765` → token op → reply, with **no
PIN/senha leaving the agent**. The `scripts/remote_smoke.py` proves the wiring over a
real socket without a token.

## Security checklist

- [ ] Agent bound to 127.0.0.1 (never 0.0.0.0).
- [ ] `JURIS_AGENT_TOKEN` set; orchestrator's `JURIS_LOCAL_AGENT_TOKEN` matches.
- [ ] Token PIN / PJe senha only in the agent's env — never in the orchestrator.
- [ ] `juris file` / `/api/connect` in remote mode do **not** prompt for or store PIN/senha.
