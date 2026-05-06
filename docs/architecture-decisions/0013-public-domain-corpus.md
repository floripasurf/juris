# ADR-0013: Public-Domain Corpus Expansion

## Status
Accepted

## Context
The Juris corpus had ~950 jurisprudence items across 7 JSON seed files. Sprint 13 expands this to a multi-tier knowledge base with petition templates, public-domain doutrina, court news, and landmark cases.

## Decision

### New TipoFonte Members
| Type | Hierarquia | Use |
|---|---|---|
| `MODELO_PETICAO` | 7 | Petition templates (scaffold only, never cited) |
| `DOUTRINA_PD` | 6 | Public-domain legal doctrine |
| `NOTICIA_TRIBUNAL` | 7 | Court news/informativos |
| `ACORDAO_LANDMARK` | 3 | Landmark court decisions |
| `ACORDAO_PUBLICADO` | 5 | Published acórdãos |

### Provenance Tracking
Three optional fields added to `FonteJurisprudencia`: `source_url`, `source_publisher`, `legal_basis`. Classified via `LegalBasis` enum.

### Chunking Strategies
| Type | Strategy |
|---|---|
| `MODELO_PETICAO` | `chunk_template()` — section headers, sub-split >512 tokens |
| `DOUTRINA_PD` | `chunk_doutrina()` — paragraph-based, merged, 64-token overlap |
| `NOTICIA_TRIBUNAL` | `chunk_noticia()` — whole article, split only if >512 |
| `ACORDAO_LANDMARK` | Reuses `chunk_acordao()` |
| `ACORDAO_PUBLICADO` | Reuses `chunk_acordao()` |

### Citation Rules
| Type | Citation Behavior |
|---|---|
| `MODELO_PETICAO` | Never cited — scaffold only |
| `DOUTRINA_PD` | Academic style ("Conforme leciona...") |
| `NOTICIA_TRIBUNAL` | Never cited — surfaces underlying decisions only |
| `ACORDAO_LANDMARK` | Normal `[CITE:source_id]` |
| `ACORDAO_PUBLICADO` | Normal `[CITE:source_id]` |

### Registry Architecture
Extended `IngesterEntry` with optional `ingester_class` and `source_dir` fields for class-based dispatch alongside SeedLoader.

### Per-Source ToS Compliance

| Source | Status | Notes |
|---|---|---|
| TJDFT Petições | Compliant | Published institutional templates for public reuse |
| STF Casos Relevantes | Compliant | Government publication, curated by STF |
| STF Informativos | Compliant | Government publication, weekly bulletins |
| OAB Seccionais | Pending | Requires manual URL curation by lawyer |
| CNJ Modelos | Pending | Requires manual URL curation |
| Defensorias | Pending | Requires manual URL curation |
| Governo Doutrina | Pending | Per-source verification needed |
| Court RSS | Compliant | Public RSS feeds |
| Portal Jurisprudência | Pending | ToS check required per portal before implementation |

## Consequences
- Type system supports 7 hierarchy levels (was 6)
- Drafter can scaffold petitions using template structure
- Citation verifier recognizes academic citation format
- Class-based ingesters coexist with seed-based ones in registry
- HTTP-fetching ingesters are gated on manual URL curation or ToS compliance
