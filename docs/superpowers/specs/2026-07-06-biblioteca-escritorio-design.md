# Biblioteca do Escritório (Fase 1 MVP) — Design

**Data:** 2026-07-06 · **Status:** aprovado em conversa (2 rodadas + mescla com revisão externa Codex) · **Relaciona-se a:** ADR-0015 (split-trust), ADR-0016 (PII), ADR-0017 (source mesh), Sprint 6 (corpus dirigido), Sprint 13 (tipos de corpus)

## Objetivo

Formalizar o tier-3 do corpus (acervo do próprio escritório) como produto: o advogado sobe peças, modelos, decisões e doutrina; o CAUSIA aprende **estrutura e estilo** do escritório e usa esse material nas minutas — **sem jamais citar peça interna como autoridade jurídica**. Valor visível: "a minuta saiu com a cara do escritório".

## Decisões de arquitetura (fechadas em conversa, 2026-07-06)

1. **RAG por tenant sobre `repertory/`** — nenhum sistema paralelo. O upload, o registry com proveniência, o isolamento por `tenant_id` e a busca híbrida já existem.
2. **Eixo `uso` como metadado de primeira classe** (contribuição Codex): documento pode ser `fundamento` (citável) ou `estilo` (ensina forma, nunca é citado). **Derivado do tipo por padrão, com override opcional por fonte** — menos fricção no upload, controle quando importa.
3. **Guarda determinística, não instrução de prompt** (mescla): documentos `uso=estilo` são excluídos da recuperação de fundamentos → nunca entram em `allowed_source_ids` → o `MarkerCitationVerifier` existente bloqueia mecanicamente qualquer citação a eles. Defesa em duas camadas pelo preço de uma.
4. **Estilo em dois mecanismos**: few-shot por recuperação (peça do próprio escritório mais similar, por geração — Fase 1) e perfil de estilo destilado editável (Fase 2, LLM local por causa de PII).
5. **MCP não é núcleo** (consenso): consumidor é o drafter interno. Superfície MCP externa fica para Fase 3. **Obsidian/pasta via agente**: Fase 2. **Fine-tuning**: não.
6. **Copy honesta** (pin existente): prometer "isolados por escritório e apagáveis com certificado" — **não** prometer "criptografado em repouso" (não existe hoje) nem "nunca saem do seu computador".
7. **Área de atuação como escopo forte**: no tier privado da Biblioteca, documentos de áreas diferentes não se misturam por default. Trabalhista, empresarial, tributário etc. são filtros duros no upload, busca, cobertura e matching de estilo.

## Invariantes

- **Isolamento por tenant**: todo chunk/fonte da biblioteca carrega `tenant_id`; peça de um escritório jamais aparece para outro (fail-safe já existente em `vector_store.py`).
- **Isolamento por área de atuação**: todo documento privado da Biblioteca carrega `area`; buscas e drafting filtram o tier privado por `area` (ou `geral`, quando explicitamente marcado). Jurisprudência, doutrina e peças trabalhistas não entram em uma minuta empresarial por acidente.
- **PII**: conteúdo de peça é dado de cliente. A Fase 1 **não envia conteúdo bruto para nuvem**: o few-shot entra no prompt pelo caminho normal do drafter e, quando o backend é cloud/browser, passa pelo `DeidentifyingLLM` **fail-closed** (ADR-0016, `core/deid_llm.py`) — exatamente como o restante do prompt. Extração de perfil (Fase 2) = LLM local.
- **Copyright (livros/doutrina)**: o CAUSIA não disponibiliza material doutrinário nem classifica se uma obra é domínio público, licenciada ou protegida. Doutrina enviada pelo advogado entra como material fornecido pelo escritório, sempre tier privado do tenant, nunca cross-tenant, com proveniência e aceite expresso de responsabilidade autoral do escritório.
- **Nenhuma citação a documento `uso=estilo`** pode sobreviver ao verifier. Este é o critério de aceitação central da Fase 1.

## Estado atual verificado (2026-07-06, `main`)

- `POST /api/corpus/upload` (`web/app.py:1207` + `web/corpus_queue.py:289 upload_source_document`): aceita `source_text` OU arquivo (`filename` + `content_base64`, ≤20MB), com `source_type/area/tema/tribunal/source_date/source_url/title/numero_cnj`; registra com proveniência (`content_sha256`) e reingere na hora, tenant-scoped.
- `extract_upload_text` (`corpus_queue.py:253`): **só `.pdf` (pymupdf), `.txt`, `.md`** — falta `.docx`; `python-docx>=1.2.0` já é dependência (usada no export).
- `TipoFonte` (`repertory/corpus/models.py:14`): já tem `MODELO_PETICAO` (hier. 7) e `DOUTRINA_PD` (hier. 6); `TIPO_HIERARQUIA` mapeia autoridade. O chunk ingerido carrega `tipo` (`corpus_queue.py` reingest: `DocumentChunk(tipo=tipo, hierarquia=TIPO_HIERARQUIA[...])`).
- **Gap confirmado**: `agents/researcher.py` não filtra por tipo; `drafter.py:282` monta `allowed_ids = {r.source_id for r in research.supporting + research.opposing}` direto da busca. Peça interna ingerida hoje pode ser recuperada e citada como fundamento.
- Seam de estilo no drafter: Step 5 (`drafter.py:226-248`, templates via `_templates.search`) e Step 5b (`drafter.py:250-276`, `find_template(tipo_peticao, area, tenant_id)` → scaffold de seções). `find_template` (`retrieval/service.py:292`) já é tenant-scoped.
- Console: aba de busca explicável (`/api/corpus/search`, tenant-scoped e em `_EXPENSIVE_API_PREFIXES`), fila/cobertura de corpus (`/api/corpus/coverage`), upload single-file na UI do Acervo/Piloto.
- `RetrievalResult` (`retrieval/service.py:52`) carrega `source_id/score/hierarchy/tribunal/texto` — **não carrega `tipo`** (precisará expor para agrupar resultados e filtrar).

## Componentes da Fase 1

### L1 — Tipos, área e eixo `uso`

- Novos membros de `TipoFonte`: `PECA_ESCRITORIO = "peca_escritorio"` (peça protocolada do próprio escritório; hierarquia 7), `NOTA_INTERNA = "nota_interna"` (tese/playbook interno; hierarquia 7) e `DOUTRINA_ESCRITORIO = "doutrina_escritorio"` (livro/artigo/trecho doutrinário fornecido pelo escritório; hierarquia 6, uso=fundamento). `DOUTRINA_PD` fica apenas para corpus público/legado quando já existir; a Fase 1 não disponibiliza doutrina pelo CAUSIA nem pede que o advogado classifique a obra como domínio público ou protegida.
- **Responsabilidade autoral (`copyright_ack`)**: campo booleano obrigatório para `doutrina_escritorio`. O advogado confirma que tem direito, autorização, licença ou responsabilidade profissional para usar aquele material no seu próprio acervo. O CAUSIA registra a declaração e a proveniência, mas não valida nem assume responsabilidade pelos direitos autorais do conteúdo enviado.
- **Área (`area`) obrigatória no tier privado**: `peca_escritorio`, `modelo_peticao`, `nota_interna` e `doutrina_escritorio` exigem `area` canônica (`trabalhista`, `empresarial`, `tributario`, `civel`, `consumidor`, `familia`, `previdenciario`, `geral`, ...). `geral` é opt-in explícito, não default silencioso.
- Novo mapa canônico no mesmo módulo:
  ```python
  class UsoFonte(StrEnum):
      FUNDAMENTO = "fundamento"   # citável como autoridade
      ESTILO = "estilo"           # ensina forma; nunca citado

  TIPO_USO_DEFAULT: dict[TipoFonte, UsoFonte] = {
      TipoFonte.SUMULA_VINCULANTE: UsoFonte.FUNDAMENTO,
      TipoFonte.RE_STF: UsoFonte.FUNDAMENTO,
      TipoFonte.RESP_REPETITIVO: UsoFonte.FUNDAMENTO,
      TipoFonte.SUMULA: UsoFonte.FUNDAMENTO,
      TipoFonte.JURISPRUDENCIA_UNIFORME: UsoFonte.FUNDAMENTO,
      TipoFonte.PRECEDENTE_LOCAL: UsoFonte.FUNDAMENTO,
      TipoFonte.ACORDAO_LANDMARK: UsoFonte.FUNDAMENTO,
      TipoFonte.ACORDAO_PUBLICADO: UsoFonte.FUNDAMENTO,
      TipoFonte.DOUTRINA_PD: UsoFonte.FUNDAMENTO,   # seed/publica, não upload doutrinário do advogado
      TipoFonte.DOUTRINA_ESCRITORIO: UsoFonte.FUNDAMENTO,
      TipoFonte.NOTICIA_TRIBUNAL: UsoFonte.ESTILO,  # informativo: nunca autoridade
      TipoFonte.MODELO_PETICAO: UsoFonte.ESTILO,
      TipoFonte.PECA_ESCRITORIO: UsoFonte.ESTILO,
      TipoFonte.NOTA_INTERNA: UsoFonte.ESTILO,
  }
  ```
  (Teste exaustivo garante que todo membro novo de `TipoFonte` exija entrada aqui.)
- Fonte no registry ganha campo opcional `uso` (override); ausente → `TIPO_USO_DEFAULT[tipo]`. O chunk ingerido carrega `uso` resolvido (novo campo em `DocumentChunk`).
- **Chunks legados (regra de resolução, correção da revisão externa):** `uso = metadata.uso ?? TIPO_USO_DEFAULT[chunk.tipo] ?? FUNDAMENTO`. Derivar do `tipo` primeiro é essencial: o corpus atual JÁ contém `MODELO_PETICAO` e `NOTICIA_TRIBUNAL` — um default cego para `fundamento` tornaria modelos/notícias antigos citáveis por acidente. Só cai em `fundamento` quando nem `uso` nem `tipo` existem no chunk.
- `CorpusUploadPayload` ganha `uso: str = ""` (opcional, valida contra `UsoFonte`), `area: str` obrigatório para fonte privada, `tipo_peticao: str = ""` (opcional: contestacao/inicial/agravo/recurso/parecer — alimenta cobertura e o matching de estilo) e `copyright_ack: bool = False` (obrigatório só para `doutrina_escritorio`). `fase`/`polo` ficam explicitamente fora da Fase 1 (YAGNI; revisitar com dados do piloto).

### L1b — Proveniência privada de primeira classe (correção da revisão externa)

Hoje `append_accepted_source` **exige `source_url` http(s)** (`corpus_queue.py:350 _public_source_url`; teste `test_corpus_upload.py` espera 400 sem URL). Petição interna, modelo próprio e livro licenciado não têm URL pública — forçar URL produz proveniência falsa.

- Novo campo `provenance_kind: "publica" | "acervo_do_escritorio"` no payload/registro. Default `publica` (comportamento atual intacto, testes existentes verdes).
- Com `acervo_do_escritorio`: `source_url` passa a ser **opcional**; a proveniência auditável vira `filename + content_sha256 + source_date + tenant_id` (todos já capturados) + `source_publisher`/`source_ref` como rótulo do acervo. Para preservar o trial sem cadastro, esse rótulo pode ser genérico (`"acervo do escritório"`) e não deve exigir nome, razão social ou identificação pessoal.
- `_require_provenance` continua exigindo `source_type`, `source_date` e fonte para AMBOS os kinds, mas no kind privado a fonte pode ser esse rótulo genérico do acervo, não uma URL ou publisher público.
- Para `doutrina_escritorio`, o registry grava também `copyright_ack=true` e a versão curta do aviso aceito. Não há `rights_basis`, porque classificar domínio público/licença/copyright não cabe ao CAUSIA.

### L2 — Guarda determinística (o coração da fase)

- `search_jurisprudencia` (caminho do researcher) passa a **excluir chunks `uso=estilo` por default** (parâmetro `include_estilo: bool = False`). **O filtro desce ao nível das stores** (WHERE no FTS + filtro de payload no denso), não pós-`top_k` — filtrar depois do corte deixaria peças de estilo expulsarem fundamentos bons do resultado (`vector_store.py:37` hoje só filtra tenant). Assim, `supporting/opposing` → `allowed_ids` nunca contêm documento de estilo, e o `MarkerCitationVerifier` (inalterado) bloqueia qualquer `[CITE:]` para eles — segunda camada de graça.
- `search_jurisprudencia` ganha também `area: str | None = None`. Quando `tenant_id` e `area` são informados, o tier privado do tenant é filtrado por `(area = area OR area = "geral")`; chunks privados sem `area` não entram em drafting por default. O corpus público/seeds segue disponível como fonte pública, mas a Biblioteca privada não mistura áreas.
- **Consistência com o seam existente**: `find_template` (Step 5b) busca `MODELO_PETICAO` — que é `uso=estilo`. Ele e o novo `find_style_exemplar` chamam a busca com `include_estilo=True` explícito (são consumidores de estilo por definição). Os testes existentes do scaffold continuam verdes.
- **Fix incluído**: `find_template` hoje filtra por `source_id.startswith("modelo_peticao_")` (`retrieval/service.py:319`) — um modelo enviado pelo escritório recebe `source_id` uuid e **nunca seria encontrado**. Passa a filtrar por `RetrievalResult.tipo == "modelo_peticao"` (o campo novo).
- `RetrievalResult` ganha `tipo: str` e `uso: str` (para o agrupamento da UI e auditoria).
- Audit: o evento existente `draft.style_retrieved` passa a registrar `source_id/tipo/uso` do exemplar usado — trilha de "o que alimentou estilo vs. fundamento".
- **Teste de aceitação central**: ingere peça do escritório como `peca_escritorio`, roda draft cujo LLM (fake) tenta citá-la → verifier bloqueia (grounding `blocked`); mesma peça aparece na busca da Biblioteca como "modelo/estilo".

### L3 — Upload em lote + DOCX

- `extract_upload_text` ganha `.docx` via `python-docx` (parágrafos + tabelas em texto; erro legível se corrompido).
- Lote no **front**: a UI itera N arquivos chamando o endpoint existente — **sequencialmente** (concorrência 1) com tratamento de 429/backoff, porque `/api/corpus/upload` está em `_EXPENSIVE_API_PREFIXES` (12/min default). Progresso por arquivo; erros individuais não abortam o lote. Sem endpoint batch novo (YAGNI; 20MB/arquivo já limita).
- Metadados no lote: o usuário define `tipo/área/uso` uma vez para o lote, com ajuste por arquivo depois (edição fica para a lista da L5; MVP: valores do lote aplicam a todos).

### L4 — Few-shot de estilo no drafter

- Novo passo no seam existente (antes do Step 5b): `find_style_exemplar(tipo_peticao, area, tenant_id)` no retrieval service — busca **apenas** chunks `uso=estilo` **do próprio tenant e da mesma área** (`area` ou `geral`; nunca outra área; nunca seed público). O template genérico TJDFT continua como fallback do Step 5b.
- Injeção: trecho do exemplar (limitado a ~2.500 chars, primeira parte estrutural) no `style_text` com moldura explícita: "EXEMPLO DE ESTILO DO SEU ESCRITÓRIO (não citar como fonte): ...".
- Precedência: exemplar do escritório > template da biblioteca `_templates` > scaffold genérico do corpus. Audit registra qual venceu.

### L5 — Aba "Biblioteca" no console

- Nova view `biblioteca` (padrão das views existentes; nav ganha o item — o nav já tem overflow-x para telas estreitas):
  - **Upload em lote**: input multi-file (pdf/docx/txt/md) + selects tipo/área/uso + barra de progresso por arquivo.
  - **Lista do acervo do tenant**: fontes do registry com tipo/uso/área/data/status (dados já existem em `/api/corpus/coverage` + sources; novo `GET /api/library` lista fontes do tenant com esses campos — leitura do registry existente, sem storage novo).
  - **Busca com resultados separados** (UX Codex): reusa `/api/corpus/search` (rota real — `app.py`; passará a devolver `tipo/uso`) e agrupa no cliente: "Fontes jurídicas para citar" (uso=fundamento) e "Modelos e peças do escritório" (uso=estilo, com `include_estilo=1` no endpoint da Biblioteca).
  - **Filtro de área sempre visível**: área selecionada no console restringe upload, lista, busca e cobertura da Biblioteca. A opção "geral" deve ser explícita.
  - **Cobertura**: contadores por tipo/área/tipo_peticao (reuso do coverage) com dica de lacuna ("nenhuma contestação trabalhista ainda", "nenhuma doutrina empresarial ainda").
- Copy honesta na aba: "Seus documentos ficam isolados por escritório e são apagáveis com certificado" (sem promessa de criptografia em repouso).

### L6 — Erasure/LGPD

- Nada novo a construir: `juris tenant erase-data`/purge já cobrem o tenant inteiro (biblioteca incluída, pois vive no repertory + registry do tenant). O spec apenas exige **teste** de que fontes da biblioteca somem no erase.

## Fluxo (draft com biblioteca populada)

```
upload lote (L3) → registry com uso resolvido (L1) → chunks tenant com tipo/uso
draft:
  researcher → search_jurisprudencia(include_estilo=False) → supporting/opposing (só fundamento)
  allowed_ids = fontes citáveis                                  (L2)
  find_style_exemplar(tenant) → style_text "EXEMPLO DE ESTILO…"  (L4)
  _generate(...) → verifier bloqueia [CITE:] fora de allowed_ids (existente)
  audit: style_retrieved{source_id,tipo,uso} + citations_verified
console: aba Biblioteca lista/busca agrupado + cobertura          (L5)
```

## Testes (por componente)

- **L1**: `TIPO_USO_DEFAULT` cobre todos os `TipoFonte` (teste exaustivo do mapa); upload com `uso` inválido → 400; upload privado sem `area` → 400; `doutrina_escritorio` sem `copyright_ack` → 400; chunk legado sem `uso` deriva do `tipo` antes de cair em `fundamento`.
- **L2 (aceitação central)**: peça `peca_escritorio` ingerida não aparece em `search_jurisprudencia` default; aparece com `include_estilo=True`; draft com fake-LLM citando-a → grounding bloqueado; `RetrievalResult.tipo/uso/area` populados; fonte privada de área diferente não entra em busca/draft daquela área.
- **L3**: `.docx` real (fixture pequena) extrai texto; corrompido → `ValueError` legível; >20MB → erro existente.
- **L4**: com exemplar do tenant → `style_text` contém a moldura e o audit registra `uso=estilo`; sem exemplar → fallback ao comportamento atual (testes existentes de template seguem verdes); exemplar de outro tenant jamais retorna.
- **L5**: `GET /api/library` só devolve fontes do tenant; agrupamento fundamento/estilo no payload de busca.
- **L6** (nível certo, correção da revisão externa): após `erase-data`, (a) a chave antiga do tenant é **rejeitada** (401 em `GET /api/library`), (b) `repertory.db` não contém chunks daquele `tenant_id`, (c) o registry/diretório do tenant foi removido, (d) certificado registrado em `compliance-erasure.jsonl`. Lista vazia NÃO é o critério — tenant apagado não autentica.

## Incorporações da revisão externa (Codex, 2026-07-06) — todas aceitas

1. Resolução de `uso` legado deriva do `tipo` do chunk antes do fallback (senão modelos/notícias antigos virariam citáveis). 2. `provenance_kind=acervo_do_escritorio` dispensa URL http(s) — proveniência privada real em vez de URL falsa (L1b). 3. Doutrina enviada pelo advogado vira `doutrina_escritorio` com `copyright_ack`; o CAUSIA não classifica domínio público/licença/copyright nem assume responsabilidade autoral por material que não disponibiliza. 4. `tipo_peticao` no upload/cobertura/matching (aceito; `fase`/`polo` deferidos — YAGNI). 5. Rota corrigida para `/api/corpus/search`. 6. Filtro de `uso` no nível das stores, não pós-`top_k`. 7. Fix do `find_template` (prefixo de `source_id` → filtro por `tipo`). 8. Frase de PII reescrita: "não envia conteúdo bruto; caminho cloud/browser passa por de-id fail-closed". 9. Aceitação de erasure no nível certo (401 + chunks ausentes + certificado, não "lista vazia"). 10. Lote sequencial com backoff de 429 (endpoint está nos prefixos caros). 11. Área de atuação é escopo forte para o tier privado: busca/draft/cobertura não misturam trabalhista com empresarial, salvo marcação explícita `geral`.

## Fora de escopo (Fase 2/3 — specs próprios)

- Pasta/vault via Causia Agent com frontmatter YAML; seções jurídicas via `peticoes/extractor.py`; perfil de estilo destilado editável (LLM local); edição de metadados por fonte na UI; OCR de PDF imagem; MCP `causia-library`; modo local-first premium; criptografia em repouso (e a respectiva copy).

## Riscos e mitigação

- **Estilo contamina fundamento** → guarda em duas camadas (L2) + teste de aceitação central.
- **Peça com dados de cliente no prompt** → few-shot roda no caminho normal do drafter (ADR-0016 já roteia PII para local/de-id); nada novo sai para nuvem.
- **Mistura de áreas de atuação** → `area` obrigatória no upload privado + filtro duro no retrieval privado + teste cross-area.
- **Direitos autorais de doutrina enviada pelo advogado** → CAUSIA não fornece material doutrinário, registra proveniência e aceite de responsabilidade do escritório; material fica privado por tenant e nunca cross-tenant.
- **Lote com metadados errados** → status/curadoria do registry existente; edição por fonte fica explícita na Fase 2.
- **Copy** → pins de honestidade existentes cobrem; L5 usa a fórmula aprovada.
