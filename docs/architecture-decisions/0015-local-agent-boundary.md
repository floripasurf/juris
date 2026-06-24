# ADR-0015: Local Agent Boundary & Token Service Interfaces

## Status
Proposed — becomes Accepted when Phase 2 (multi-tenant) work starts.

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
