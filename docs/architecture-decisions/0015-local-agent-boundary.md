# ADR-0015: Local Agent Boundary & Token Service Interfaces

## Status
Accepted — Remote implementation built (2026-06-29).

The split-trust agent is implemented and swappable by config:

- **Clients (orchestrator side):** `RemoteSigningService` (`signing/remote.py`) and
  `RemoteMNIReadService` (`mni/remote.py`) implement the same ABCs as the InProcess
  ones. They forward over sync WebSocket transports; **no token material travels**
  — the PIN and PJe credentials are resolved at the agent. Signing never retries
  (not idempotent); MNI reads retry briefly (idempotent).
- **Agent (token side):** `api/local_agent.py` serves `/ws/sign` (PAdES) and
  `/ws/mni` (`mni.consultar_processo` / `mni.consultar_avisos`), token-authenticated,
  resolving credentials locally and auditing only non-sensitive metadata.
- **Contract:** `SignRequest`/`SignResponse` + the `AgentRequest`/`AgentResponse`
  envelope (`request_id`, `tenant_id`, `operation`, `payload`, `error`) in
  `api/ws_schemas.py`. Domain objects round-trip via pydantic `TypeAdapter`.
- **Factory:** `get_signing_service()` / `get_mni_read_service()` pick InProcess
  (`JURIS_AGENT_MODE=inprocess`, default — CLI/pilot) vs Remote
  (`=remote` + `JURIS_LOCAL_AGENT_URL` + `JURIS_LOCAL_AGENT_TOKEN`). The demo
  pipeline + connect read through the factory, so multi-tenant is config, not a
  rewrite. Agent-side secrets: `JURIS_AGENT_CPF` / `JURIS_AGENT_SENHA` /
  `JURIS_AGENT_PIN`.

- **Remote filing (`/ws/file`) — done.** Signing *and* peticionamento both need the
  A3 token, so the whole pipeline runs at the agent (not a `get_signing_service()`
  swap). `signing/filing_service.py`: `FilingService` ABC + `run_filing` (shared
  in-process body) + `InProcessFilingService` + `RemoteFilingService` (forwards a
  `FilingRequest` with **cpf/senha/PIN blanked** — resolved at the agent). The agent
  serves `/ws/file` (`handle_file_request`); the result crosses as the **chain-of-
  custody hashes** (auditable proof) — the signed PDF + receipt stay at the agent.
  `get_filing_service()` picks InProcess/Remote by config; `juris file` routes through
  it (the old remote guard is gone). Unit-tested split-trust (no creds cross); live
  filing needs the real token (manual smoke).

**Multi-tenant minimum — done:** per-tenant **routing** (`tenant_agent_binding` →
each firm's agent URL+token from `$JURIS_AGENTS_FILE`, env fallback; all three
factories route by tenant), **pairing** (`juris agent pair`/`serve`/`health`),
**visible health** (`agent_health` real readiness), **durable jobs** (SQLite
`ConnectJobStore`, survives restart, tenant-scoped), **per-tenant logs**
(`bind_tenant_log_context` binds `tenant_id` to structlog per request/job).

**Reverse channel — built (core):** for non-co-located deploys the agent dials OUT to
the orchestrator (`juris agent connect-relay <wss-url>`) and holds the connection open;
the orchestrator routes token ops down it via `RelayHub` (request/response multiplexed
by `request_id`), sidestepping the agent's NAT. Endpoint `/ws/agent-relay`
(token-authed per tenant); agent-side `dispatch_agent_request` runs mni/file locally
(file signs at the agent). Use `wss://` for channel TLS (mTLS if the relay requires a
client cert).

Remaining:

- mTLS (client certs) beyond the shared `JURIS_AGENT_TOKEN` + `wss://` — pin per agent.
- Route the orchestrator's Remote services through `RelayHub` in relay mode (today the
  hub is the integration point) + dialer reconnection/backoff (run under a supervisor).
- Demo-path `tenant_id` threading (connect already tags it; demo runs are sync).

## Date
2026-06-24

## Related
ADR-0011 (PAdES filing — the signing side of the boundary). Builds on the MNI
read path validated live on 2026-06-24 (`src/juris/mni/fetch.py`,
`mni/token.py`) and the existing scaffolding `src/juris/api/local_agent.py`,
`api/orchestrator.py`, `api/ws_schemas.py`.

## Context

The product vision is a multi-tenant SaaS where a lawyer logs in, "connects
their token", sees their processes, and one-clicks read → analyze → draft →
sign → file.

The ICP-Brasil **A3** token is non-exportable hardware: the private key never
leaves the device. The two operations that use that key —

1. **mTLS handshake** for MNI reads against tribunals like TJMG, and
2. **PAdES signing** of petitions —

**must execute on the machine where the token is physically plugged in.** A
browser cannot perform PKCS#11 mTLS against a third-party tribunal on behalf
of a cloud server, and an A3 key cannot be uploaded to a cloud HSM. There is
no "insert your token into the website" — only "a local component on your
machine uses the token on your behalf."

Today everything runs in one process on one machine (CLI + local pilot web UI,
co-located with the token). Multi-tenancy breaks that: each firm's token is on
*their* machine, not our server.

This is the established pattern in Brazilian legal software (PJe assinador,
Shodō, BRy) — lawyers already run a local signer app. The friction is known
and accepted by the market.

## Decision

### 1. Token-bound operations sit behind explicit service interfaces

Define three interfaces in the core/domain layer:

| Interface | Operations |
|---|---|
| `TokenService` | detect token, read certificate material + status (no PIN) |
| `MNIReadService` | `consultar_processo`, `consultar_avisos_pendentes` (mTLS + password) |
| `SigningService` | PAdES sign a PDF with the A3 key + consent capture |

The orchestrator, web layer, and demo pipeline depend **only** on these
interfaces. They never import `pkcs11`, `juris.mni.token`,
`juris.mni.pkcs11_transport`, `requests_pkcs12`, `pyhanko`, or the mTLS
transport directly. `fetch_processo_mni` becomes the body of the in-process
`MNIReadService` implementation.

### 2. Two implementations per interface, selected by config

- **InProcess** — runs the token operation in the same process (Phase 1,
  co-located). What the CLI/demo do today.
- **Remote** — a thin client that forwards the operation to the lawyer's
  **local agent** over the authenticated localhost/WebSocket protocol
  (Phase 2). Mirrors `api/local_agent.py` / `ws_schemas.py`.

Swapping InProcess ↔ Remote is configuration, not a code change in the
orchestrator. This is the cheap-insurance move: pay the interface cost now,
make the Phase 2 split a swap rather than a rewrite.

### 3. The local agent is the only PKCS#11 holder

The agent exposes exactly: `health` (token_connected, cert CN/validity), MNI
read (consulta/avisos), and `sign` (PAdES + `ConsentSummary`). It binds to
`127.0.0.1` only and authenticates clients with a per-session token (both
already enforced in `local_agent.py`).

### 4. The agent is stateless with respect to case data

It performs an operation and streams the result to the orchestrator. It does
not persist processo content, drafts, or PII beyond the in-flight operation.
Case data residency is governed by ADR-0016, not the agent.

### 5. Phasing

- **Phase 1 (single firm — owner's office):** InProcess implementations,
  co-located on one machine (e.g. the Mac Mini with the token attached,
  exposed via Cloudflare Tunnel). No remote agent. Also serves the in-person
  pilot.
- **Phase 2 (multi-tenant):** Remote implementations; finish the local agent
  (wire SigningService + MNIReadService into the WS protocol), build the
  installer and the device-pairing/enrollment flow.

## Consequences

### Positive
- The expensive Phase 2 split becomes a config swap, not a rewrite of the cloud.
- The interface boundary is independently testable with fakes (no token needed in CI).
- Matches the BR-market assinador UX lawyers already expect.
- Keeps PKCS#11 / heavy crypto deps out of the cloud import graph.

### Negative
- Two implementations per interface to maintain.
- Install + auto-update friction for the local agent in Phase 2.
- The localhost/WS protocol needs versioning (agent and cloud upgrade independently).

### Deferred
- Device pairing / tenant-enrollment flow (how an agent authenticates to an account).
- Agent packaging, code-signing, auto-update.
- Offline / token-absent behavior and reconnection semantics.
- Whether the agent also hosts a local LLM for PII tasks (see ADR-0016).
