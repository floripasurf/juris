# Sprint 13 — Public-Domain Corpus Expansion

**Duration:** ~3 weeks
**Predecessor:** Sprint 10.5 (binding/persuasive jurisprudence) is the architectural template. This sprint extends the same registry pattern to template/doutrina/news sources.

## Goal

Expand Juris's corpus from ~3,700 jurisprudence items (Sprint 10.5) to a multi-tier knowledge base covering:

- **Petition templates and models** (OAB, CNJ, Defensoria, clinics)
- **Public-domain doutrina** (older editions, government-published works)
- **Court news bulletins** (STF/STJ/TST Notícias as ongoing fresh signal)
- **Landmark anonymized cases** (de público interesse, explicitly published)
- **Published acórdãos** from court jurisprudence portals (research-purpose publications)

Target: ~5,000-8,000 new corpus items across these tiers. After Sprint 13, the Drafter has structural templates, doctrinal support, and current-events awareness alongside the existing jurisprudence.

Defensibility constraint: every source has documented public-domain or explicitly-public-research status. No use of your OAB credentials to access restricted material.

## Architecture

Same pattern as Sprint 10.5: per-source ingesters in `src/juris/repertory/ingestion/`, registered in `registry.py`, dispatchable via `juris repertory ingest --source <key>`.

**New TipoFonte values** added to `corpus/models.py`:

```python
class TipoFonte(StrEnum):
    # existing...
    SUMULA_VINCULANTE = "sumula_vinculante"
    SUMULA = "sumula"
    RESP_REPETITIVO = "resp_repetitivo"
    RE_STF = "re_stf"
    JURISPRUDENCIA_UNIFORME = "jurisprudencia_uniforme"

    # NEW in Sprint 13:
    MODELO_PETICAO = "modelo_peticao"          # template, structural scaffold
    DOUTRINA_PD = "doutrina_pd"                # public-domain doctrine
    NOTICIA_TRIBUNAL = "noticia_tribunal"      # court news bulletin
    ACORDAO_LANDMARK = "acordao_landmark"      # anonymized landmark case
    ACORDAO_PUBLICADO = "acordao_publicado"    # research-portal acórdão
```

**Hierarquia values** for retrieval ordering:

| TipoFonte | Hierarquia | Why |
|---|---|---|
| MODELO_PETICAO | 7 | Structural reference, not authority |
| DOUTRINA_PD | 6 | Persuasive context |
| NOTICIA_TRIBUNAL | 7 | Fresh signal, points to authoritative sources |
| ACORDAO_LANDMARK | 3 | Strong persuasive (court itself selected as landmark) |
| ACORDAO_PUBLICADO | 4-5 | Persuasive depending on tribunal |

These slot into the existing hierarchy boost in retrieval — templates and doutrina aren't authorities, but they're available for the drafter to use as scaffolding and supporting context.

## Deliverables

### Phase 1 — Petition templates (Days 1-7)

The highest-value tier. Templates ship as structural scaffolds; the drafter consumes them as guidance, not as text to copy.

#### 1A. OAB seccional model petitions

**File:** `src/juris/repertory/ingestion/oab_modelos.py`

Source mapping (the OAB seccionais that publish modelos systematically):

| Seccional | URL pattern | Volume estimate |
|---|---|---|
| OAB-SP | `oabsp.org.br/comissoes/...` various commission pages | 200+ |
| OAB-RJ | `oabrj.org.br/...` | 100+ |
| OAB-MG | `oabmg.org.br/...` | 80+ |
| OAB-RS | `oabrs.org.br/...` | 100+ |
| OAB Federal | `oab.org.br/cartilhas-modelos` | 50+ |

**Approach:**
1. Day 1: discovery — manually crawl the seccional commission pages, identify the modelo URLs, document them in `data/oab_modelos_index.json`
2. Day 2: per-seccional fetcher pulling the indexed URLs, parsing PDFs/HTML
3. Day 3: structural extraction — for each modelo, extract:
   - `area_direito` (trabalhista, civil, tributário, penal, etc.)
   - `tipo_peticao` (contestação, agravo, recurso ordinário, etc.)
   - `secoes` (list of structural sections with their typical content patterns)
   - `boilerplate_phrases` (generic legal phrasings, attribution-free)
   - `argumentative_scaffolds` (thesis structures, abstract not textual)

**Output:** `ModeloPeticao` records in `data/corpus/modelos_oab.json`. Source attribution preserved (which OAB seccional published it).

**IP discipline:** OAB modelos are designed for reuse. Attribution stays. Do not re-publish the verbatim text of any modelo as Juris content; extract structural patterns and boilerplate phrasings only.

#### 1B. CNJ standardized templates

**File:** `src/juris/repertory/ingestion/cnj_modelos.py`

CNJ publishes standardized templates for specific procedures: Juizados Especiais, execução fiscal, certain procedimentos especiais. Volume is smaller (~50-100 modelos) but quality is high and authority is unambiguous.

**Approach:** index `cnj.jus.br/sistemas/modelos`, pull each, parse, normalize.

#### 1C. Defensoria Pública published templates

**Files:** `defensoria_uniao_modelos.py`, `defensoria_estaduais_modelos.py`

Major Defensorias publish modelo libraries:
- DPU (federal)
- DPE-SP (significant volume in trabalhista, consumidor, família)
- DPE-RJ
- DPE-MG, DPE-RS, others

**Volume:** ~300-500 high-quality modelos across these. Designed for use by anyone (the public defenders' explicit purpose includes enabling citizens' access to legal templates).

#### 1D. Law school clinical templates (optional, Sprint 13.5)

**Files (deferred):** `clinicas_*` if time allows in Sprint 13.

USP Faculdade de Direito, FGV Direito SP, PUC-Rio, UFMG and others publish clinical templates. Smaller volume but often well-structured. Scope expansion if Phase 1A-1C finishes early.

### Phase 2 — Public-domain doutrina (Days 8-12)

Doutrina works whose copyright has expired (author deceased >70 years) or that have been explicitly placed in the public domain.

#### 2A. Government-published works

**File:** `src/juris/repertory/ingestion/governo_doutrina.py`

Sources:
- **MJSP (Ministério da Justiça)** publishes academic series under various commissions. Several historical series are public-domain or open-licensed.
- **STF Memória Institucional** publishes historical legal commentary
- **CNJ Edições** has a series of open-access publications
- **Senado Federal Editora** publishes legal works under permissive terms
- **IPEA** legal-economic studies

**Volume estimate:** 50-150 substantial works.

#### 2B. Public-domain classics

**File:** `src/juris/repertory/ingestion/classicos_pd.py`

Older editions of seminal works whose authors died before 1955 (70-year copyright term in Brazil per Lei 9.610). Examples:

- Pontes de Miranda (died 1979 — copyright runs to 2049, so NOT yet public domain)
- Clóvis Bevilácqua (died 1944 — public domain since 2014)
- João Mendes Júnior (died 1923 — public domain)
- Rui Barbosa's legal writings (died 1923 — public domain)
- Teixeira de Freitas (died 1883 — public domain)

**Verification step (Day 8):** for each candidate author, verify copyright status carefully before ingestion. Public-domain claim documented in source metadata.

**Sources:** archive.org (Brazilian legal works section), Biblioteca Nacional Digital, Domínio Público (MEC portal).

**Volume:** ~30-80 substantial works. Smaller than modern doutrina but historically foundational and unambiguously usable.

### Phase 3 — Court news bulletins (Days 13-15)

Ongoing fresh-signal ingestion. Different shape from one-time imports — these are *recurring* feeds.

#### 3A. STF Notícias, STJ Notícias, TST Notícias

**Files:** `stf_noticias.py`, `stj_noticias.py`, `tst_noticias.py`

Each court publishes RSS feeds and weekly informativo bulletins:
- STF Informativo Semanal: structured summaries of recent decisions with case references
- STJ Informativo de Jurisprudência: weekly digest, well-tagged by tema
- TST Notícias: less formal but covers important trabalhista decisions

**Approach:**
1. RSS poller running on cron (initially weekly; adjustable)
2. Each item: parse, extract case references, link to underlying acórdão (often available via court's own jurisprudence portal)
3. Store as `NOTICIA_TRIBUNAL` entries with `referenced_decisions: list[str]` linking to other corpus items
4. Backfill the last 24 months on initial run

**Why this matters:** the Notícias often summarize and contextualize new decisions days or weeks before DataJud has them indexed. They keep the corpus fresh on what's actually being decided right now. The summaries themselves often capture the legal significance better than the raw ementa.

#### 3B. Court informativos (more structured than RSS)

STF and STJ publish PDF informativos weekly with editorial summaries. These are often more useful than the news pages because they're explicitly framed for legal research.

Add a separate parser path for informativo PDFs.

### Phase 4 — Landmark cases and published acórdãos (Days 16-19)

#### 4A. STF/STJ landmark anonymized cases

**File:** `src/juris/repertory/ingestion/landmark_cases.py`

The courts themselves publish certain decisions as landmarks (often through their press offices or institutional memory pages), already anonymized when sensitive. Examples:

- STF "Decisões Históricas" page
- STJ "Casos Marcantes" (when published)
- Specific themed collections (e.g., STF's Direito à Vida Privada compilation)

These are explicitly curated for public consumption. Different legal status from raw case files.

**Volume:** small (~50-200) but high-signal.

#### 4B. Published acórdãos via jurisprudence portals

**File:** `src/juris/repertory/ingestion/jurisprudencia_portais.py`

STF, STJ, TST, TRFs all expose jurisprudence search portals. Acórdãos surfaced through these portals are explicitly published *for research purposes* — that's the portal's stated function. This is different from PJe consulta (which is for parties to the case).

**Approach:**
- STF: `portal.stf.jus.br/jurisprudencia/`
- STJ: `scon.stj.jus.br`
- TST: `jurisprudencia.tst.jus.br`
- TRFs: per-region portals

Pull recent acórdãos (last 24 months) by tema/topic. Respect rate limits aggressively — these portals are research tools, not data lakes. ≤1 req/2sec, off-peak hours.

**Volume estimate:** 1,000-3,000 acórdãos, depending on coverage breadth. The corpus is large enough to require selectivity — focus on themes the firm targets first (trabalhista, cível, tributário) rather than exhaustive coverage.

### Phase 5 — Integration and validation (Days 20-21)

#### 5A. Drafter prompt update

The drafter (Sprint 10) has an empty slot for "structural templates." Now that templates exist:

```python
# src/juris/prompts/drafter_v1.py — add section

ESTRUTURA_REFERENCIAL = """
ESTRUTURA REFERENCIAL (modelo OAB-{seccional} para {tipo_peticao}):

Seções típicas:
{secoes_esperadas}

Padrões de fundamentação:
{padroes_fundamentacao}

INSTRUÇÃO: Use esta estrutura como referência. Adapte ao caso concreto.
Não copie trechos textuais — gere texto novo seguindo a estrutura.
"""
```

The Researcher gains a new retrieval step `find_template(tipo_peticao, area_direito)` that returns the best-matching `MODELO_PETICAO`. The drafter consumes it as scaffold.

#### 5B. Citation contract extension

Templates and doutrina don't get cited the same way as jurisprudence:

- Templates: never cited in output (they're scaffolds, not authority)
- Doutrina PD: cited with academic format ("Conforme leciona Bevilácqua, Direito da Família, 1934, p. 234, [paraphrase]")
- Notícias: never cited; only used to surface underlying decisions which may then be cited
- Landmark/published acórdãos: cited normally with `[CITE:source_id]`

Update CitationVerifier to recognize these distinctions.

#### 5C. Retrieval benchmark refresh

Re-run the Sprint 10 retrieval benchmark with the expanded corpus. Expected: recall@3 improves further as more relevant content becomes findable.

Add new test cases to the benchmark that target template retrieval specifically:
- "estrutura de contestação trabalhista" → should return MODELO_PETICAO entries
- "doutrina prescrição quinquenal" → should return DOUTRINA_PD entries

## Operating rules

1. **Respect rate limits, robots.txt, and ToS for every source.** Slow ingestion (≤1 req/2sec) is fine; speed isn't a goal here. Document each source's terms in the per-source ingester.

2. **Source attribution is mandatory.** Every corpus entry has a `source_url`, `source_publisher`, `ingested_at`, and `legal_basis` field documenting why this content can be used.

3. **`legal_basis` is structured:**
   ```python
   class LegalBasis(StrEnum):
       PUBLIC_DOMAIN = "public_domain"               # copyright expired
       OPEN_LICENSE = "open_license"                 # explicitly licensed for reuse
       GOVERNMENT_PUBLICATION = "government_publication"  # public sector publication
       RESEARCH_PORTAL = "research_portal"           # explicit research-purpose publication
       INSTITUTIONAL_TEMPLATE = "institutional_template"  # OAB/Defensoria/CNJ template
   ```
   Every ingester sets this for its content. CitationVerifier respects it.

4. **Ingester idempotency** (per Sprint 10.5 standard). Re-running an ingester updates changed records, doesn't duplicate.

5. **No re-publication of verbatim text.** Templates contribute their *structure* to Juris's outputs, not their text. Doutrina contributes *paraphrased* arguments with proper attribution. Acórdãos contribute their ementas (already designed as the citable unit). News bulletins are never reproduced in output, only used to surface authority.

## Tests

```
tests/unit/repertory/ingestion/
├── test_oab_modelos.py           # parsing, structural extraction
├── test_cnj_modelos.py           # CNJ template parsing
├── test_defensoria_modelos.py    # Defensoria template parsing
├── test_governo_doutrina.py      # government publication parsing
├── test_classicos_pd.py          # public-domain verification, parsing
├── test_court_noticias.py        # RSS feed parsing, deduplication
├── test_landmark_cases.py        # landmark case extraction
└── test_jurisprudencia_portais.py # portal scraping with mocked responses

tests/integration/
└── test_corpus_expansion.py      # end-to-end: ingest, dedup, query, verify
```

Per source: parser test on sample HTML/PDF, error handling on malformed input, idempotency test, rate limit respect (mocked time).

## Definition of Done

- [ ] All Phase 1-4 ingesters built; phase 5 integration complete
- [ ] Corpus grows by ≥3,000 items across the new tiers (target: 5,000-8,000)
- [ ] Every entry has `legal_basis` set; sources documented
- [ ] No verbatim copying of copyrighted material in any corpus entry
- [ ] Drafter consumes MODELO_PETICAO entries as structural scaffolds via the new prompt section
- [ ] Retrieval benchmark recall@3 improves measurably (vs Sprint 10.5 baseline)
- [ ] Court news bulletin ingestion runs as a scheduled job; backfill of last 24 months completed
- [ ] All tests pass; lint and mypy clean
- [ ] Documentation: ADR `0013-public-domain-corpus.md`, source inventory `docs/corpus-sources.md`

## Suggested daily rhythm

- **Day 1:** Discovery and indexing of OAB modelo URLs across major seccionais. Document in `data/oab_modelos_index.json`. Write ADR.
- **Day 2-4:** OAB modelo ingester. Structural extraction. Tests.
- **Day 5:** CNJ modelo ingester.
- **Day 6-7:** Defensoria modelos ingesters (DPU + DPEs).
- **Day 8:** Public-domain verification for classics. Document copyright status per author.
- **Day 9-12:** Government doutrina + classics ingesters.
- **Day 13-15:** Court news ingestion (RSS pollers + informativo PDF parsers). Backfill.
- **Day 16-17:** Landmark cases ingester.
- **Day 18-19:** Published acórdãos via jurisprudence portals.
- **Day 20:** Drafter prompt integration; CitationVerifier extensions.
- **Day 21:** Benchmark refresh; final validation; documentation.

## What NOT to do in Sprint 13

- Use OAB credentials to access non-research-portal case data (separate legal track)
- Scrape commercial doutrina (Saraiva, Forense, RT, JusPodivm) under any guise
- Reproduce verbatim copyrighted text in any corpus entry
- Build per-tenant doutrina ingestion (that's Sprint 14+ when SaaS goes live and customers upload their own purchased books)
- Pursue ColBERT, multi-vector mode, or embedder evaluation (separate retrieval-quality sprint)

## What this enables

After Sprint 13:

- Drafter has structural scaffolds for ~30-50 common petition types
- Retrieval surfaces public-domain doutrina alongside jurisprudence
- Court news keeps the corpus fresh weekly
- Landmark cases and published acórdãos add persuasive depth
- Total corpus: ~10,000+ entries (Sprint 10.5 binding/persuasive + Sprint 13 templates/doutrina/news)

This is enough corpus to validate the drafter on real cases without a litigating partner — you can take a case from STF/STJ landmark collections, draft a hypothetical petition responding to it, and judge quality against the actual decision. That's a usable validation surface even without a daily-user litigator.

The case memory layer (originally Sprint 12) becomes Sprint 14 — it depends on having a litigating user or pilot firm, which Sprint 13 doesn't require.
