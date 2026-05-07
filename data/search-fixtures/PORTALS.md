# Portal URL Patterns — Juris Search Adapters

Reference for adapter unit tests. Each section documents the request shape and response structure for a given court portal.

---

## STF — Supremo Tribunal Federal

- **Base URL**: `https://jurisprudencia.stf.jus.br/pages/search`
- **Method**: GET
- **Content type**: JSON API
- **Session required**: No
- **CSRF required**: No

### Query params

| Param | Example | Notes |
|---|---|---|
| `base` | `acordaos` | Fixed value |
| `pesquisa_inteiro_teor` | `false` | Full-text toggle |
| `sinonimo` | `true` | Synonym expansion |
| `plural` | `true` | Plural expansion |
| `radicais` | `false` | Stem search |
| `buscaExata` | `true` | Exact phrase |
| `page` | `1` | 1-indexed |
| `pageSize` | `10` | Results per page |
| `queryString` | `improbidade administrativa` | URL-encoded search term |
| `sort` | `_score` | Sort field |
| `sortBy` | `desc` | Sort direction |

### Response shape

```json
{
  "result": [{ "id", "title", "classeNumero", "relator", "dataJulgamento", "description", "url", "orgaoJulgador", "publicacao" }],
  "totalCount": 123,
  "page": 1,
  "pageSize": 10
}
```

---

## STJ — Superior Tribunal de Justiça

- **Base URL**: `https://scon.stj.jus.br/SCON/pesquisar.jsp`
- **Method**: GET
- **Content type**: HTML
- **Session required**: No
- **CSRF required**: No

### Query params

| Param | Example | Notes |
|---|---|---|
| `livre` | `improbidade administrativa` | Free-text search |
| `b` | `ACOR` | Base: ACOR = acórdãos |
| `thesaurus` | `JURIDICO` | Legal thesaurus |
| `p` | `true` | Pagination enabled |

### Response shape

HTML page with `<div class="divResult">` containers, each containing `.divDataDocumento`, `.divEmenta`, and `.divDocumento` child elements.

---

## TST — Tribunal Superior do Trabalho

- **Base URL**: `https://jurisprudencia.tst.jus.br/rest/documentos/acordao`
- **Method**: GET
- **Content type**: JSON API
- **Session required**: No
- **CSRF required**: No

### Query params

| Param | Example | Notes |
|---|---|---|
| `query` | `improbidade administrativa` | URL-encoded |
| `pageSize` | `10` | Results per page |
| `page` | `1` | 1-indexed |

### Response shape

```json
{
  "items": [{ "id", "numeroProcesso", "relator", "dataJulgamento", "ementa", "url", "orgaoJulgador" }],
  "total": 45,
  "page": 1,
  "pageSize": 10
}
```

---

## TRF1 — Tribunal Regional Federal da 1ª Região

- **Base URL**: `https://trf1.jus.br/sjur/pesquisar`
- **Method**: GET
- **Content type**: HTML
- **Session required**: No

### Query params

| Param | Example |
|---|---|
| `livre` | `improbidade administrativa` |

### Response shape

HTML with tabular results inside `<table class="resultado">`. Each `<tr>` row contains process number, relator, date, and ementa snippet.

---

## TRF2 — Tribunal Regional Federal da 2ª Região

- **Base URL**: `https://trf2.jus.br/jurisprudencia/pesquisa`
- **Method**: GET
- **Content type**: HTML
- **Session required**: No

### Query params

Similar to TRF1. Uses `livre={query}` as the main search param.

### Response shape

HTML with `<div class="resultado-item">` blocks per result.

---

## TRF3 — Tribunal Regional Federal da 3ª Região

- **Base URL**: `https://web.trf3.jus.br/base-textual/Home/ListaResumida`
- **Method**: GET
- **Content type**: HTML
- **Session required**: No

### Query params

| Param | Example |
|---|---|
| `strPesq` | `improbidade administrativa` |

### Response shape

Well-structured HTML. Results in `<table id="tabelaResultado">`. Each row has columns: Processo, Data, Relator, Ementa. Pagination via `<div id="paginacao">`.

---

## TRF4 — Tribunal Regional Federal da 4ª Região

- **Base URL**: `https://jurisprudencia.trf4.jus.br/pesquisa/resultado_pesquisa.php`
- **Method**: GET
- **Content type**: HTML
- **Session required**: No

### Query params

| Param | Example | Notes |
|---|---|---|
| `tipo_pesquisa` | `1` | 1 = livre |
| `txtPesquisaLivre` | `improbidade administrativa` | URL-encoded |

### Response shape

HTML with `<div class="acEmenta">` per result. Includes `<span class="acNumeroProcesso">`, `<span class="acRelator">`, `<span class="acData">`.

---

## TRF5 — Tribunal Regional Federal da 5ª Região

- **Base URL**: `https://trf5.jus.br/cp/pesquisar`
- **Method**: GET
- **Content type**: HTML
- **Session required**: No

### Query params

Similar to TRF4. Uses `txtPesquisa={query}`.

### Response shape

HTML. Results in `<ul class="resultados">`, each `<li>` contains header with process number and a `<p class="ementa">` block.

---

## TRF6 — Tribunal Regional Federal da 6ª Região

- **Base URL**: `https://trf6.jus.br/jurisprudencia/pesquisa`
- **Method**: GET
- **Content type**: HTML
- **Session required**: No
- **Note**: Newest TRF, created in 2022. Covers Minas Gerais (split from TRF1).

### Query params

| Param | Example |
|---|---|
| `q` | `improbidade administrativa` |

### Response shape

Modern HTML. Results in `<article class="julgado">` elements. Includes `<header>` with metadata and `<section class="ementa">`.

---

## TJSP — Tribunal de Justiça de São Paulo (ESAJ)

- **Base URL**: `https://esaj.tjsp.jus.br/cjsg/resultadoCompleta.do`
- **Method**: POST (2-step flow)
- **Content type**: HTML (form-encoded POST)
- **Session required**: Yes
- **CSRF required**: Yes (ViewState token)

### 2-step authentication flow

**Step 1 — GET the search page to capture session tokens**

```
GET https://esaj.tjsp.jus.br/cjsg/consultaCompleta.do
```

Extract from response HTML:
- `javax.faces.ViewState` hidden input value
- Session cookie (`JSESSIONID`) from `Set-Cookie` header

**Step 2 — POST the search**

```
POST https://esaj.tjsp.jus.br/cjsg/resultadoCompleta.do
Content-Type: application/x-www-form-urlencoded
Cookie: JSESSIONID=<captured>
```

Form fields:

| Field | Value |
|---|---|
| `conversationId` | (from page) |
| `dadosConsulta.pesquisaLivre` | `improbidade administrativa` |
| `tipoNumero` | `UNIFICADO` |
| `numeroDigitoAnoUnificado` | (empty) |
| `foroNumeroUnificado` | (empty) |
| `dadosConsulta.dtInicio` | (optional, dd/MM/yyyy) |
| `dadosConsulta.dtFim` | (optional) |
| `dadosConsulta.ordenacao` | `DESC` |
| `javax.faces.ViewState` | `<captured from step 1>` |

### Response shape

HTML with `<tr class="fundocinza1">` and `<tr class="fundocinza2">` alternating rows. Each row contains: process number as link, relator, organ, date, and ementa preview. Full ementa requires secondary fetch to `/cjsg/getArquivo.do?cdAcordao=<id>`.
