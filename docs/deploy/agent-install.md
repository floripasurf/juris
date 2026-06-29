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
- **Orchestrator**: `JURIS_LOCAL_AGENT_TOKEN=<token>` + `JURIS_AGENT_MODE=remote`
  + `JURIS_LOCAL_AGENT_URL=ws://<reachable-agent-address>:8765`

> **Reachability:** the agent binds **127.0.0.1 only**, so `<reachable-agent-address>`
> is *not* the lawyer's public IP. See **§6 Connectivity** — co-located it's
> `127.0.0.1`; for a real cloud orchestrator it's the local end of a secure tunnel.

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
web "connect" (including the **nightly sync**) — now flows: orchestrator →
`JURIS_LOCAL_AGENT_URL` (loopback or tunnel, §6) → token op at the agent → reply,
with **no PIN/senha leaving the agent**. `scripts/remote_smoke.py` proves the wiring
over a real socket without a token.

## 6. Connectivity (cloud → agent)

The agent binds **127.0.0.1 only** — never the public network. So a cloud
orchestrator **cannot** reach `ws://<lawyer-public-ip>:8765` directly: the home
machine is behind NAT/firewall, and exposing the port would defeat the loopback
guarantee. Bridge the gap one of these ways:

- **Co-located (Phase 1, today).** Orchestrator + agent on the same machine (the
  firm's Mac Mini). `JURIS_LOCAL_AGENT_URL=ws://127.0.0.1:8765`. No tunnel needed —
  this is the pilot setup and what `scripts/remote_smoke.py` exercises.
- **Secure tunnel (multi-tenant).** Run a tunnel that maps a private cloud-side
  hostname to the agent's loopback port, authenticated and encrypted — e.g.
  **Cloudflare Tunnel** (the daemon runs on the lawyer's machine and dials *out*, so
  no inbound port is opened). The orchestrator then uses the tunnel hostname as
  `JURIS_LOCAL_AGENT_URL`. The pairing token still gates every request.
- **Reverse channel (future).** Flip the direction so the **agent dials out** to a
  cloud relay and the orchestrator routes through it — removes the inbound-NAT
  problem entirely and is the cleanest multi-tenant model. Not built yet
  (the transport is orchestrator-initiated today); tracked as Phase-2 work.

In every case the security properties hold: loopback bind, paired token, secrets
resolved at the agent.

## Security checklist

- [ ] Agent bound to 127.0.0.1 (never 0.0.0.0).
- [ ] `JURIS_AGENT_TOKEN` set; orchestrator's `JURIS_LOCAL_AGENT_TOKEN` matches.
- [ ] Token PIN / PJe senha only in the agent's env — never in the orchestrator.
- [ ] `juris file` / `/api/connect` in remote mode do **not** prompt for or store PIN/senha.
- [ ] Cloud → agent only via co-located loopback or a secure tunnel (§6) — never a
      public-facing agent port.
