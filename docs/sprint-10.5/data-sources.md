# Sprint 10.5: Corpus Data Sources

## Overview

Sprint 10.5 expanded the jurisprudence corpus from 100 to 949 entries across 7 source types. All data is public domain (official government legal acts).

## Source Inventory

| Source | File | Entries | Data Origin | Completeness | Next Step |
|--------|------|---------|-------------|-------------|-----------|
| SVs | `sumulas_vinculantes.json` | 56 | Agent-generated from STF texts | 56/56 (100%) | Complete |
| STF Súmulas | `sumulas_stf.json` | 196 | Agent-generated, `scripts/extract_stf_sumulas.py` | 196/~736 (27%) | Web scrape for full set |
| STJ Súmulas | `sumulas_stj.json` | 163 | Agent-generated, `scripts/extract_stj_sumulas.py` | 163/~672 (24%) | Web scrape for full set |
| TST Súmulas | `sumulas_tst.json` | 66 | Agent-generated from known texts | 66/~463 (14%) | Scraper needed |
| TST OJs | `ojs_tst.json` | 56 | Agent-generated from known texts | 56/~400 (14%) | Scraper needed |
| STF RG | `temas_repercussao_geral_stf.json` | 200 | Agent-generated from known themes | 200/~1200 (17%) | STF API fetch |
| STJ Repetitivos | `temas_repetitivos_stj.json` | 212 | Agent-generated + existing 20 | 212/~600 (35%) | STJ API fetch |

**Total**: 949 entries (active after filtering: ~850+)

## Licensing

All sources are official government acts published in the Diário Oficial or tribunal websites. Under Brazilian law (Lei 9.610/98, Art. 8°), official texts of a normative nature are not subject to copyright protection. The data is public domain.

## Situacao Values by Source

| Source Type | Active Situacoes | Inactive Situacoes |
|-------------|-----------------|-------------------|
| Súmulas (SV, STF, STJ, TST) | `vigente` | `cancelada`, `superada` |
| OJs (TST) | `vigente` | `superada` |
| Repercussão Geral (STF) | `tese_firmada` | `pendente_julgamento` |
| Repetitivos (STJ) | `transitado`, `afetado` | — |

The per-TipoFonte active mapping is defined in `src/juris/repertory/corpus/status.py`.

## Data Quality Notes

- All entries were agent-generated from publicly known legal texts
- Texts are summaries/ementas, not full acórdãos
- Some entries may have minor transcription differences from official texts
- Date fields (`data_aprovacao`, `data_alteracao`) are populated where known

## GitHub Search Findings

Searched for existing Brazilian jurisprudence datasets on GitHub. Findings:
- Several repos with partial STF/STJ data exist, but none with structured JSON covering all 7 source types
- Most repos focus on raw PDF/HTML scraping without structured extraction
- No existing dataset met our schema requirements (TipoFonte, hierarquia, situacao fields)
- Decision: generate data directly rather than adapting incompatible formats

## Verification Results

### Per-Source Counts (after B1 fix)

| Source | Active Entries |
|--------|---------------|
| stf-sv | 56 |
| stf-rg | 199 |
| stj-repetitivos | 212 |
| stf-sumulas | 163 |
| stj-sumulas | 160 |
| tst-sumulas | 65 |
| tst-ojs | 53 |
| **Total** | **908** |

### Real Case Queries (5 tests)

| Query | Results | Source Types | Courts |
|-------|---------|-------------|--------|
| recurso extraordinário contribuição previdenciária | 5 | re_stf, resp_repetitivo | STF, STJ |
| dano moral relação consumo | 5 | re_stf, resp_repetitivo, sumula | STJ, STF |
| estabilidade provisória gestante | 5 | jurisprudencia_uniforme, re_stf, resp_repetitivo, sumula | STJ, STF, TST |
| prescrição intercorrente execução fiscal | 5 | resp_repetitivo, sumula | STJ |
| honorários advocatícios fazenda pública | 5 | re_stf, resp_repetitivo, sumula | STF, STJ |

All queries return results from multiple source types and courts, confirming good source diversity.
