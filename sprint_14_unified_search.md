# Sprint 14 — Unified Multi-Court Search

**Duration:** ~1.5-2 weeks
**Predecessor:** Builds on Sprint 7 (multi-channel party search across PJe systems). Sprint 14 extends the same pattern to *jurisprudence portals* — the public research interfaces of STF, STJ, TST, TRFs, and major TJs.

## Goal

A single CLI command that fans out a search query across multiple court jurisprudence portals in parallel and returns merged, ranked results. Replaces the manual workflow of opening N browser tabs.

```bash
juris search --tema "improbidade administrativa" --courts trf1,trf2,trf3,stf
juris search --oab "SP123456" --courts trf3,tjsp
juris search --cnpj "12.345.678/0001-90" --courts trf1,trf2,stj
juris search --cnj "0001234-56.2024.8.26.0001"   # auto-detects court
juris search --tema "prescrição quinquenal trabalhista" --courts tst,trt2,trt15
```

## What this is NOT

- Not a corpus ingester (Sprint 13 covers that)
- Not a research library or saved-results database (browser bookmarks suffice)
- Not a background monitor or scheduled scraper (search is user-initiated only)
- Not a PJe/case-management harvester (jurisprudence portals only)
- Not multi-tenant — runs locally, results displayed and discarded

The discipline matters: results are *displayed*, not *stored*. Every legal-posture concern from earlier conversations resolves cleanly when search is ephemeral.

## Architecture

Same pattern as Sprint 7's `busca_canais`: pluggable adapters, parallel dispatch, merged output. New for Sprint 14: the adapters target *public jurisprudence portals* rather than PJe case systems, and queries support theme/OAB/party search rather than just party lookup.

```
src/juris/search/
├── __init__.py
├── models.py           # SearchQuery, SearchResult, SearchResponse
├── dispatcher.py       # parallel fanout, dedup, ranking
├── adapters/
│   ├── base.py         # SearchAdapter ABC
│   ├── stf.py          # portal.stf.jus.br/jurisprudencia
│   ├── stj.py          # scon.stj.jus.br
│   ├── tst.py          # jurisprudencia.tst.jus.br
│   ├── trf1.py         # trf1.jus.br/sjur
│   ├── trf2.py         # trf2.jus.br/jurisprudencia
│   ├── trf3.py         # web.trf3.jus.br/base-textual
│   ├── trf4.py         # jurisprudencia.trf4.jus.br
│   ├── trf5.py         # trf5.jus.br/cp
│   ├── trf6.py         # trf6.jus.br
│   ├── tst.py          # jurisprudencia.tst.jus.br
│   ├── tjsp.py         # esaj.tjsp.jus.br/cjsg
│   └── tjmg.py         # tjmg.jus.br/portal-tjmg
└── ranking.py          # cross-court ranking heuristics
```

## Deliverables

### 1. Core models

**File:** `src/juris/search/models.py`

```python
@dataclass(frozen=True, slots=True)
class SearchQuery:
    query_type: Literal["tema", "oab", "nome", "cpf", "cnpj", "cnj"]
    value: str
    date_range: tuple[date, date] | None = None
    max_results_per_court: int = 20

@dataclass(frozen=True, slots=True)
class SearchResult:
    court: str                  # "stf", "trf3", etc.
    case_number: str            # CNJ format when available
    decision_date: date | None
    relator: str | None         # ministro/desembargador
    classe: str | None          # "RE", "REsp", "ApCiv", etc.
    ementa: str                 # the holding text
    url: str                    # link to the decision on the portal
    source_query: SearchQuery
    fetched_at: datetime

@dataclass(frozen=True, slots=True)
class SearchResponse:
    query: SearchQuery
    results: list[SearchResult]
    courts_queried: list[str]
    courts_failed: list[tuple[str, str]]   # (court, error)
    total_count: int
    elapsed_seconds: float
```

### 2. Adapter base class

**File:** `src/juris/search/adapters/base.py`

```python
class SearchAdapter(ABC):
    """A search adapter for a specific court's jurisprudence portal."""

    court_code: str               # "stf", "trf3", etc.
    portal_url: str
    rate_limit_seconds: float     # min seconds between requests
    supported_query_types: set[Literal["tema", "oab", "nome", "cpf", "cnpj", "cnj"]]

    @abstractmethod
    async def search(self, query: SearchQuery) -> list[SearchResult]: ...

    def supports(self, query_type: str) -> bool:
        return query_type in self.supported_query_types
```

Each adapter is responsible for:
- Translating the unified `SearchQuery` to the portal's specific query format
- Respecting the portal's rate limit
- Parsing the portal's HTML/JSON response into `SearchResult` objects
- Graceful failure (return empty list, log reason — never raise)

### 3. Dispatcher

**File:** `src/juris/search/dispatcher.py`

```python
class SearchDispatcher:
    def __init__(self, adapters: dict[str, SearchAdapter]): ...

    async def search(
        self,
        query: SearchQuery,
        courts: list[str],
    ) -> SearchResponse:
        # 1. Filter adapters by query type compatibility
        compatible = [a for a in self._lookup(courts) if a.supports(query.query_type)]
        unsupported = [c for c in courts if c not in compatible_codes]

        # 2. Parallel fanout via asyncio.gather
        tasks = [adapter.search(query) for adapter in compatible]
        results_per_court = await asyncio.gather(*tasks, return_exceptions=True)

        # 3. Merge, dedupe by (court, case_number)
        merged = self._merge_and_dedupe(results_per_court)

        # 4. Cross-court ranking (see ranking.py)
        ranked = rank_results(merged, query)

        return SearchResponse(...)
```

### 4. Cross-court ranking

**File:** `src/juris/search/ranking.py`

Simple deterministic ranking that doesn't pretend to be more sophisticated than it is:

```python
def rank_results(results: list[SearchResult], query: SearchQuery) -> list[SearchResult]:
    """Rank merged results by court hierarchy + recency + query match.

    Court hierarchy weight (binding precedent first):
        stf > stj > tst > trf* > tj*
    Recency: decisions from last 24 months get a boost.
    Query match: simple term overlap with ementa.
    """
```

Don't reach for ML reranking — this is a search aid, not a retrieval engine. Deterministic ranking is debuggable and fast.

### 5. Adapters (per court)

**Build order — most valuable first:**

| Day | Adapter | Why first |
|---|---|---|
| 1-2 | STF, STJ | Highest legal weight; portals are well-documented |
| 3 | TST | Trabalhista coverage |
| 4-5 | TRF1, TRF2, TRF3, TRF4, TRF5, TRF6 | Federal regional coverage |
| 6 | TJSP | Largest TJ by volume |
| 7 | TJMG, TJRJ, TJRS | Other major TJs |
| 8+ | Remaining TJs as needed | Fill in by demand |

**Per-adapter implementation pattern:**

1. **Discovery (~1 hour per court):** open the portal in a browser, identify the search URL, the query parameters, the HTML structure of results. Document in a comment block at the top of the adapter.
2. **Implementation (~2-4 hours per court):** httpx async client, query parameter construction, HTML parsing via BeautifulSoup or selectolax (faster), result extraction.
3. **Tests (~1 hour per court):** mock the HTTP response with a saved fixture from real portal output, verify parsing.

**Common patterns to extract into shared utilities:**

- CNJ number normalization (some portals accept formatted, some unformatted)
- Date parsing (Brazilian formats: dd/mm/yyyy, "Publicado em DJe de...")
- Ementa text cleaning (remove court boilerplate headers, strip HTML)
- OAB number handling (some portals require state prefix, some don't)

### 6. CNJ auto-detection

**File:** `src/juris/search/cnj_router.py`

CNJ numbers encode their court of origin. Format: `NNNNNNN-DD.AAAA.J.TR.OOOO`:
- `J` = segment (1=STF, 4=TJ Federal, 5=TRF, 8=TJ Estadual, etc.)
- `TR` = tribunal code

When a user runs `juris search --cnj "0001234-56.2024.8.26.0001"`, parse the CNJ number, identify the court (8.26 = TJSP), and route the search only to that court's adapter. No fanout needed — it's a specific lookup.

### 7. CLI command

**File:** extend `src/juris/cli/main.py`

```python
@search_app.command()
def search(
    tema: str | None = typer.Option(None, "--tema", "-t"),
    oab: str | None = typer.Option(None, "--oab"),
    nome: str | None = typer.Option(None, "--nome", "-n"),
    cpf: str | None = typer.Option(None, "--cpf"),
    cnpj: str | None = typer.Option(None, "--cnpj"),
    cnj: str | None = typer.Option(None, "--cnj"),
    courts: str = typer.Option("stf,stj", "--courts", "-c", help="comma-separated court codes"),
    date_from: str | None = typer.Option(None, "--from"),
    date_to: str | None = typer.Option(None, "--to"),
    max_per_court: int = typer.Option(20, "--max"),
    output_format: str = typer.Option("table", "--format", "-f", help="table | json | markdown"),
):
    """Search jurisprudence across multiple courts in parallel."""
```

**Validation rules:**
- Exactly one of `--tema`, `--oab`, `--nome`, `--cpf`, `--cnpj`, `--cnj` must be provided
- `--cnj` ignores `--courts` (auto-detected)
- `--courts all` expands to all registered adapters supporting the query type
- Unknown court codes warn but don't fail

**Output formats:**

- `table` (default): Rich table with columns Court | Case | Date | Relator | Ementa preview (60 chars)
- `json`: full structured output for piping to other tools
- `markdown`: each result as a markdown block with full ementa, suitable for pasting into notes

### 8. Rate limiting

**File:** `src/juris/search/rate_limiter.py`

Per-court rate limiter shared across requests:

```python
class CourtRateLimiter:
    """Per-court async rate limiter. Tracks last request time, sleeps if needed."""

    async def acquire(self, court: str) -> None: ...
```

Default: 1 request per 2 seconds per court. Configurable per adapter for portals with stricter requirements.

### 9. Tests

```
tests/unit/search/
├── test_models.py
├── test_dispatcher.py        # parallel fanout, dedup, ranking
├── test_cnj_router.py        # CNJ → court detection
├── test_rate_limiter.py
├── test_ranking.py
└── adapters/
    ├── test_stf.py           # mock HTTP, fixture HTML, verify parsing
    ├── test_stj.py
    ├── test_tst.py
    ├── test_trf1.py
    ├── test_trf3.py
    └── ...                   # one per adapter

tests/integration/
└── test_search_live.py       # @pytest.mark.live, real HTTP, not in CI
```

**Test discipline:**
- Every adapter has a saved HTML/JSON fixture from real portal output
- Mock httpx responses; never hit live portals in unit tests
- Live integration test runs only when explicitly invoked

### 10. Documentation

- ADR `docs/architecture-decisions/0014-multi-court-search.md` — why displayed-not-stored, adapter pattern, ranking choices
- `docs/usage/search.md` — lawyer-facing guide with examples per query type
- Update CLAUDE.md to add `juris search` to common commands

## Operating rules

1. **Results are ephemeral.** Display and discard. No persistence in the production corpus, no caching beyond the current invocation.

2. **Respect ToS and robots.txt.** Each adapter documents the portal's terms in its file header. If a portal forbids automated access, the adapter is not built.

3. **Rate limits are per-portal, not global.** Some portals will tolerate 1 req/sec; others require 1 req/5sec. Calibrate per adapter.

4. **User agent identifies the tool.** `User-Agent: Juris/1.0 (juris.ai; legal research tool; contact@example.com)`. Don't masquerade as a browser.

5. **Errors per court don't kill the response.** If TRF3 times out, return results from STF + STJ + TRF1 + TRF2 with a notice that TRF3 failed.

6. **Off-peak preferred but not enforced.** Mention in the user guide that running large searches outside business hours reduces portal load. Don't programmatically restrict.

## Definition of Done

- [ ] STF, STJ, TST, TRF1-6, TJSP adapters implemented and tested
- [ ] `juris search --tema "..." --courts stf,stj,trf3` returns merged results in <30s
- [ ] CNJ auto-routing works for STF, STJ, TJ Estadual, TRF, TJ Trabalhista CNJs
- [ ] OAB and CNPJ search work across portals that support those query types
- [ ] All unit tests pass with mocked HTTP; one live integration test passes per adapter
- [ ] Lint and mypy clean
- [ ] Per-portal rate limiting respected (no portal receives >1 req/2sec)
- [ ] Documentation: ADR, user guide, CLAUDE.md update

## Suggested daily rhythm

- **Day 1:** ADR. Models, dispatcher, base adapter, CNJ router. Rate limiter.
- **Day 2:** STF + STJ adapters. Tests. First end-to-end search working.
- **Day 3:** TST adapter. CLI command. Output formatting.
- **Day 4-5:** TRF1, TRF2, TRF3 adapters.
- **Day 6:** TRF4, TRF5, TRF6 adapters.
- **Day 7:** TJSP adapter (largest TJ, harder portal).
- **Day 8:** TJMG, TJRJ, TJRS adapters.
- **Day 9:** Cross-court ranking refinement, deduplication edge cases.
- **Day 10:** Documentation, final test pass, real-portal validation.

## What NOT to do in Sprint 14

- Don't add a research library, save-to-disk feature, or "favorites" — the moment results persist, the legal posture changes
- Don't ingest results into the production corpus (Sprint 13 covers that with proper sourcing)
- Don't run scheduled or background searches
- Don't query PJe or case-management systems — only public jurisprudence portals
- Don't build LLM-based reranking or semantic search over results — deterministic ranking is sufficient and debuggable
- Don't build a web UI in this sprint — CLI only

## What this enables

After Sprint 14, the lawyer's research workflow becomes:

```bash
# Researching a tax-law question
juris search --tema "responsabilidade tributária por sucessão" --courts trf1,trf2,trf3,trf4,stj

# Studying opposing counsel's arguments
juris search --oab "SP234567" --courts tjsp,trf3

# Looking up a specific case
juris search --cnj "0009999-99.2024.5.02.0001"

# Researching a corporate party's litigation
juris search --cnpj "12.345.678/0001-90" --courts trf1,trf2,trf3,stj --from 2022-01-01
```

This replaces ~30 minutes of manual portal-tab-juggling with a single command and ranked output. It's the kind of utility that makes the product worth opening every day, alongside the case-management and drafter features. And because results are displayed-not-stored, the legal posture is clean: it's automation of what lawyers have always done manually with public research portals.
