# Roadmap — Juris como ferramenta jurídica completa

**Data:** 2026-06-24 · **Status:** norte de produto (vivo)

Unifica todas as peças — código já existente, o SCHEMA da jurisprudência, e os
recursos externos levantados (courtsbr, datasets, LLM/RAG) — num caminho único
para uma ferramenta que **lê, analisa, decide a estratégia, minuta e protocola**,
como SaaS multi-tenant, com aquisição redundante e um corpus cujo fosso é a
**profundidade local**.

---

## 1. Os quatro subsistemas

```
            ┌─────────────────────────────────────────────────────────┐
            │  ENTREGA   agentes (analyzer/drafter/reviewer/defesa) ·   │
            │            web Fase 1 · assinatura PAdES · agente local   │
            └───────────────▲─────────────────────────▲────────────────┘
                            │                         │
            ┌───────────────┴─────────┐   ┌───────────┴────────────────┐
            │ INTELIGÊNCIA            │   │ CORPUS                      │
            │ Filtro (ADR-0017):      │◄──┤ espinha (súmulas/enunciados)│
            │ ranking determinístico  │   │ + escavação (inteiro teor)  │
            │ + linha argumentativa   │   │ SCHEMA espinha_jurisprudencia│
            └───────────────▲─────────┘   └───────────▲────────────────┘
                            │                         │
            ┌───────────────┴─────────────────────────┴────────────────┐
            │ AQUISIÇÃO  Source Mesh (ADR-0017): MNI · DataJud · eSAJ ·  │
            │            DJE · scrapers (courtsbr) · corpus — redundante │
            └───────────────────────────────────────────────────────────┘
```

| Subsistema | Papel | Já existe no juris | Recursos externos que encaixam |
|---|---|---|---|
| **Aquisição (Source Mesh)** | obter processo/jurisprudência/intimação por várias fontes redundantes | `busca/` (multi-canal, dedup CNJ, corroboração), `search/` (adapters+doctor), MNI/token, DataJud, `connect`/diferencial | **courtsbr**: `esaj`(cpopg/cjsg), `dje`, `stj`, `tjsp`, `stfstj` — blueprints de raspagem por tribunal |
| **Corpus** | base de duas camadas (espinha barata + escavação = fosso) | `repertory/` (3-tier, HNSW, reranker), `enunciados_tjmg.json` (157 fichas) | **stfstj**/**RulingBR** (precedentes STF/STJ p/ espinha nível 1); **legalnlp** (embeddings PT-jurídico) |
| **Inteligência (Filtro+Estratégia)** | escolher a melhor jurisprudência + a linha argumentativa | retrieval híbrido, ranking determinístico (ADR-0014), `MarkerCitationVerifier`, `defesa_analyzer`, `nivel_hierarquico`/`superior_relacionada` (SCHEMA) | **LeNER-Br** (de-id/entidades — ADR-0016); **Juru/Sabiá** (LLM jurídico local); **LRAGE/LegalBench.PT** (avaliação de retrieval+raciocínio) |
| **Entrega** | minuta, revisão, assinatura, protocolo, UI | agentes drafter/reviewer/researcher, `demo`/`connect`, web Fase 1, PAdES (ADR-0011), agente local (ADR-0015) | **JurisMiner** (helpers: kwic, fuzzy, timeline) p/ enriquecimento |

---

## 2. Princípios que amarram tudo

1. **Redundância vira sinal** (ADR-0017): dado obtido por N fontes independentes tem confiança maior. O mesh não é só failover — alimenta o filtro.
2. **Determinístico antes de LLM**: o ranking de jurisprudência e a verificação de citação são determinísticos e auditáveis; o LLM *propõe* a linha argumentativa, mas os critérios são explícitos e as citações verificadas (princípio "não inventar jurisprudência").
3. **Fosso é a escavação local** (SCHEMA §1): profundidade numa comarca > cobertura nacional rasa. A espinha torna a escavação *dirigida*.
4. **PII fica local** (ADR-0016): conteúdo de processo é sensível; cloud só de-identificado ou público.
5. **Token nunca vai à nuvem** (ADR-0015): operações de chave (mTLS, PAdES) no agente local.

---

## 3. Mapa de recursos externos → encaixe → status

| Recurso | Tipo | Onde encaixa | Ação |
|---|---|---|---|
| courtsbr/**esaj** | scraper R | Source Mesh: `cpopg/cposg` (processo) + `cjpg/cjsg` (jurisprudência) | portar lógica p/ adapter Python; estudar captcha vs. regra do projeto |
| courtsbr/**stfstj** | scraper+dados R | Corpus espinha nível 1 (STF/STJ) | ingerir → preenche corpus (resolve `test_corpus_verification`) |
| courtsbr/**dje** | scraper R | Source Mesh: intimações/publicações sem token | provider alternativo de `IntimacaoSource` |
| courtsbr/**JurisMiner** | utils R | Enriquecimento (SCHEMA §6): `jus_kwic`, `busca_fuzzy`, `cnj_sequencia`, timeline | portar ideias p/ `repertory/ingestion` + analyzer |
| **RulingBR** | dataset | Corpus: 10k decisões STF (estrutura de acórdão) | ingestão batch (datado) |
| **LeNER-Br** | dataset/modelo NER | De-id (ADR-0016) + extração de entidades do acórdão | avaliar no spike de de-id (vs Presidio) |
| **legalnlp** | embeddings PT-jurídico | Corpus: embedding afinado ao domínio | benchmark vs BGE-M3 |
| **Juru/Sabiá** | LLM jurídico | `llm_router`: opção local p/ PII | integrar como provider de LLM |
| **LRAGE / LegalBench.PT** | benchmark/eval | medir retrieval+minuta | harness de avaliação do drafter |

---

## 4. Fases (sequência de execução)

**Fase 0 — fundações (✅ em grande parte feito)**
Leitura MNI/mTLS validada; pipeline demo (ler→analisar→prazos→minutar→revisar→auditar); `connect` (avisos+seed+diferencial); web Fase 1 (lista + conectar + minutar); interfaces de serviço (ADR-0015); PII/IA-de-preferência (ADR-0016).

**Fase 1 — Source Mesh + Filtro (ADR-0017)** ← *próximo*
1. Registro de provider profiles (trust/saúde/público/captcha) sobre `busca/`. ← *primeira fatia*
2. Modo corroboração generalizado (já parcial em `busca/orchestrator`).
3. Escore composto do filtro (relevância + nível + vigência + corroboração).
4. Seleção da linha argumentativa (judge-panel ancorado + verificado).

**Fase 2 — Corpus dirigido (SCHEMA §7)**
1. Espinha nacional (súmulas STF/STJ/TST + 27 TJs/6 TRFs) — ingerir `enunciados_tjmg.json` + `stfstj`/`RulingBR`.
2. Enriquecimento por IA (preencher `tema_chave`, limpar OCR, normalizar CNJ — JurisMiner).
3. Escavação-piloto numa comarca/área de domínio (inteiro teor níveis 4-5, começando pelos `precedentes_processos`).
4. Validação local onde você conhece os juízes → afina o `nivel_hierarquico` e o fit-ao-decisor.

**Fase 3 — Qualidade & de-id**
1. De-id (LeNER-Br/Presidio) → habilita cloud-de-identificado.
2. Eval (LRAGE/LegalBench.PT) → métrica de retrieval+minuta no piloto.
3. LLM jurídico (Juru) no caminho PII-local.

**Fase 4 — SaaS multi-tenant**
Agente local remoto (ADR-0015 Fase 2), armazenamento por-conta, onboarding de escritórios, descoberta eSAJ-OAB para tribunais não-PJe.

---

## 5. O fluxo do advogado (visão integrada)

1. **Conecta o token** → `connect`: importa acervo (avisos + seed) + diferencial.
2. **Abre um processo** → Source Mesh lê por fonte redundante; movimentos → prazos.
3. **Pede estratégia** → Filtro: ranqueia jurisprudência (relevância+nível+vigência+corroboração, citações verificadas) → seleciona linha argumentativa (ancorada no corpus + fit ao decisor local + resiliência ao adversário).
4. **Gera a minuta** → drafter usa as citações verificadas; reviewer + contraponto.
5. **Assina e protocola** → PAdES no agente local + MNI.

> Cada etapa degrada graciosamente: fonte que cai derruba confiança, não o pipeline; corpus raso vira raspagem dirigida; sem LLM local cai p/ cloud-de-identificado ou modo rascunho.
