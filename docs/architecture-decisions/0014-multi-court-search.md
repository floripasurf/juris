# ADR-0014: Unified Multi-Court Jurisprudence Search

**Status:** Accepted
**Date:** 2026-05-06
**Supersedes:** None
**Related:** ADR-0013 (Public-Domain Corpus Expansion)

## Context

Brazilian legal practitioners routinely search for jurisprudence across multiple court portals (STF, STJ, TST, TRF1-6, TJ state courts). The current workflow requires manually opening each portal, entering the same query, and mentally merging results. This is slow, error-prone, and misses cross-court patterns.

Sprint 14 introduces a unified `juris search` CLI command that fans out queries across multiple portals in parallel and returns merged, ranked results.

## Decision

### 1. Pluggable Adapter Pattern

Each court portal gets a `SearchAdapter` subclass (ABC at `juris.search.adapters.base`). Mirrors Sprint 7's `busca_canais` pattern with `SearchChannel` ABC. Adapters are auto-discovered via `importlib`/`pkgutil` and registered with `@register_adapter`.

**Rationale:** Different portals have wildly different APIs (JSON vs HTML, ESAJ ViewState vs simple GET). A pluggable adapter isolates each portal's complexity. New TJ adapters can be added without touching the dispatcher.

### 2. Results Are Ephemeral (Displayed, Not Stored)

Search results are displayed to the user and discarded. No persistence to database or file system.

**Rationale:** Jurisprudence content belongs to the courts. Storing it would create legal exposure around redistribution rights and data freshness obligations. The tool is a search aggregator, not a mirror.

### 3. Deterministic Cross-Court Ranking

Composite score: `court_hierarchy * 0.4 + recency * 0.35 + term_overlap * 0.25`.

Court hierarchy: STF (1.0) > STJ (0.9) > TST/TSE (0.85) > TRF (0.70) > TRT (0.65) > TJ (0.50).

**Rationale:** No ML reranking — fully debuggable, explainable to lawyers. The `--explain` flag exposes all scoring components. Weights can be tuned based on user feedback without model retraining.

### 4. Cross-Court Deduplication by CNJ Number

Primary dedup: normalized CNJ number (same underlying case appearing in STJ + TRF3 via appeal). Fallback: `(court, case_number)` tuple when CNJ is unavailable.

**Rationale:** The same case travels through multiple courts (origin → TRF → STJ → STF). CNJ numbers uniquely identify the case across all instances. Without CNJ-based dedup, users see the same case multiple times with different portal formatting.

### 5. Per-Court Rate Limiting with File Persistence

Rate limits persist to `~/.juris/rate_limits.json` via timestamp-per-court. Default: 1 request per 2 seconds per court. Configurable per court (ESAJ portals may need longer intervals).

**Rationale:** Back-to-back `juris search` invocations must respect rate limits across OS processes. File-based persistence is the simplest cross-process coordination mechanism. Courts actively rate-limit or block aggressive scraping.

### 6. User-Agent Identification

All HTTP requests include `User-Agent: Juris/1.0 (legal research tool; contact@example.com)`.

**Rationale:** Transparent identification per common crawling etiquette. Courts can contact the tool maintainer if usage patterns are problematic. Hiding identity would be adversarial.

### 7. Health Checks (`juris search doctor`)

Every adapter implements `health_check()` — sends a minimal probe query and reports reachability + latency. `juris search doctor` runs all checks in parallel and displays a status table.

**Rationale:** Court portals change URLs, HTML structures, and API contracts without notice. Health checks provide quick diagnosis when search results suddenly drop to zero for a court.

### 8. CNJ Router (Resolução CNJ 65/2008)

`cnj_to_court()` maps any CNJ number to its originating court using the J (justiça) and TR (tribunal) segments. Verified against the official resolution.

**Rationale:** When users search by `--cnj`, the system auto-routes to the correct court(s) instead of querying all portals unnecessarily.

### 9. TJSP/ESAJ Complexity

ESAJ (used by TJSP, TJMG, TJPR, others) requires 2-step form submission: GET page → extract ViewState token + cookies → POST search. This is inherently fragile.

**Decision:** Implement ESAJ adapter with explicit session management. If ViewState extraction breaks, the adapter gracefully returns empty results and `juris search doctor` flags it as unhealthy. DataJud API is available as a fallback but has limited search capabilities.

## Consequences

### Positive
- Single CLI command replaces N browser tabs
- Cross-court dedup surfaces unique cases
- Ranking provides consistent ordering across heterogeneous portals
- Adapter pattern allows incremental portal coverage (TJ long tail)
- Health checks enable proactive monitoring

### Negative
- HTML-scraping adapters are fragile — portal changes break them silently
- Rate limiting across processes adds file I/O overhead (negligible for CLI use)
- No result caching — repeated queries re-hit all portals
- ESAJ ViewState may require periodic adapter updates

### Deferred to Sprint 14.5
- TJ adapters beyond TJSP (build by demand)
- Live integration tests as CI cron job
- Output to clipboard / browser open
- Result caching with TTL (if latency becomes a concern)

## File Structure

```
src/juris/search/
├── __init__.py
├── models.py           # SearchQuery, SearchResult, SearchResponse
├── dispatcher.py       # SearchDispatcher — parallel fanout, dedup, ranking
├── ranking.py          # cross-court ranking heuristics
├── rate_limiter.py     # per-court rate limiter with file persistence
├── cnj_router.py       # CNJ number → court auto-detection
├── utils.py            # date parsing, ementa cleaning, CNJ normalization
└── adapters/
    ├── __init__.py     # adapter registry + discovery
    ├── base.py         # SearchAdapter ABC with health_check()
    ├── stf.py, stj.py, tst.py
    ├── trf1.py ... trf6.py
    └── tjsp.py
```
