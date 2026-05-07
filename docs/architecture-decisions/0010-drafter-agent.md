# ADR 0010: Drafter Agent Architecture

## Status
Accepted

## Context

Sprints 1-9 built reading, analysis, alerting, retrieval, and review capabilities. Sprint 10 completes the generation pillar with a Drafter Agent that produces grounded, citation-verified petition drafts.

Key design decisions needed:
- How to ensure citations are grounded in the repertory (not hallucinated)
- How to present opposing arguments (contraponto) to the lawyer
- How to bound the revision loop to prevent infinite re-prompting
- How to integrate with existing retrieval and review infrastructure

## Decision

### Citation Contract
The LLM is instructed to use `[CITE:source_id]` markers exclusively. A deterministic `MarkerCitationVerifier` validates every marker against the repertory post-generation. Any unresolvable marker triggers a re-prompt (up to `max_revision_rounds`). This separates generation (LLM) from verification (deterministic).

### Antithesis Loop (Contraponto)
The `Researcher` agent generates 2-3 antithesis phrasings via a small LLM call, then searches the repertory for opposing jurisprudence. This ensures the `[CONTRAPONTO PREVISTO]` section is grounded in real case law, not LLM-fabricated arguments.

### Revision Loop Bounds
- `max_revision_rounds` defaults to 1 (configurable up to 3)
- Re-prompts are triggered by: (a) failed citation verification, (b) critical issues from ReviewerAgent
- After max rounds, the draft is returned with failed checks noted — the lawyer makes the final call

### Retrieval Enhancements
- Cross-encoder reranking (BAAI/bge-reranker-v2-m3) inserted between RRF merge and hierarchy boost
- HyDE (Hypothetical Document Embeddings) for improved recall on ambiguous queries
- Both are optional — graceful fallback when models are unavailable

### Shared Citation Lookup
`resolve_source_id()` and `resolve_narrative_citation()` extracted to `repertory/citation_lookup.py` to serve both `RawCitationVerifier` (review) and `MarkerCitationVerifier` (agents).

## Consequences

### Positive
- No hallucinated citations can reach the lawyer (deterministic verification)
- Opposing arguments are grounded in real jurisprudence
- Revision loop is bounded — no runaway costs
- Retrieval quality improvements benefit all consumers (review, research, draft)

### Negative
- Cross-encoder adds ~2-5s latency per retrieval (mitigated by caching)
- HyDE requires an additional LLM call per search (cached per session)
- Drafter requires both local LLM and repertory to be functional

### Risks
- LLM may struggle to use `[CITE:]` markers correctly on first pass — revision loop mitigates this
- Antithesis phrasings may not cover all opposing positions — coverage_note makes gaps visible
