# ADR-0017: Source Mesh + Jurisprudence/Strategy Filter

## Status
Proposed — first slice (provider profile registry) implemented; the filter score
and argumentative-line stages become Accepted as they ship.

## Date
2026-06-24

## Related
ADR-0014 (multi-court search: dedup-by-CNJ + deterministic ranking — extended
here). Builds on `juris/busca/` (multi-channel orchestrator with corroboration),
`juris/search/` (adapters + `doctor` health checks), the
`SCHEMA_espinha_jurisprudencia.md` corpus model (`nivel_hierarquico`,
`superior_relacionada`, `status`), and the citation/strategy primitives
(`MarkerCitationVerifier`, `defesa_analyzer`, `llm_router`).

## Context

Two recurring problems shape every data path in Juris:

1. **Acquisition is fragile and heterogeneous.** A processo, a piece of
   jurisprudence, or an intimação can be obtained from several sources (MNI
   token, DataJud, eSAJ, DJE, scrapers, the local corpus), each with different
   coverage, reliability, cost, and legal posture (public vs captcha). Any
   single source fails often (WAF, captcha, dead endpoint, token locked).

2. **From many candidates, the lawyer needs *the best ones* — and a defensible
   line of argument.** Relevance alone is not enough: authority (how close to
   the case's decider), currency (vigente vs superado), and how the *local*
   judge actually rules all matter.

We want a design where **redundancy is not only failover but a signal**: a
precedent returned by several independent sources is more trustworthy than one
scraped fragilely from a single place. The acquisition mesh should feed the
filter's confidence.

`juris/busca/` already implements much of the mesh for *party search*: parallel
dispatch, graceful per-tribunal failure (`tribunais_com_erro`), dedup by CNJ
with source-priority field merge, and a corroboration score (`+0.15` per extra
corroborating source). What is missing is (a) trust/health as *declared
provider properties* rather than magic numbers, (b) generalisation beyond party
search, and (c) the jurisprudence/strategy filter.

## Decision

### 1. Capability ports + provider profiles

Acquisition is organised by **capability** — `ProcessoSource`,
`JurisprudenciaSource`, `IntimacaoSource` — each served by multiple
**providers**. Every provider declares a **profile**:

| field | meaning |
|---|---|
| `fonte` | source id (MNI, DataJud, eSAJ, DJE, scraper, corpus) |
| `trust` | base reliability for the capability (0–1) |
| `merge_priority` | which source wins when merging the same datum |
| `fonte_publica` / `atras_captcha` | legal/operational posture (mirrors the SCHEMA fonte flags) |
| `health()` | reachability probe (reuses the `search doctor` pattern) |

Trust/priority stop being hardcoded in the orchestrator and become registry
data — the first buildable slice extracts `busca`'s `_SOURCE_PRIORITY` /
`_RELIABLE_SOURCES` into `ProviderProfile`s, preserving current scores.

### 2. Two resolution strategies

- **Failover chain** (default for processo/intimação): try providers in
  `trust × health` order until one succeeds; record which one did. Unhealthy
  providers are skipped (circuit breaker / health check), not retried blindly.
- **Corroboration mode** (default for jurisprudence and party search): query
  multiple providers in parallel, merge + dedup **by CNJ** (ADR-0014), and use
  **source agreement as a confidence signal**. This is the mode `busca` already
  runs; ADR-0017 makes it explicit and reusable.

Every consolidated datum carries `sources[]` (provenance) and a `confidence`.

### 3. The filter — Stage 1: jurisprudence ranking (deterministic, verifiable)

A composite score per candidate precedent, **all components explicit and
auditable** (no ML black box — the lawyer must be able to inspect it):

```
score = w_rel · relevância          (retrieval híbrido — embedding/BM25)
      + w_auth · autoridade          (nivel_hierarquico: proximidade vara→câmara→superior)
      + w_vig · vigência             (vigente=1, superado/cancelado=0 ou exclui)
      + w_rec · recência
      + w_corr · corroboração        (f(nº de fontes independentes))
      + w_pac · pacificação          (superior_relacionada: pacificado=cita seguro; disputado=flag)
```

Initial weights (tunable, logged): `w_rel=0.35, w_auth=0.25, w_vig=0.15,
w_corr=0.15, w_rec=0.07, w_pac=0.03`. Authority is anchored on **this case's**
recursal chain (vara V → câmara C → autoridades 1-3), per the SCHEMA §2 rule:
relevance filters, level breaks ties by proximity. Output: ranked citations,
each **verified to exist** by `MarkerCitationVerifier`.

### 4. The filter — Stage 2: argumentative line (LLM proposes, criteria decide)

From the Stage-1 verified precedents, generate **N candidate argumentative
lines** (judge-panel pattern — e.g. prescrição / mérito / processual) and score
each by explicit criteria:

- support among Stage-1 verified citations,
- fit to the local decider's tendency (escavação data when available),
- adversary resilience (`defesa_analyzer` / contraponto),
- risk.

Select the best; **surface the runners-up** for transparency. The LLM never
invents citations (verified deterministically) and never makes the final call
by itself — the selection criteria are explicit and logged.

### 5. Deterministic × LLM boundary

| Deterministic (auditable, no LLM) | LLM (proposes, then verified) |
|---|---|
| provider resolution + corroboration confidence | argumentative-line generation |
| Stage-1 jurisprudence score | thesis inference / HyDE query expansion |
| citation existence/verification | drafting prose |
| vigência/level/dedup | summarisation of precedents |

Rule: **anything a citation or deadline depends on is deterministic**; the LLM
is confined to generation, always grounded in deterministically-verified inputs.

### 6. Graceful degradation everywhere

A missing provider lowers `confidence` but never breaks the pipeline; a thin
corpus triggers directed scraping (SCHEMA §5) instead of an empty answer; no
local LLM falls back to cloud-de-identified (ADR-0016) or the deterministic
rascunho mode.

## Consequences

### Positive
- Redundancy improves both resilience and answer quality (corroboration → confidence).
- Trust/health are declared, inspectable provider data — not magic numbers.
- The lawyer can audit *why* a precedent ranked and *why* a line was chosen.
- Reuses what exists (busca corroboration, ADR-0014 dedup, SCHEMA fields, citation verifier).

### Negative
- Querying many providers in corroboration mode costs latency/quota — needs per-capability budgets + health-aware skipping.
- The score weights need empirical tuning (pilot data); wrong weights mis-rank.
- "Fit to local decider" depends on escavação data that may not exist yet for a comarca (degrades to authority+relevance).

### Deferred
- The escavação data model feeding "fit to local decider" (depends on SCHEMA Fase 2 scraping).
- Jurisprudence-source providers beyond the local corpus (porting eSAJ `cjsg` / `stfstj`).
- Weight auto-tuning from lawyer feedback.
