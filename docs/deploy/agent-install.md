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
> is *not* the lawyer's public IP. See **§6 Connectivity** — co-located it's
> `127.0.0.1`; for a real cloud orchestrator it's the local end of a secure tunnel.

For the anonymous Causia trial, the orchestrator issues this token for the trial
tenant and shows a command like:

```bash
JURIS_AGENT_TOKEN=<token> juris agent connect-relay wss://causia.com.br/ws/agent-relay --tenant <trial_id>
```

That mode uses the reverse channel: the agent dials out to Causia, so no inbound
port is opened on the lawyer's machine.

## 2. Run the agent as a service (macOS launchd)

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
web "connect" (including the **nightly sync**) — now flows: orchestrator →
the tenant's `JURIS_AGENTS_FILE` binding (loopback or tunnel, §6) → token op at the agent → reply,
with **no PIN/senha leaving the agent**. `scripts/remote_smoke.py` proves the wiring
over a real socket without a token.

## 6. Connectivity (cloud → agent)

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
      (§6) — never a public-facing agent port.
