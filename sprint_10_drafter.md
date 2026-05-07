# Sprint 10 — Drafter Agent (the writing counterpart of Reviewer)

**Duration:** ~3 weeks (+ 2 days for retrieval quality enhancements + ~1 hour of human-blocking lawyer time on Day 4)
**Side task in parallel:** None — drafter is the focus. If you finish early, start the citation_verifier polish.

> **Update from initial spec:** This sprint includes HyDE (hypothetical document embeddings) and cross-encoder reranking as Deliverable 2 below. Sparse-only FTS retrieval is sufficient for exact-term legal queries (article numbers, súmula numbers) but weak for semantic queries — and a drafter is bottlenecked by the strength of its supporting authority. These additions disproportionately improve retrieval quality at modest implementation cost (~2 days combined). They benefit the existing Reviewer too.
>
> **Benchmark approach:** the retrieval quality benchmark is auto-extracted from the firm's existing petitions, then lawyer-curated via a `[Y/N/E/S]` review CLI. ~95% of the work (extraction, paraphrasing, source resolution) is automated; the lawyer's irreducible contribution is ~30 minutes of binary judgment that breaks the circular-evaluation problem. The benchmark validates the *internal retrieval calls the Drafter makes mid-pipeline*, not Q&A — Juris is a litigation copilot, not a research engine.

## Why this is Sprint 10

Sprints 1–9 produced a system that **reads, analyzes, alerts, retrieves, and critiques**. With the Reviewer already shipped, every primitive the Drafter needs (retrieval, LLM router, audit, structured output, citation parsing, defesas analysis) is already battle-tested in production code paths. Sprint 10 closes the original mission's third pillar — generation — with the lowest possible integration risk because nothing new in the foundation has to be invented; the Drafter is the inverse of the Reviewer.

After Sprint 10, the only thing standing between the system and the original "Read → Analyze → Draft → File" mission is **signing + filing** (Sprint 11), which becomes much less ambiguous to scope once the Drafter is producing real outputs to feed it.

## Goal

By end of sprint, running

```bash
juris draft <numero_cnj> <tipo> [--thesis "..."] [--cloud]
```

produces a Markdown petition draft that is:

1. **Grounded** — every citation in the output resolves to a real source in the repertory (verified deterministically, not by hope)
2. **Stylistically aware** — uses petition templates (`juris.repertory.peticoes.models.TemplatePeticao`) when matched; defaults to neutral structure otherwise
3. **Tactically informed** — for contestação/réplica, the drafter calls `DefesaAnalyzer` and incorporates applicable defenses
4. **Self-critiqued** — the existing `ReviewerAgent` runs as a final pass before output is shown; critical issues raised by the reviewer trigger one auto-revision attempt
5. **Strategically honest** — produces a `[CONTRAPONTO PREVISTO]` internal section listing the strongest opposing authority the antithesis researcher found
6. **Fully audited** — every step (retrieval, antithesis retrieval, LLM call, citation verification, reviewer pass, revision) emits an `AuditEntry` via `juris.persistence.audit.AuditLog`

Definition of "good enough to file" for sprint exit: on at least 3 of your real cases, the draft is something you'd be willing to file with under 30 minutes of editing. Not a prototype demo; a real working tool for your own caseload.

## Deliverables

### 1. Module: `juris.agents.researcher`

The component the Reviewer should have had but didn't fully need. The researcher is now a first-class citizen because the Drafter calls it heavily.

**File:** `src/juris/agents/researcher.py`

Public interface:

```python
from dataclasses import dataclass, field

@dataclass(frozen=True, slots=True)
class ResearchQuery:
    """A research request anchored to a thesis the drafter wants to argue."""
    thesis: str                          # Portuguese: "A prescrição quinquenal aplica-se..."
    case_context: dict[str, Any]         # tribunal, classe, ramo_direito, partes_tipos
    desired_authority_min: int = 4       # default: súmula or above
    top_k: int = 8

@dataclass(frozen=True, slots=True)
class ResearchResult:
    """Symmetric supporting + opposing authority for a thesis."""
    thesis: str
    supporting: list[RetrievalResult]    # from juris.repertory.retrieval.service
    opposing: list[RetrievalResult]      # the contradictory-jurisprudence flag
    coverage_note: str                   # human-readable: "found 3 STJ repetitivos, no STF binding"
    has_strong_opposition: bool          # for the drafter's strategic decision

class Researcher:
    def __init__(self, repertory: RepertoryService, llm: AbstractLLM): ...

    async def research(self, query: ResearchQuery) -> ResearchResult: ...
```

**Implementation notes:**

- For `supporting`: use HyDE-augmented retrieval (see Deliverable 2). Pseudocode: generate a hypothetical ementa via Ollama, embed/search both the literal thesis AND the hypothetical, merge via RRF. Then call `RepertoryService.search_jurisprudencia` (which already runs through the reranker per Deliverable 2) and apply `hierarquia_min=desired_authority_min, top_k=top_k`.
- For `opposing`: this is the antithesis loop. Make a small LLM call (Ollama by default, no PII risk since input is just the thesis) asking *"Negate or contradict this thesis as a Brazilian appellate court might phrase it. Output 2–3 phrasings."* Then run `search_jurisprudencia` against each phrasing (also HyDE-augmented), dedupe results, return top 3.
- `coverage_note` is built from metadata, not LLM-generated. Count by `hierarchy` level: "Encontradas 2 Súmulas STJ, 4 acórdãos STJ não-vinculantes, 1 precedente local. Nenhum precedente vinculante (Súmula Vinculante ou Tema STF)."
- `has_strong_opposition` is True when at least one opposing result has `hierarchy <= 4`. This drives the drafter's tactical choice between preempting and holding.

**Audit:** every `Researcher.research()` call emits one `AuditEntry` with `event_type="research"`, including thesis, both source-id lists, hash of returned chunks, plus HyDE flag (was the hypothetical used) and reranker scores. This is critical for the Resolução CNJ 615/2025 contestabilidade requirement.

### 2. Module: `juris.repertory.retrieval.reranker` + HyDE expansion

Two retrieval quality enhancements that benefit *all* consumers of the repertory (Researcher, the existing Reviewer, future Drafter), not just Sprint 10. Built before the Researcher because the Researcher consumes them.

**Why this is here:** Sparse FTS5 retrieval is strong for exact terms (article numbers, súmula numbers, specific phrases) but weak for semantic queries. Lawyers phrase questions differently than ementas express holdings. Two well-understood techniques close that gap with modest implementation cost.

#### 2A. Cross-encoder reranking

**File:** `src/juris/repertory/retrieval/reranker.py`

```python
@dataclass(frozen=True, slots=True)
class RerankerScore:
    chunk_id: str
    score: float
    cached: bool

class CrossEncoderReranker:
    """BGE-reranker-v2-m3 wrapper for top-K reranking.

    Runs the cross-encoder over (query, chunk_text) pairs and returns
    relevance scores. Cached by (query_hash, source_id) to avoid recomputation.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        device: str = "cpu",
        cache: Path | None = None,
    ): ...

    def rerank(
        self,
        query: str,
        candidates: list[SearchResult],
        top_k: int = 15,
    ) -> list[SearchResult]: ...
```

**Integration in `HybridRetriever.search()`:**

```
existing flow:
  dense_search(top_k * 2) + sparse_search(top_k * 2)
  → RRF merge
  → hierarchy_boost
  → return top_k

new flow:
  dense_search(50) + sparse_search(50)
  → RRF merge → top 30 candidates
  → cross_encoder_rerank → top 15
  → hierarchy_boost
  → return top_k (default 10)
```

**Implementation notes:**

- Lazy-load the model (same pattern as `LegalEmbedder`)
- Graceful fallback: if model unavailable, skip reranking and return RRF results unchanged. Do NOT silently degrade — log a warning at startup so the user knows reranking is off.
- Cache scores in SQLite (or a simple `dict` for dev) keyed by `sha256(query + source_id)`. The same query+source pair gets re-scored often as different drafts cite the same authority.
- Don't rerank the entire RRF result; cap input at 30 candidates. Cross-encoder cost scales linearly.

**Why cross-encoder reranking matters specifically for legal text:** bi-encoders (embeddings) compute similarity in a single vector space, which inevitably loses signal. Cross-encoders read the query and each candidate together with full attention, computing a true relevance score. For an STJ ementa where the relevant holding is in paragraph 4 of 8, the bi-encoder dilutes the signal across the whole text; the cross-encoder finds the holding.

#### 2B. HyDE (Hypothetical Document Embeddings)

**File:** add `_hyde_expand` method to `juris.repertory.retrieval.service.RepertoryService`

```python
class RepertoryService:
    async def search_jurisprudencia(
        self,
        query: str,
        ...,
        use_hyde: bool = True,
        llm: AbstractLLM | None = None,
    ) -> list[RetrievalResult]:
        """Search with optional HyDE expansion.

        When use_hyde=True and llm provided, generates a hypothetical ementa
        for the query, runs retrieval against both the literal query and the
        hypothetical, and merges via RRF before reranking.
        """
        ...

    async def _hyde_expand(self, query: str, llm: AbstractLLM) -> str:
        """Generate a hypothetical ementa that would answer this query.

        Uses Ollama by default. The hypothetical is matched against real
        ementas which share its register, vocabulary, and structure —
        producing dramatically better semantic matches than the original
        question phrasing.
        """
        ...
```

**HyDE prompt template:** add to `src/juris/prompts/hyde_v1.py`:

```python
SYSTEM_PROMPT = """Você é um assistente jurídico que escreve ementas hipotéticas
no estilo do STJ/STF para auxiliar pesquisa de jurisprudência."""

EXPAND_PROMPT = """Tese a ser pesquisada:
{query}

Escreva UMA ementa hipotética curta (60-100 palavras) no estilo de uma decisão
do STJ que SUSTENTE essa tese. Use vocabulário e estrutura típicos: começar com
o tema, expor a tese vencedora, citar dispositivo legal relevante. Não invente
números de processo, ministros ou súmulas — escreva apenas o corpo da ementa.

Ementa hipotética:"""
```

**Implementation notes:**

- Use Ollama with low temperature (0.2-0.3) for stylistic consistency
- Cache hypotheticals by query_hash for the session — the same thesis researched twice should reuse
- When the literal-query retrieval and the HyDE retrieval both return the same source, RRF naturally boosts it (rank in two lists)
- HyDE is most valuable for high-level legal questions ("aplicabilidade da desconsideração da personalidade jurídica em grupo econômico"). For very specific queries ("Súmula 547 STJ"), HyDE adds little but doesn't hurt
- If `llm=None`, the method silently skips HyDE — older code paths continue working

**Audit:** when HyDE is used, log the hypothetical text in the audit chain (event_type="retrieval.hyde"). The hypothetical is a generated artifact that influenced the search; it's part of the contestabilidade chain.

#### 2C. Retrieval quality benchmark (auto-extracted, lawyer-curated)

**Files:**
- `src/juris/benchmark/extractor.py` — auto-extraction pipeline
- `src/juris/cli/main.py` — `juris benchmark curate` CLI command
- `tests/integration/test_retrieval_quality.py` — the actual benchmark test

**What this benchmark validates:** the internal retrieval calls the Drafter makes when building petitions. Not Q&A. Not open-ended legal research. Specifically: when the Drafter, mid-pipeline, retrieves authority for a thesis it is about to argue, does the retriever surface the kind of authority an experienced lawyer would expect to find?

The pairs come from the firm's real petition corpus because those represent realistic in-context retrieval calls — the Drafter, if it had been responsible for those past petitions, would have generated similar internal queries. The lawyer's past citations are the ground truth.

**Why this matters for scoping:** because the benchmark tests internal Drafter retrieval (not Q&A), the dataset doesn't need to be exhaustive across all of legal practice. It needs to cover the firm's actual practice areas with realistic theses. 50–80 well-curated pairs from the firm's own petitions are more useful than 500 synthetic pairs covering theoretical edge cases.

##### The pipeline

**Auto-extraction (Claude Code, ~half day on Day 3):**

```python
# src/juris/benchmark/extractor.py
async def extract_pairs_from_petition(
    petition_path: Path,
    repertory: RepertoryService,
    llm: AbstractLLM,
) -> list[ExtractedPair]:
    """For a single past petition:
    1. Parse sections (existing TemplatePeticao extractor)
    2. For each section, prompt LLM:
       'Extract the legal thesis being argued in this section
        (one sentence, lawyer's voice) and list every authority
        cited as support (Súmula numbers, REsp numbers, etc.).'
    3. Resolve each cited authority via citation_lookup
    4. Drop pairs where the authority doesn't resolve in repertory
    5. Generate 2-3 paraphrases per thesis (formal, colloquial, question-form)
    6. Score extraction confidence (single clear citation = high;
       multiple citations or ambiguous thesis = low)
    """
```

The extractor runs over the firm's existing petition PDFs (already in `repertory.peticoes`). Output: candidate `ExtractedPair` objects with `thesis`, `expected_source_ids`, `paraphrases`, `confidence`, and `provenance` (which petition + which section it came from).

Optional augmentation: scrape STJ Notícias and STF Notícias of the last 6 months. Each news summary contains a paragraph describing a recent decision plus a citation to it — natural (paragraph, expected_source_id) pairs from public data. Add ~30–50 pairs this way.

**Curation UI (Claude Code builds, lawyer uses, ~30–45 min on Day 4):**

```bash
juris benchmark curate
```

Single-pair-at-a-time terminal review with three-key shortcuts. Pairs sorted by extraction confidence descending, so easy/clean ones come first, harder ones later when the lawyer is in rhythm:

```
┌─────────────────────────────────────────────────────────────┐
│ Pair 12 of 87 (confidence: 0.92)                            │
│                                                             │
│ From: contestacao_caso_4521.pdf, section 3                  │
│                                                             │
│ Thesis (auto-extracted):                                    │
│   "Aplicação da prescrição quinquenal em ação trabalhista   │
│    proposta após o término do contrato, contando-se a       │
│    partir do efetivo descumprimento."                       │
│                                                             │
│ Expected authority (cited in your petition):                │
│   src_tst_sumula_362                                        │
│   "TST Súmula 362 — Prescrição. FGTS. Contas vinculadas..." │
│                                                             │
│ [Y] keep  [N] reject  [E] edit thesis  [S] skip  [Q] save&quit │
└─────────────────────────────────────────────────────────────┘
```

UX rules:
- Default to `[Y]` on Enter — most extractions are valid; one keystroke per "yes" keeps total time under an hour
- `[N]` accepts an optional rejection reason (free text, used later to refine the extraction prompt)
- `[E]` opens `$EDITOR` for thesis text only; preserves the source_id
- `[S]` defers the pair; comes back at end of session
- `[Q]` saves state and exits; resumable across sessions

State persisted to `.juris/benchmark_curation.json` so curation can be done in chunks.

**Stop criteria for curation:**
- Lawyer reaches 50 confirmed pairs → enough for a stable benchmark
- Lawyer fatigues earlier → partial dataset is fine; the benchmark test reports its own n
- All pairs reviewed → done

**Baseline + validation (Claude Code, end of Day 4):**

```python
# tests/integration/test_retrieval_quality.py

@pytest.mark.integration
def test_retrieval_quality_benchmark():
    """Recall@3 with HyDE+reranker ON beats OFF by >= 15pp."""
    pairs = load_curated_pairs(".juris/benchmark_curated.json")
    assert len(pairs) >= 30, "Curate more pairs first"

    recall_off = run_benchmark(pairs, hyde=False, reranker=False)
    recall_on = run_benchmark(pairs, hyde=True, reranker=True)

    assert recall_on - recall_off >= 0.15, (
        f"Retrieval enhancements not earning their cost. "
        f"OFF={recall_off:.2f}, ON={recall_on:.2f}"
    )
```

##### Why the curation step is irreducible

The auto-extraction pipeline produces pairs by asking an LLM what the thesis and citations are in a given petition section. If those same auto-extracted labels are then used to evaluate an LLM-driven retriever, the benchmark is **circular** — it measures the LLM agreeing with itself, not whether retrieval is good.

The lawyer's curation breaks the circularity by injecting independent judgment: "is this auto-extracted thesis actually a legitimate thesis worth citing this authority for?" That's a question only a lawyer can answer, but it takes ~30 seconds per pair (most are obviously yes). 30 seconds × 50 pairs = 25 minutes of irreducible human work, with auto-extraction doing the other 95% of the labor.

##### Day 4 evening: go/no-go gate

If the benchmark passes (≥15pp improvement), proceed to Phase 3 (Researcher).

If the benchmark fails, **stop feature work and diagnose**:
- Common cause 1: HyDE prompt too generic — iterate on `prompts/hyde_v1.py`
- Common cause 2: reranker model not loading silently — check graceful degradation isn't masking
- Common cause 3: corpus too thin to demonstrate improvement — note this and proceed anyway, but flag for Sprint 10.5 corpus expansion
- Common cause 4: extraction quality too low — re-curate, reject more pairs

Do NOT proceed with a failing benchmark. The Drafter's quality is bounded by retrieval quality; building forward on broken retrieval makes Day 14–17 testing impossible to interpret ("is this draft weak because of the prompt or because of retrieval?").

##### Long-term value

After Day 4, the curated dataset becomes a permanent test asset. Every future retrieval change — embedder swap, chunking strategy, index format, reranker upgrade — re-runs the benchmark and produces a directly comparable recall@3 number. This is the difference between data-driven retrieval evolution and gut-feel retrieval evolution. For a system that needs to be defensible to customers and regulators, the data-driven path matters.

### 3. Module: `juris.agents.citation_verifier`

The deterministic post-pass that makes hallucinated citations structurally impossible. Currently the Reviewer parses citations for critique purposes; this is its enforcement counterpart.

**File:** `src/juris/agents/citation_verifier.py`

```python
@dataclass(frozen=True, slots=True)
class CitationCheck:
    raw_marker: str                      # "[CITE:src_stf_sumula_47]"
    source_id: str                       # parsed from the marker
    resolved: bool                       # source_id exists in repertory
    available_excerpt: str | None        # if resolved, the actual chunk text
    span_in_draft: tuple[int, int]       # (start_char, end_char) in draft

@dataclass(frozen=True, slots=True)
class VerificationResult:
    all_passed: bool
    checks: list[CitationCheck]
    failed: list[CitationCheck]          # subset where resolved=False
    spurious_citations: list[str]        # case numbers like "REsp 1.234.567/SP"
                                         # found in prose but not in any [CITE:] marker

class CitationVerifier:
    def __init__(self, repertory: RepertoryService): ...

    def verify(self, draft: str, allowed_source_ids: set[str]) -> VerificationResult: ...
```

**Implementation notes:**

- The Drafter's prompt forces citations to use `[CITE:source_id]` markers (see prompt template below). The verifier parses these with a single regex.
- For each `[CITE:source_id]` found, look it up in the repertory. If the source_id is not in `allowed_source_ids` (the set returned by `Researcher.research`) → fail.
- Also scan for raw case-number patterns in prose (`REsp \d+`, `RE \d+`, `Súmula \d+`, `Tema \d+`) and verify each. If any case number appears that's not anchored to a `[CITE:]` marker for an allowed source, flag as `spurious_citations`. This catches the LLM that "remembered" a case from training.
- This is **deterministic** — no LLM call. Pure regex + dict lookup. Sub-100ms.

The verifier feeds back into the drafter for at most one auto-revision: if `not result.all_passed`, the drafter is invoked again with the failures listed and instructed to remove or replace those citations.

### 4. Module: `juris.agents.drafter`

The main agent. Orchestrates everything.

**File:** `src/juris/agents/drafter.py`

```python
@dataclass(frozen=True, slots=True)
class DraftRequest:
    numero_cnj: str
    tribunal: str
    tipo_peticao: TipoPeticao            # from juris.repertory.peticoes.models
    thesis: str | None = None            # optional explicit thesis; else inferred
    custom_instructions: str = ""        # lawyer's tactical notes, free text
    use_cloud_llm: bool = False          # default: Ollama for PII-bearing
    max_revision_rounds: int = 1

@dataclass(frozen=True, slots=True)
class DraftResult:
    draft_markdown: str                  # the petition itself, [CITE:] markers resolved
    contraponto_section: str             # the [CONTRAPONTO PREVISTO] internal section
    citations_used: list[CitationCheck]  # all resolved
    research_summary: str                # coverage_note from researcher
    reviewer_report: ReviewReport | None # if pre-show review enabled
    revisions: int                       # how many auto-revisions occurred
    total_duration_seconds: float
    audit_entry_ids: list[str]           # full provenance chain

class DrafterAgent:
    def __init__(
        self,
        llm: AbstractLLM,
        repertory: RepertoryService,
        researcher: Researcher,
        verifier: CitationVerifier,
        reviewer: ReviewerAgent,         # the existing one
        audit: AuditLog,
        defesa_analyzer: DefesaAnalyzer | None = None,
    ): ...

    async def draft(self, request: DraftRequest, context: ProcessoContext) -> DraftResult: ...
```

**The flow inside `draft()`:**

```
1. Build case context
   - Load processo via DataJud or stored ProcessoDomain
   - Build ProcessoContext (reuse the one from defesas/context.py)
   - If tipo_peticao in {CONTESTACAO, CONTRARRAZOES}: call DefesaAnalyzer.analyze()
   - Audit: event_type="draft.context_built"

2. Determine thesis
   - If request.thesis provided, use it
   - Else: small LLM call (Ollama) summarizing what the petition needs to argue
     based on case context + tipo + last decision/movement
   - Audit: event_type="draft.thesis_chosen"

3. Research
   - Researcher.research(ResearchQuery(thesis, case_context))
   - Returns supporting + opposing
   - Audit: event_type="research" (emitted by Researcher itself)

4. Style retrieval (optional, only if tenant has petition templates)
   - Try repertory.peticoes lookup by tipo_peticao + ramo_direito
   - If templates exist, pick best-matching one (most recent + highest outcome score)
   - This becomes the structural skeleton in the prompt
   - Audit: event_type="draft.style_retrieved"

5. First-pass generation
   - Compose prompt from: case context, defesas (if applicable), research result,
     style template, custom instructions, the [CITE:] markers contract
   - Call LLM (cloud=Claude if request.use_cloud_llm AND case is de-identified;
     else Ollama)
   - Audit: event_type="llm_call" with prompt_hash, output_hash, model, temperature

6. Citation verification
   - allowed_source_ids = {r.source_id for r in research.supporting + research.opposing}
   - verifier.verify(draft, allowed_source_ids)
   - If not all_passed AND revisions < max_revision_rounds:
       Re-prompt LLM with failure list, increment revisions, GOTO step 6
   - Audit: event_type="draft.citations_verified" with pass/fail counts

7. Build [CONTRAPONTO PREVISTO] section
   - Plain-text section listing the opposing authority found
   - Format: each opposing source as a bullet with hierarchy_label, tribunal,
     short ementa (max 120 chars), and the strategic note
     "preemptively address" if has_strong_opposition else "hold for réplica"
   - This section is OUTSIDE the petition body, marked clearly as internal-only

8. Pre-show review (the safety net)
   - If reviewer is configured: run reviewer.review(ReviewRequest(draft, ...))
   - If report.critical_count > 0 AND revisions < max_revision_rounds:
       Re-prompt LLM with critical issues, GOTO step 6
   - Audit: event_type="draft.reviewed" with critical_count, important_count

9. Compose final DraftResult
   - draft_markdown = petition body
   - contraponto_section = strategic note for the lawyer
   - All citations resolved with hierarchy labels in the body
     (e.g., [CITE:src_stf_sv_8] becomes "Súmula Vinculante 8 do STF")
   - Audit: event_type="draft.completed" with full duration
```

### 5. Prompt template: `juris.prompts.drafter_v1`

**File:** `src/juris/prompts/drafter_v1.py`

Following the existing pattern of `prompts.analyzer_v1`, `prompts.petition_extractor_v1`. Use the same module structure: `SYSTEM_PROMPT`, `DRAFT_PROMPT`, optional `DRAFT_SCHEMA`.

The `SYSTEM_PROMPT` must include the citation contract verbatim:

```
REGRAS ABSOLUTAS DE CITAÇÃO:
1. Você só pode citar fontes que aparecem na lista FONTES_DISPONÍVEIS abaixo.
2. Cada citação no texto deve usar o formato [CITE:source_id], onde source_id
   é exatamente o id de uma fonte da lista.
3. Não invente números de processo, súmulas, temas, recursos repetitivos ou
   acórdãos. Se a fonte não está na lista, você NÃO pode citá-la — formule o
   argumento sem citação ou peça por mais pesquisa.
4. Não cite por título genérico ("a doutrina majoritária"); use a fonte específica.
5. Cada [CITE:source_id] que você usar deve ser apropriado ao argumento — não
   use uma fonte só para parecer fundamentado.
```

The `DRAFT_PROMPT` template includes interpolation slots for: case context, defesas applicable, research supporting, research opposing, style template, custom instructions, revision feedback (when re-prompting).

Pin a low temperature (`0.1`–`0.2`) for production drafts. Higher temperatures produce more variant prose but more hallucinated citations even with the contract.

### 6. CLI: `juris draft`

**File:** extend `src/juris/cli/main.py`

```python
@app.command()
def draft(
    numero_cnj: str = typer.Argument(..., help="Case number in CNJ format"),
    tipo: str = typer.Argument(..., help="Petition type: contestacao, apelacao, etc."),
    thesis: str = typer.Option(None, "--thesis", "-T", help="Thesis to argue"),
    instructions: str = typer.Option("", "--instructions", "-i", help="Tactical notes for the drafter"),
    cloud: bool = typer.Option(False, "--cloud", help="Use Claude (only when case data is de-identified)"),
    output: str = typer.Option(None, "--output", "-o", help="Save draft to file"),
    skip_review: bool = typer.Option(False, "--skip-review", help="Skip the pre-show reviewer pass"),
    tribunal: str = typer.Option("tjmg", "--tribunal", "-t"),
) -> None:
    """Generate a petition draft grounded in the repertory."""
    # ... pattern follows the existing `analyze` and `review` commands
```

The output should:
- Print the petition body with rich formatting (preserve [CITE:] resolution into hyperlinked-looking inline labels)
- Print the `[CONTRAPONTO PREVISTO]` section in a distinct style (e.g., Rich panel with title "Internal — Contrapontos previstos pela pesquisa")
- Print summary footer: research coverage, citations used count, revisions, reviewer's critical/important counts
- If `--output` provided, save the petition body and the contraponto section as separate files (`draft.md` and `draft.contraponto.md`) — they're for different audiences

### 7. Tests

**Directory:** `tests/unit/agents/`, `tests/integration/`

Required test coverage:

- `test_reranker.py` — cross-encoder reranks relevant chunks above irrelevant ones on a synthetic legal-text fixture; cache hits return same scores; graceful degradation when model is unavailable
- `test_hyde.py` — HyDE expansion produces non-empty hypotheticals; merged retrieval (literal + HyDE) recall is ≥ literal-only recall on benchmark queries
- `test_researcher.py` — antithesis loop produces non-empty opposing on theses with known opposition; coverage_note math is correct; HyDE flag propagates to audit log
- `test_citation_verifier.py` — catches hallucinated `[CITE:]` markers; catches spurious case numbers in prose; passes clean drafts
- `test_drafter_pipeline.py` — full end-to-end with mocked LLM and a small fixture corpus; verifies all audit entries emitted in order
- `test_drafter_revision.py` — when verifier fails, drafter re-prompts; when reviewer raises critical, drafter re-prompts; both stop at `max_revision_rounds`
- `tests/integration/test_retrieval_quality.py` — runs the lawyer-curated benchmark dataset (50+ pairs); `recall@3` with retrieval enhancements ON beats OFF by ≥15 percentage points
- `tests/unit/benchmark/test_extractor.py` — auto-extraction pipeline produces valid `ExtractedPair` objects with confidence scores; resolves source_ids correctly; rejects unresolvable
- `tests/integration/test_drafter_real_case.py` (marked `@pytest.mark.live`) — runs against your real caseload using Ollama; not part of CI

Coverage target: 85% for the `agents/researcher.py`, `agents/drafter.py`, `agents/citation_verifier.py`, `repertory/retrieval/reranker.py` modules combined.

### 8. Documentation

- `docs/architecture-decisions/0010-drafter-agent.md` — the ADR
- Update `CLAUDE.md` to add the drafter to the agent inventory and add `juris draft` to common commands
- One-page user guide in `docs/usage/drafter.md` — the lawyer-facing doc explaining what the drafter is, what it isn't, what the contraponto section is for, and the citation contract

## Definition of Done

- [ ] All deliverables 1–8 implemented
- [ ] `uv run pytest` passes with target coverage
- [ ] `uv run ruff check .` and `uv run mypy src/juris` clean
- [ ] On 3+ real cases from your caseload, `juris draft <numero_cnj> contestacao` produces a draft you'd file with <30 minutes of editing
- [ ] No draft escapes with hallucinated citations (verifier catches them; if any leak through, treat as a sprint blocker)
- [ ] `[CONTRAPONTO PREVISTO]` section consistently identifies the strongest realistic opposing argument when one exists
- [ ] Audit log shows full provenance for every draft: context → thesis → research (with HyDE flag and reranker scores) → generation → verification → review → completion (every entry hash-chained)
- [ ] Pre-show reviewer pass catches at least one issue per 5 drafts on average (i.e., it's earning its keep)
- [ ] **Retrieval quality benchmark passes**: ≥50 lawyer-curated pairs in the dataset; `recall@3` with HyDE + reranker ON exceeds OFF by ≥15 percentage points
- [ ] Curation tool (`juris benchmark curate`) is reusable for future retrieval changes — saves state, supports resume, persists rejection reasons
- [ ] Cross-encoder reranker degrades gracefully when model unavailable (logs warning at startup, falls back to RRF + hierarchy boost)

## Operating Rules

1. **Read the existing reviewer code first.** `src/juris/review/reviewer.py` is the closest cousin to what you're building. Match its style, its audit pattern, its prompt structure. Do not invent new patterns.
2. **Reuse, don't recreate.** The retriever, audit, LLM router, defesa analyzer, ProcessoContext, TPU classifier, prazo engine all exist. Import them. If you find yourself writing parallel logic, stop and refactor.
3. **The `[CITE:]` contract is non-negotiable.** Do not relax it for any "the model writes better without it" argument. The whole point is that hallucinated citations are structurally impossible, not just discouraged.
4. **Local LLM by default for drafting.** The case context contains PII. `--cloud` should only be selectable when the user explicitly de-identifies — and even then, surface a warning. The cleanest pattern is to add a `--cloud` flag that prints a confirmation prompt before proceeding.
5. **Audit hash chain integrity.** Every drafter run produces N audit entries (where N is roughly 6–10, more if HyDE is used and reranker logs scores). The hash chain must be unbroken — verify with `audit.verify_integrity()` at end of each test run.
6. **Build retrieval first, validate before integrating.** Deliverables 2A (reranker) and 2B (HyDE) ship and are benchmarked (Deliverable 2C) before the Researcher uses them. If the benchmark doesn't show ≥15pp recall@3 improvement, debug there — do NOT continue building Researcher and Drafter on top of broken retrieval. The whole drafter quality is bounded by retrieval quality.
7. **Don't try to ship signing/filing in this sprint.** That's Sprint 11. The drafter's output is a Markdown file; turning it into a PAdES-signed PDF and filing it via MNI is the next sprint's mission.

## What NOT to do in Sprint 10

- Do not build any signing infrastructure (Sprint 11)
- Do not build any FastAPI endpoints (Sprint 12) — drafter is CLI-first
- Do not build per-tenant style memory beyond what `repertory.peticoes` already provides — that's Phase 2 territory
- Do not introduce a new LLM (e.g., Gemini, GPT-4) — use the existing `juris.llm.{claude,ollama}` router
- Do not add a "fully autonomous mode" that skips human review — Resolução CNJ 615/2025 forbids it and the architecture is explicit on this
- **Do not change the embedder model.** BGE-M3 stays. Embedder evaluation (e5-large-instruct, Stella, GTE, nomic-embed-text, legal-bert-pt) is Sprint 10.5 territory and requires a proper benchmark setup with real query/relevance pairs that you'll only have after Sprint 10 testing.
- **Do not activate BGE-M3 multi-vector / ColBERT mode.** It's a real quality lever but requires re-ingesting the corpus and a Qdrant version that supports late interaction. Sprint 10.5 territory.
- **Do not integrate JUDIT MCP** for breadth. Strategic buy decision; defer until Sprint 10 validates that local retrieval + HyDE + reranker is or isn't enough.

## Suggested daily rhythm

- **Day 1–2:** Read existing code (reviewer, analyzer, retrieval, audit). Write the ADR. Sketch the prompt templates (drafter + HyDE).
- **Day 3 (Claude Code):** Build cross-encoder reranker (deliverable 2A) and HyDE expansion (deliverable 2B). Wire reranker into `HybridRetriever.search()` between RRF and hierarchy boost. Verify graceful degradation. Build the auto-extraction pipeline (`benchmark/extractor.py`) and the `juris benchmark curate` CLI command. Run extraction over the firm's existing petition corpus to produce candidate pairs (sorted by confidence). **Output of Day 3: a populated curation queue ready for the lawyer.**
- **Day 4 morning (LAWYER, ~30–45 min — HUMAN-BLOCKING):** Run `juris benchmark curate`. Review auto-extracted pairs with `[Y/N/E/S]` shortcuts. Target 50+ confirmed pairs; stop earlier if fatigued (the test reports its own n). Save state freely; resumable across sessions.
- **Day 4 afternoon (Claude Code):** Run baseline benchmark with retrieval enhancements OFF, then ON. **Go/no-go gate**: if recall@3 improvement ≥15pp, proceed. If not, stop and diagnose (HyDE prompt, reranker loading, extraction quality, or corpus depth — see "Day 4 evening go/no-go gate" in Deliverable 2C). Do NOT continue to Phase 3 with a failing benchmark.
- **Day 5–6:** Build `Researcher` (deliverable 1) — both supporting (HyDE-augmented) and opposing (antithesis loop). The benchmark already validated retrieval quality on Day 4, so issues at this stage are Researcher-level (antithesis loop, coverage_note math), not retrieval-level.
- **Day 7:** Build `CitationVerifier` (deliverable 3). Test with synthetic drafts, both clean and dirty.
- **Day 8–11:** Build `DrafterAgent` orchestrator + prompts (deliverables 4 + 5). Wire up to existing reviewer for the safety net.
- **Day 12–13:** Build `juris draft` CLI (deliverable 6). Smoke-test end-to-end on a fixture case.
- **Day 14–17:** Test on 5–10 real cases from your caseload. Iterate on prompts and the citation contract until output is consistently good. This is where actual product quality emerges; don't rush it.
- **Day 18–19:** Documentation (deliverable 8). Final test run. ADR finalized.

If day 17 arrives and the drafter isn't producing genuinely useful output for your real cases, **stop adding features and iterate on prompts**. The product gap at this point is almost always prompt quality, not architecture. If retrieval is the issue (verify by inspecting what `Researcher` returned for failing cases), defer to Sprint 10.5 — don't try to solve embedder selection or multi-vector mode in this sprint.
