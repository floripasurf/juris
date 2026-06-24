# ADR-0016: PII Handling & "AI of Preference"

## Status
Proposed — becomes Accepted when the de-identification engine is chosen and spiked.

## Date
2026-06-24

## Related
ADR-0015 (local agent boundary — where raw case data can live). Builds on the
existing PII-aware router `src/juris/core/llm_router.py` and CLAUDE.md working
principle #6 ("local LLM for PII-bearing prompts; cloud only for de-identified
or public-corpus tasks").

## Context

The product vision promises analysis and drafting "by the AI of the operator's
preference" — implying cloud providers (Claude, and potentially others).

But processo content is **PII** and protected by both the LGPD and the OAB duty
of confidentiality (sigilo profissional). The current router encodes the safe
default: PII-bearing tasks (`ANALYZE`, `DRAFT`, `EXTRACT`, `ANALYZE_DEFESA`) go
to local Ollama; public-corpus tasks (`RESEARCH`, `REWRITE_QUERY`) may go to
cloud Claude.

Two forces collide:

1. The operator wants to choose a cloud model — "AI of preference".
2. Running a capable local LLM is impractical on weak hardware (e.g. a MacBook
   Air struggles with Ollama; only the Mac Mini runs it well).

So "always local for PII" is operationally fragile, and "always cloud" would
leak privileged client data. We need a model that offers provider choice
**without** sending raw PII to a third party by default.

## Decision

### 1. Classify every LLM task by data sensitivity

Keep `LLMTask` as the sensitivity axis: PII-bearing vs public-corpus. This is
already the basis of `llm_router.route(task, contains_pii=...)`.

### 2. De-identification is a first-class capability

Introduce a de-identification step that pseudonymizes **direct identifiers**
in case content before any PII-bearing text is sent to a cloud provider:
party names, CPF/CNPJ, OAB numbers, the CNJ/process number, addresses, and
contact data. A re-identification map is kept locally (or tenant-side), and the
cloud receives only de-identified facts. The router comment already anticipates
this ("cloud with de-identified context").

### 3. "AI of preference" = a constrained provider choice

The operator chooses among:

| Mode | What goes to the provider | When |
|---|---|---|
| **Cloud, de-identified** | pseudonymized facts only | default for capable cloud models |
| **Local, raw** | full case content, never leaves the machine | where local hardware permits |
| **Cloud, raw** | full case content | **opt-in only**, with explicit per-tenant consent + a signed DPA, audited per run |

Public-corpus tasks (research, query rewriting) may always use the cloud raw —
they carry no PII.

### 4. Default posture: raw PII never leaves the perimeter without consent

If neither a capable local LLM nor explicit cloud-raw consent is available, the
system uses cloud-de-identified or degrades — it never silently sends raw PII
to a third party.

### 5. Every routing + de-identification decision is audited

The audit chain records, per LLM call: task, `contains_pii`, chosen provider,
and whether de-identification was applied (`deid=true/false`). Extends the
"audit everything" principle to data-egress decisions.

## Consequences

### Positive
- Offers genuine provider choice without breaching LGPD / OAB confidentiality.
- Works on weak hardware (cloud-de-identified path) without forcing local LLM.
- Data-egress posture is explicit, default-safe, and auditable.
- Cleanly separates "which model" (preference) from "what data it may see" (policy).

### Negative
- De-identification of legal prose is genuinely hard — names are embedded in
  narrative facts; imperfect redaction risks either leaking PII or degrading
  draft quality.
- The re-identification map is itself sensitive and must be protected.
- De-identified context can reduce analysis/draft quality vs raw context;
  needs measurement.

### Deferred
- **De-identification engine choice** — spike Presidio (already evaluated in the
  `~/Desktop/spikes` review) vs an LLM-based or rules-based redactor; measure
  precision/recall on real petitions.
- Quality eval: de-identified vs raw drafting on a held-out set.
- Consent UX and DPA templates for the cloud-raw opt-in.
- Which cloud providers beyond Anthropic to support, and their per-provider
  data-handling terms.
