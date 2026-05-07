# ADR 0011 — PAdES Signing and MNI Filing Pipeline

## Status

Accepted

## Context

Sprint 11 introduces the end-to-end flow for digitally signing petitions (PAdES) and filing them with Brazilian tribunals via the MNI (Modelo Nacional de Interoperabilidade) web-service. The system must run entirely on the lawyer's local machine — private keys never leave the device. We need a design that works for the single-user CLI today while laying the groundwork for the multi-tenant SaaS architecture planned for Sprint 14+.

Key constraints:

- A1/A3 ICP-Brasil certificates are required; signing must happen locally.
- Only TJMG and TRT-2 are in scope for v1.
- Crash recovery is critical — a filed petition without a stored receipt is an audit gap.
- Lawyers must give informed, auditable consent before every filing.

## Decision

### 1. Single-Machine Co-located Architecture (Sprint 11)

The orchestrator, `PAdESSigner`, and `MNIClient` all run on the same machine. There is no network separation between signing and filing. This keeps deployment trivial (one process, one machine) and avoids premature distribution complexity.

### 2. WebSocket Skeleton as Sprint 14+ Integration Point

`local_agent.py` defines a WebSocket `/ws/sign` endpoint with Pydantic message schemas (`SignRequest` / `SignResponse`). In Sprint 11 the CLI calls the signer directly — the WebSocket listener is not activated. The protocol contract is defined now so that the future multi-tenant SaaS orchestrator can invoke the same `PAdESSigner` interface remotely without changing the signer code.

### 3. PAdESSigner as the Stability Boundary

The `PAdESSigner` class (used as a context manager) is the stable API surface. Callers will change over time — CLI direct call, then WebSocket, then cloud orchestrator — but the signer interface does not. All caller-side evolution happens outside this boundary.

### 4. PDF/A-2u Deferred to Sprint 11.5

Sprint 11 produces standard text-extractable PDFs. PDF/A-2u compliance is added only if a tribunal rejects a filing. Both in-scope tribunals (TJMG and TRT-2) currently accept standard PDFs.

### 5. In-Scope Tribunals: TJMG and TRT-2

Only TJMG and TRT-2 are supported in Sprint 11. Additional tribunals are Sprint 11.5+. Each tribunal may have MNI endpoint quirks, so scope is deliberately narrow.

### 6. Receipt Storage with Atomic Rename for Crash Recovery

Filing receipts are stored at:

```
~/.juris/filings/<cnj>/<timestamp>_pending/
```

During filing, the directory carries the `_pending` suffix. After MNI confirmation, it is atomically renamed to:

```
~/.juris/filings/<cnj>/<timestamp>_<protocolo>/
```

A `recover_pending()` function scans for `_pending` directories and resurfaces interrupted filings for retry or manual resolution.

### 7. Chain of Custody Hashes

Every stage produces a SHA-256 hash forming an auditable chain:

```
pdf_hash -> signed_pdf_hash -> submitted_payload_hash -> receipt_hash
```

All four hashes are persisted in `hashes.json` alongside the receipt inside the filing directory. This allows independent verification that no artifact was tampered with between stages.

### 8. ConsentSummary Audit

Before signing, the system builds a `ConsentSummary` containing rich context: case number, tribunal, prazo (deadline) status, certificate validity window, and page count. The lawyer is prompted to confirm. The consent event — including what was displayed, whether the PDF preview was opened, and elapsed decision time — is captured in the audit log as a `filing.consent` event.

### 9. Dry-Run Mode

`--dry-run` renders the PDF, executes all preflight checks, and displays the would-file parameters without performing any signing or MNI contact. It emits `filing.dryrun` audit events. The operation is repeatable and side-effect-free, suitable for CI pipelines and lawyer review workflows.

### 10. Prazo Override

`--prazo-override "justificativa"` allows filing past a deadline. The justification string is mandatory and is recorded as a `filing.prazo_override` audit event. This ensures that late filings are always traceable to an explicit human decision with a stated reason.

## Consequences

**Positive:**

- Single-machine deployment eliminates network-related failure modes for signing in Sprint 11.
- The WebSocket contract defined early prevents interface drift when the SaaS layer lands in Sprint 14+.
- Atomic rename guarantees that receipt storage is crash-consistent — no partial states visible to the recovery scanner.
- The hash chain provides tamper-evident custody from PDF generation through tribunal acknowledgment.
- Dry-run mode enables safe testing and lawyer preview without tribunal side effects.
- ConsentSummary audit creates a defensible record of informed consent for every filing.

**Negative:**

- Co-located architecture means Sprint 11 cannot scale beyond one machine per lawyer.
- Deferring PDF/A-2u risks a tribunal rejection requiring a fast follow-up patch (mitigated by confirming TJMG and TRT-2 acceptance).
- The WebSocket skeleton is dead code in Sprint 11, adding minor maintenance surface.

**Neutral:**

- Prazo override shifts liability to the lawyer — the system records but does not prevent late filings when explicitly overridden.
- Limiting to two tribunals means early users on other courts must wait for Sprint 11.5+.
