# ADR-0018: AI via the lawyer's browser session (subscription), not the API

**Status:** Accepted · **Date:** 2026-06-25 · **Relates to:** ADR-0015 (local agent boundary), ADR-0016 (PII & AI of preference)

## Context

The local models we can run on the lawyer's hardware (Ollama: Qwen/Llama) are
**below the frontier** for nuanced legal reasoning (strategy selection, drafting).
We need a frontier model for the PII-bearing tasks (analyze, strategy, draft).

Two ways to reach a frontier model with confidential data:

1. **Cloud API (Anthropic/OpenAI) + de-identification.** Sanctioned for products,
   does not train by default, offers a DPA. But **per-token cost** is significant
   at scale.
2. **The lawyer's own consumer subscription (Claude.ai / ChatGPT) driven by a
   browser extension.** The firm **already pays** the flat subscription; marginal
   cost ~zero. The session lives on the lawyer's machine.

The owner's call (informed of the trade-offs): **option 2** — the cost of the API
is excessive when every lawyer already has a subscription.

## Decision

The primary frontier provider for PII-bearing tasks is the **lawyer's browser
session** (`LLMProvider.CLAUDE_BROWSER`), reached via a browser extension on the
lawyer's machine. This is a **local capability** in the ADR-0015 split-trust model
— like the A3 token, the AI session never leaves the lawyer's perimeter; the cloud
orchestrator sends a prompt and receives a completion through the local extension.

Two safeguards, layered:

1. **De-identification stays ON** (`PIIMode.BROWSER_DEID` → `route.deidentify =
   True`). Consumer plans *may* train on content, so we strip CPF/CNPJ/CNJ/OAB
   before the prompt leaves for the session and re-identify the response. Cheap
   defense in depth, independent of the lawyer's settings.
2. **Onboarding step.** Setup instructs the lawyer to **disable training / data
   collection** in their provider settings (Claude.ai: *Privacy → don't help
   improve*; ChatGPT: *Data Controls → Improve the model = off*). Recorded as a
   pilot checklist item.

The API path (`CLOUD_DEID` / `CLOUD_RAW`) remains in the router as an alternative
(e.g. a tenant that prefers a DPA-backed API and accepts the cost).

## Consequences

**Positive:** frontier quality; ~zero marginal cost (existing subscriptions);
session stays on the lawyer's machine (fits split-trust); de-id + opt-out address
the training concern.

**Risks (accepted, recorded):**
- **ToS gray area.** Driving a consumer subscription by automation may conflict
  with provider Terms for *commercial / multi-tenant resale*. Lower risk for the
  firm's **own** use (own data, own subscription); revisit before multi-tenant
  resale — a DPA-backed API tenant may be required there.
- **No DPA.** Consumer plans give no data-processing agreement; the LGPD posture
  rests on de-id + the training opt-out, not a contract. Acceptable for the pilot;
  flagged for the multi-tenant phase.
- **Fragility.** UI automation breaks on layout changes / anti-bot. The extension
  must degrade gracefully and surface failures (fall back to local).

## Implementation

- **Router (done):** `LLMProvider.CLAUDE_BROWSER`, `PIIMode.BROWSER_DEID`
  (de-identify + route to the session), `prepare_payload` gates with
  `ensure_cloud_safe`.
- **Build path (next):** a Chrome extension on the lawyer's machine + a
  `BrowserSessionLLM` (`AbstractLLM`) that relays prompts to the logged-in
  Claude.ai/ChatGPT tab and extracts the reply; a localhost channel between the
  juris local agent and the extension (mirrors the token agent in ADR-0015).
