# Biblioteca do Escritório (Fase 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tier-3 do corpus como produto: o escritório sobe peças/modelos/decisões/doutrina; o drafter aprende estrutura e estilo do escritório; **nenhuma peça interna jamais é citada como autoridade** (guarda determinística em duas camadas).

**Architecture:** Tudo sobre `repertory/` existente. Eixo `uso` (fundamento/estilo) derivado do `TipoFonte` com override por fonte; filtro de estilo desce ao nível das stores (SQL/payload) para não poluir o `top_k`; `allowed_source_ids` do drafter passa a conter só fundamentos e o `MarkerCitationVerifier` (inalterado) bloqueia o resto. Estilo entra por `find_style_exemplar` tenant-only no seam `style_text` que já existe. Spec: `docs/superpowers/specs/2026-07-06-biblioteca-escritorio-design.md`.

**Tech Stack:** Python 3.12 + uv, FastAPI, SQLite FTS5 (+ Qdrant opcional), pytest, python-docx (já dep), SPA vanilla (`index.html`).

## Global Constraints

- Gates por task: ciclo TDD com `uv run pytest <arquivos> -q`; antes de cada commit `uv run ruff check src/juris tests` e `uv run mypy src/juris`. Suíte baseline: **1891 passed**.
- Ids canônicos: `UsoFonte.FUNDAMENTO = "fundamento"`, `UsoFonte.ESTILO = "estilo"`. Tipos novos: `peca_escritorio`, `nota_interna`, `doutrina_privada`. `provenance_kind ∈ {"publica","acervo_do_escritorio"}` (default `"publica"`). `rights_basis ∈ {"dominio_publico","obra_do_escritorio","licenca_do_escritorio","ato_oficial"}`.
- Regra de resolução de uso (inclusive legados): `uso_explicito ?? TIPO_USO_DEFAULT[tipo] ?? FUNDAMENTO`. NUNCA default cego para fundamento quando o tipo é conhecido.
- Isolamento por tenant é invariante: exemplar de estilo vem SÓ do próprio tenant; busca nunca vaza entre escritórios.
- Copy honesta (pin de teste existente): não escrever "criptografado em repouso" nem "nunca saem do seu computador" em NENHUMA string de UI.
- SQL das stores: constantes de módulo, valores de enum interno apenas — nunca interpolar input de usuário.
- Commits `type(scope): subject`; um por task; trabalhar em `main`.

---

## File Structure

| Arquivo | Papel |
|---|---|
| `src/juris/repertory/corpus/models.py` | T1: `UsoFonte`, tipos novos, `TIPO_USO_DEFAULT`, `resolve_uso`, `RIGHTS_BASIS_VALUES` |
| `src/juris/web/corpus_queue.py` | T2: proveniência privada + campos novos; T3: DOCX |
| `src/juris/web/app.py` | T2: payload; T8: `/api/library`, search com tipo/uso, coverage |
| `src/juris/repertory/chunking.py` | T4: `DocumentChunk.uso` |
| `src/juris/repertory/vector_store.py` | T4: coluna/filtros SQLite; T5: payload/filtro Qdrant |
| `src/juris/repertory/retrieval/hybrid.py` | T6: repasse `include_estilo`/`tenant_only` |
| `src/juris/repertory/retrieval/service.py` | T6: `RetrievalResult.tipo/uso`, fix `find_template`, `find_style_exemplar` |
| `src/juris/agents/drafter.py` | T7: step de estilo do escritório |
| `src/juris/web/static/index.html` | T9: aba Biblioteca |

Ordem: T1 → T2/T3 (independentes entre si) → T4 → T5 → T6 → T7 → T8 → T9 → T10.

---

### Task 1: L1 — `UsoFonte`, tipos novos e mapa de uso

**Files:**
- Modify: `src/juris/repertory/corpus/models.py` (enum `TipoFonte` linha 14, `TIPO_HIERARQUIA` linha 30)
- Test: `tests/unit/repertory/test_uso_fonte.py` (novo)

**Interfaces:**
- Produces (todas as tasks seguintes consomem): `UsoFonte` (StrEnum), `TipoFonte.PECA_ESCRITORIO/NOTA_INTERNA/DOUTRINA_PRIVADA`, `TIPO_USO_DEFAULT: dict[TipoFonte, UsoFonte]`, `ESTILO_SOURCE_TYPES: frozenset[str]`, `RIGHTS_BASIS_VALUES: frozenset[str]`, `resolve_uso(tipo: TipoFonte | str | None, override: str | None = None) -> UsoFonte`.

- [ ] **Step 1: Teste que falha** — criar `tests/unit/repertory/test_uso_fonte.py`:

```python
"""Eixo uso (fundamento/estilo) — spec Biblioteca do Escritório L1."""

from __future__ import annotations

import pytest

from juris.repertory.corpus.models import (
    ESTILO_SOURCE_TYPES,
    RIGHTS_BASIS_VALUES,
    TIPO_HIERARQUIA,
    TIPO_USO_DEFAULT,
    TipoFonte,
    UsoFonte,
    resolve_uso,
)


def test_mapa_de_uso_cobre_todos_os_tipos_exaustivamente() -> None:
    # Novo membro de TipoFonte sem entrada aqui deve quebrar ESTE teste.
    assert set(TIPO_USO_DEFAULT.keys()) == set(TipoFonte)


def test_tipos_de_estilo_sao_os_esperados() -> None:
    estilo = {t for t, u in TIPO_USO_DEFAULT.items() if u is UsoFonte.ESTILO}
    assert estilo == {
        TipoFonte.MODELO_PETICAO,
        TipoFonte.NOTICIA_TRIBUNAL,
        TipoFonte.PECA_ESCRITORIO,
        TipoFonte.NOTA_INTERNA,
    }
    assert ESTILO_SOURCE_TYPES == frozenset(t.value for t in estilo)


def test_novos_tipos_tem_hierarquia() -> None:
    assert TIPO_HIERARQUIA[TipoFonte.PECA_ESCRITORIO] == 7
    assert TIPO_HIERARQUIA[TipoFonte.NOTA_INTERNA] == 7
    assert TIPO_HIERARQUIA[TipoFonte.DOUTRINA_PRIVADA] == 6


def test_resolve_uso_deriva_do_tipo_e_respeita_override() -> None:
    assert resolve_uso(TipoFonte.PECA_ESCRITORIO) is UsoFonte.ESTILO
    assert resolve_uso("modelo_peticao") is UsoFonte.ESTILO           # aceita string
    assert resolve_uso(TipoFonte.ACORDAO_PUBLICADO) is UsoFonte.FUNDAMENTO
    assert resolve_uso(TipoFonte.ACORDAO_PUBLICADO, "estilo") is UsoFonte.ESTILO  # override
    assert resolve_uso(None) is UsoFonte.FUNDAMENTO                   # sem tipo nem uso → fundamento
    assert resolve_uso("tipo_desconhecido_qualquer") is UsoFonte.FUNDAMENTO
    with pytest.raises(ValueError):
        resolve_uso(TipoFonte.SUMULA, "citavel")                      # override inválido


def test_rights_basis_values() -> None:
    assert RIGHTS_BASIS_VALUES == frozenset(
        {"dominio_publico", "obra_do_escritorio", "licenca_do_escritorio", "ato_oficial"}
    )
```

- [ ] **Step 2:** Run: `uv run pytest tests/unit/repertory/test_uso_fonte.py -q` — Expected: FAIL (ImportError `UsoFonte`).

- [ ] **Step 3: Implementar** em `src/juris/repertory/corpus/models.py` — acrescentar ao enum `TipoFonte` (após `ACORDAO_PUBLICADO`):

```python
    PECA_ESCRITORIO = "peca_escritorio"  # hierarquia=7 — peça protocolada do próprio escritório
    NOTA_INTERNA = "nota_interna"  # hierarquia=7 — tese/playbook interno
    DOUTRINA_PRIVADA = "doutrina_privada"  # hierarquia=6 — obra licenciada/própria (rights_basis obrigatório)
```

Acrescentar a `TIPO_HIERARQUIA` as três entradas (`PECA_ESCRITORIO: 7, NOTA_INTERNA: 7, DOUTRINA_PRIVADA: 6`). Depois do dict `TIPO_HIERARQUIA`, adicionar:

```python
class UsoFonte(StrEnum):
    """Como uma fonte pode ser usada pelo pipeline (spec Biblioteca L1).

    FUNDAMENTO: citável como autoridade jurídica (entra em allowed_source_ids).
    ESTILO: ensina estrutura/forma; NUNCA é citada — o verifier bloqueia.
    """

    FUNDAMENTO = "fundamento"
    ESTILO = "estilo"


TIPO_USO_DEFAULT: dict[TipoFonte, UsoFonte] = {
    TipoFonte.SUMULA_VINCULANTE: UsoFonte.FUNDAMENTO,
    TipoFonte.RE_STF: UsoFonte.FUNDAMENTO,
    TipoFonte.RESP_REPETITIVO: UsoFonte.FUNDAMENTO,
    TipoFonte.SUMULA: UsoFonte.FUNDAMENTO,
    TipoFonte.JURISPRUDENCIA_UNIFORME: UsoFonte.FUNDAMENTO,
    TipoFonte.PRECEDENTE_LOCAL: UsoFonte.FUNDAMENTO,
    TipoFonte.MODELO_PETICAO: UsoFonte.ESTILO,
    TipoFonte.DOUTRINA_PD: UsoFonte.FUNDAMENTO,
    TipoFonte.NOTICIA_TRIBUNAL: UsoFonte.ESTILO,
    TipoFonte.ACORDAO_LANDMARK: UsoFonte.FUNDAMENTO,
    TipoFonte.ACORDAO_PUBLICADO: UsoFonte.FUNDAMENTO,
    TipoFonte.PECA_ESCRITORIO: UsoFonte.ESTILO,
    TipoFonte.NOTA_INTERNA: UsoFonte.ESTILO,
    TipoFonte.DOUTRINA_PRIVADA: UsoFonte.FUNDAMENTO,
}

# Valores string dos tipos estilo-only, para os SQLs/payloads das stores.
ESTILO_SOURCE_TYPES: frozenset[str] = frozenset(
    t.value for t, uso in TIPO_USO_DEFAULT.items() if uso is UsoFonte.ESTILO
)

# Base de direitos exigida para doutrina (spec L1): sem base válida, não ingere.
RIGHTS_BASIS_VALUES: frozenset[str] = frozenset(
    {"dominio_publico", "obra_do_escritorio", "licenca_do_escritorio", "ato_oficial"}
)


def resolve_uso(tipo: TipoFonte | str | None, override: str | None = None) -> UsoFonte:
    """Resolve o uso efetivo: override explícito > default do tipo > fundamento.

    Args:
        tipo: TipoFonte (ou seu valor string) do documento; None quando desconhecido.
        override: valor explícito de uso vindo do upload/registro ("" = ausente).

    Returns:
        UsoFonte efetivo.

    Raises:
        ValueError: override não-vazio que não é um UsoFonte válido.
    """
    if override:
        return UsoFonte(override)  # ValueError natural para valor inválido
    if tipo is None:
        return UsoFonte.FUNDAMENTO
    try:
        tipo_enum = tipo if isinstance(tipo, TipoFonte) else TipoFonte(str(tipo))
    except ValueError:
        return UsoFonte.FUNDAMENTO
    return TIPO_USO_DEFAULT.get(tipo_enum, UsoFonte.FUNDAMENTO)
```

- [ ] **Step 4:** Run: `uv run pytest tests/unit/repertory/test_uso_fonte.py tests/unit -q -k "corpus or repertory"` — Expected: PASS (novos + existentes; `test_ingester_registry`-like suites seguem verdes pois o enum só cresceu).

- [ ] **Step 5:** Gates + commit:

```bash
uv run ruff check src/juris tests && uv run mypy src/juris && uv run pytest -q
git add src/juris/repertory/corpus/models.py tests/unit/repertory/test_uso_fonte.py
git commit -m "feat(corpus): eixo uso fundamento/estilo + tipos da Biblioteca do Escritório (L1)"
```

---

### Task 2: L1b — Proveniência privada, `rights_basis` e campos novos no upload

**Files:**
- Modify: `src/juris/web/corpus_queue.py` (`_require_provenance` linha ~72, `append_accepted_source` linha ~88, `upload_source_document` linha ~289)
- Modify: `src/juris/web/app.py` (`CorpusUploadPayload`)
- Test: `tests/unit/web/test_corpus_upload.py` (estender — harness `tenant_env`/`PROVENANCE` já existe nesse arquivo)

**Interfaces:**
- Consumes: `RIGHTS_BASIS_VALUES`, `UsoFonte`, `TipoFonte` (Task 1).
- Produces: payload/registro aceitam `provenance_kind`, `uso`, `tipo_peticao`, `rights_basis`; fonte `acervo_do_escritorio` sem `source_url` é aceita; doutrina sem `rights_basis` → `ValueError` (→ 400). O registro persiste os 4 campos novos (Task 8 lê).

- [ ] **Step 1: Testes que falham** — acrescentar a `tests/unit/web/test_corpus_upload.py`:

```python
    def test_acervo_do_escritorio_dispensa_url(self, tenant_env) -> None:
        payload = {
            "title": "Contestação modelo — cobrança",
            "source_type": "peca_escritorio",
            "source_date": "2025-11-10",
            "source_publisher": "Escritório A",
            "provenance_kind": "acervo_do_escritorio",
            "tipo_peticao": "contestacao",
            "area": "civel",
            "source_text": TEXTO,
        }
        resp = tenant_env.post("/api/corpus/upload", json=payload, headers={"X-API-Key": "key-a"})
        assert resp.status_code == 201, resp.text
        source = resp.json()["source"]
        assert source["provenance_kind"] == "acervo_do_escritorio"
        assert source["uso"] == "estilo"            # derivado de peca_escritorio
        assert source["tipo_peticao"] == "contestacao"
        assert not source.get("source_url")

    def test_provenance_publica_continua_exigindo_url(self, tenant_env) -> None:
        payload = {**PROVENANCE, "source_text": TEXTO}
        payload.pop("source_url")
        resp = tenant_env.post("/api/corpus/upload", json=payload, headers={"X-API-Key": "key-a"})
        assert resp.status_code == 400  # comportamento atual preservado

    def test_doutrina_sem_rights_basis_nao_ingere(self, tenant_env) -> None:
        payload = {
            "title": "Manual de Processo Civil",
            "source_type": "doutrina_privada",
            "source_date": "2024-01-01",
            "source_publisher": "Editora X",
            "provenance_kind": "acervo_do_escritorio",
            "source_text": TEXTO,
        }
        resp = tenant_env.post("/api/corpus/upload", json=payload, headers={"X-API-Key": "key-a"})
        assert resp.status_code == 400
        assert "rights_basis" in resp.json()["detail"]["message"]

    def test_doutrina_com_rights_basis_ingere(self, tenant_env) -> None:
        payload = {
            "title": "Manual de Processo Civil",
            "source_type": "doutrina_privada",
            "source_date": "2024-01-01",
            "source_publisher": "Editora X",
            "provenance_kind": "acervo_do_escritorio",
            "rights_basis": "licenca_do_escritorio",
            "source_text": TEXTO,
        }
        resp = tenant_env.post("/api/corpus/upload", json=payload, headers={"X-API-Key": "key-a"})
        assert resp.status_code == 201, resp.text
        assert resp.json()["source"]["rights_basis"] == "licenca_do_escritorio"

    def test_uso_override_invalido_e_400(self, tenant_env) -> None:
        payload = {**PROVENANCE, "source_text": TEXTO, "uso": "citavel"}
        resp = tenant_env.post("/api/corpus/upload", json=payload, headers={"X-API-Key": "key-a"})
        assert resp.status_code == 400
```

Nota: `tenant_env` — conferir no arquivo como a fixture expõe o client (se devolve `TestClient`, os posts acima usam-na direto; ajustar chamada conforme o padrão dos testes vizinhos, ex. `client.post`).

- [ ] **Step 2:** Run: `uv run pytest tests/unit/web/test_corpus_upload.py -q` — Expected: FAIL (campos desconhecidos ignorados/`provenance_kind` ausente do registro).

- [ ] **Step 3: Implementar.** (a) `CorpusUploadPayload` (app.py) ganha:

```python
    provenance_kind: str = Field(default="publica", max_length=32)
    uso: str = Field(default="", max_length=16)
    tipo_peticao: str = Field(default="", max_length=64)
    rights_basis: str = Field(default="", max_length=32)
```

(b) `corpus_queue.py` — em `_require_provenance(payload)`, acrescentar ao final:

```python
    kind = str(payload.get("provenance_kind") or "publica")
    if kind not in {"publica", "acervo_do_escritorio"}:
        msg = "provenance_kind deve ser 'publica' ou 'acervo_do_escritorio'."
        raise ValueError(msg)
    tipo_raw = str(payload.get("source_type") or "")
    if tipo_raw in {TipoFonte.DOUTRINA_PD.value, TipoFonte.DOUTRINA_PRIVADA.value}:
        rights = str(payload.get("rights_basis") or "")
        if rights not in RIGHTS_BASIS_VALUES:
            msg = (
                "rights_basis é obrigatório para doutrina "
                f"({', '.join(sorted(RIGHTS_BASIS_VALUES))}) — sem base de direitos não ingere."
            )
            raise ValueError(msg)
    override = str(payload.get("uso") or "")
    if override:
        resolve_uso(tipo_raw or None, override)  # ValueError se inválido
```

(imports no topo do módulo: `from juris.repertory.corpus.models import RIGHTS_BASIS_VALUES, TipoFonte, resolve_uso` — `TipoFonte`/`TIPO_HIERARQUIA` já são importados; conferir e mesclar).

(c) `append_accepted_source`: tornar a URL condicional e persistir os campos novos —

```python
    _require_provenance(payload)
    content_hash = _resolve_content_hash(payload)
    kind = str(payload.get("provenance_kind") or "publica")
    if kind == "acervo_do_escritorio":
        raw_url = str(payload.get("source_url") or "").strip()
        source_url = _public_source_url(raw_url) if raw_url else ""
    else:
        source_url = _public_source_url(payload.get("source_url"))
```

e no dict `record`, acrescentar (mantendo os campos atuais):

```python
        "provenance_kind": kind,
        "uso": resolve_uso(str(payload.get("source_type") or "") or None, str(payload.get("uso") or "") or None).value,
        "tipo_peticao": str(payload.get("tipo_peticao") or ""),
        "rights_basis": str(payload.get("rights_basis") or ""),
```

(d) `upload_source_document`: incluir `"provenance_kind", "uso", "tipo_peticao", "rights_basis"` na tupla de chaves copiadas para `record_payload`.

- [ ] **Step 4:** Run: `uv run pytest tests/unit/web/test_corpus_upload.py tests/unit/web -q` — Expected: PASS (novos + todos os existentes, incl. `test_missing_provenance_url_is_400` intacto).

- [ ] **Step 5:** Gates + commit:

```bash
uv run ruff check src/juris tests && uv run mypy src/juris
git add src/juris/web/corpus_queue.py src/juris/web/app.py tests/unit/web/test_corpus_upload.py
git commit -m "feat(corpus): proveniência privada (acervo do escritório), rights_basis e uso/tipo_peticao no upload (L1b)"
```

---

### Task 3: L3 — DOCX no `extract_upload_text`

**Files:**
- Modify: `src/juris/web/corpus_queue.py:253` (`extract_upload_text`)
- Test: `tests/unit/web/test_corpus_upload.py` (estender)

**Interfaces:**
- Produces: uploads `.docx` extraem texto (parágrafos + células de tabela); corrompido → `ValueError` legível (→ 400).

- [ ] **Step 1: Testes que falham** — acrescentar (o teste GERA o .docx com python-docx, sem fixture binária no repo):

```python
    def test_docx_base64_is_extracted_and_ingested(self, tenant_env) -> None:
        import io

        from docx import Document

        doc = Document()
        doc.add_paragraph("CONTESTAÇÃO. " + TEXTO)
        table = doc.add_table(rows=1, cols=1)
        table.rows[0].cells[0].text = "Cláusula de tabela relevante."
        buf = io.BytesIO()
        doc.save(buf)
        payload = {
            **PROVENANCE,
            "filename": "contestacao.docx",
            "content_base64": base64.b64encode(buf.getvalue()).decode(),
        }
        resp = tenant_env.post("/api/corpus/upload", json=payload, headers={"X-API-Key": "key-a"})
        assert resp.status_code == 201, resp.text

    def test_docx_corrompido_e_400_legivel(self, tenant_env) -> None:
        payload = {
            **PROVENANCE,
            "filename": "quebrado.docx",
            "content_base64": base64.b64encode(b"nao sou um docx").decode(),
        }
        resp = tenant_env.post("/api/corpus/upload", json=payload, headers={"X-API-Key": "key-a"})
        assert resp.status_code == 400
        assert "DOCX" in resp.json()["detail"]["message"] or "docx" in resp.json()["detail"]["message"]
```

- [ ] **Step 2:** Run: `uv run pytest tests/unit/web/test_corpus_upload.py -q -k docx` — Expected: FAIL (extensão não suportada → 400 no caso feliz).

- [ ] **Step 3: Implementar** — em `extract_upload_text`, antes do ramo `.txt/.md`:

```python
    elif name.endswith(".docx"):
        import io

        from docx import Document
        from docx.opc.exceptions import PackageNotFoundError

        try:
            document = Document(io.BytesIO(data))
        except (PackageNotFoundError, KeyError, ValueError) as exc:
            msg = "não foi possível ler o DOCX — exporte novamente ou cole o texto."
            raise ValueError(msg) from exc
        parts = [p.text for p in document.paragraphs if p.text.strip()]
        for table in document.tables:
            for row in table.rows:
                parts.extend(cell.text for cell in row.cells if cell.text.strip())
        text = "\n".join(parts)
```

Atualizar o docstring da função (`.pdf, .docx, .txt ou .md`) e a mensagem de extensão não suportada, se listar extensões.

- [ ] **Step 4:** Run: `uv run pytest tests/unit/web/test_corpus_upload.py -q` — Expected: PASS.

- [ ] **Step 5:** Gates + commit:

```bash
uv run ruff check src/juris tests && uv run mypy src/juris
git add src/juris/web/corpus_queue.py tests/unit/web/test_corpus_upload.py
git commit -m "feat(corpus): upload .docx (python-docx) com erro legível (L3)"
```

---

### Task 4: L2 — Filtro de uso na store SQLite (FTS) + `DocumentChunk.uso`

**Files:**
- Modify: `src/juris/repertory/chunking.py:22` (`DocumentChunk`)
- Modify: `src/juris/repertory/vector_store.py` (schema `_init_tables:286`, `upsert:~320`, `search_text:~356`, SQLs `:29-46`)
- Modify: `src/juris/web/corpus_queue.py` (reingest ~196-231: resolver uso no chunk)
- Test: `tests/unit/repertory/test_vector_store_uso.py` (novo)

**Interfaces:**
- Consumes: `ESTILO_SOURCE_TYPES`, `resolve_uso`, `UsoFonte` (T1).
- Produces: `DocumentChunk.uso: str = ""`; `SearchResult.source_type: str = ""` e `SearchResult.uso: str = ""`; `LocalFTSStore.search_text(query, top_k=10, tenant_id=None, *, include_estilo: bool = False, tenant_only: bool = False)`; coluna `uso` na tabela `chunks` (migração idempotente). Filtro aplicado **no WHERE**, com derivação por `source_type` para chunks legados sem `uso`.

- [ ] **Step 1: Testes que falham** — criar `tests/unit/repertory/test_vector_store_uso.py`:

```python
"""Filtro determinístico de uso na store FTS — L2 (aplicado ANTES do corte)."""

from __future__ import annotations

from pathlib import Path

from juris.repertory.chunking import DocumentChunk
from juris.repertory.corpus.models import TipoFonte
from juris.repertory.vector_store import LocalFTSStore


def _chunk(cid: str, tipo: TipoFonte, text: str, uso: str = "") -> DocumentChunk:
    return DocumentChunk(
        chunk_id=cid, source_id=f"src-{cid}", source_type=tipo, text=text, uso=uso
    )


def _store(tmp_path: Path) -> LocalFTSStore:
    store = LocalFTSStore(tmp_path / "repertory.db")
    store.upsert(
        [
            _chunk("a1", TipoFonte.ACORDAO_PUBLICADO, "honorarios sucumbenciais fazenda publica"),
            _chunk("m1", TipoFonte.MODELO_PETICAO, "honorarios sucumbenciais modelo de contestacao"),
            _chunk("p1", TipoFonte.PECA_ESCRITORIO, "honorarios sucumbenciais peca do escritorio", uso="estilo"),
        ],
        [[], [], []],
        tenant_id="escritorio-a",
    )
    return store


def test_busca_default_exclui_estilo(tmp_path: Path) -> None:
    results = _store(tmp_path).search_text("honorarios", top_k=10, tenant_id="escritorio-a")
    ids = {r.source_id for r in results}
    assert "src-a1" in ids
    assert "src-m1" not in ids  # legado sem uso: derivado do source_type
    assert "src-p1" not in ids  # uso explícito


def test_include_estilo_devolve_tudo_com_uso_preenchido(tmp_path: Path) -> None:
    results = _store(tmp_path).search_text(
        "honorarios", top_k=10, tenant_id="escritorio-a", include_estilo=True
    )
    by_id = {r.source_id: r for r in results}
    assert set(by_id) == {"src-a1", "src-m1", "src-p1"}
    assert by_id["src-a1"].uso == "fundamento"
    assert by_id["src-m1"].uso == "estilo"       # derivado
    assert by_id["src-m1"].source_type == "modelo_peticao"


def test_tenant_only_exclui_seed_publico(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(
        [_chunk("pub1", TipoFonte.MODELO_PETICAO, "honorarios modelo publico do seed")],
        [[]],
        tenant_id=None,  # seed público
    )
    results = store.search_text(
        "honorarios", top_k=10, tenant_id="escritorio-a", include_estilo=True, tenant_only=True
    )
    ids = {r.source_id for r in results}
    assert "src-pub1" not in ids and "src-p1" in ids


def test_chunk_legado_sem_coluna_uso_migra(tmp_path: Path) -> None:
    # Simula db criado antes da coluna: cria store, dropa a coluna via recriação crua.
    import sqlite3

    db = tmp_path / "repertory.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE chunks (chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
            source_type TEXT, text TEXT NOT NULL, metadata TEXT,
            position INTEGER DEFAULT 0, tenant_id TEXT);
        CREATE VIRTUAL TABLE chunks_fts USING fts5(text);
        """
    )
    conn.execute(
        "INSERT INTO chunks VALUES ('l1','src-l1','modelo_peticao','honorarios modelo antigo','{}',0,NULL)"
    )
    conn.execute("INSERT INTO chunks_fts (rowid, text) SELECT rowid, text FROM chunks")
    conn.commit()
    conn.close()

    store = LocalFTSStore(db)  # _init_tables deve adicionar a coluna sem quebrar
    results = store.search_text("honorarios", top_k=10)
    assert all(r.source_id != "src-l1" for r in results)  # legado estilo continua excluído
```

- [ ] **Step 2:** Run: `uv run pytest tests/unit/repertory/test_vector_store_uso.py -q` — Expected: FAIL (`DocumentChunk` sem `uso`; `search_text` sem parâmetros novos).

- [ ] **Step 3: Implementar.** (a) `DocumentChunk` ganha campo `uso: str = ""` (docstring: "uso resolvido — fundamento/estilo; vazio = derivar do source_type").

(b) `vector_store.py`: no topo, `from juris.repertory.corpus.models import ESTILO_SOURCE_TYPES, resolve_uso`. Gerar a cláusula de derivação como constante (valores de enum interno — seguro):

```python
_ESTILO_IN = ", ".join(f"'{t}'" for t in sorted(ESTILO_SOURCE_TYPES))
_USO_EFETIVO = (
    "COALESCE(NULLIF(c.uso, ''), CASE WHEN c.source_type IN (" + _ESTILO_IN + ") "
    "THEN 'estilo' ELSE 'fundamento' END)"
)
```

Reescrever os SQLs de busca como template de módulo com 3 eixos combináveis (tenant × estilo × tenant_only). Para manter "constantes, nunca interpolação de user input", montar as 4 variantes no import (`_SEARCH_SQL`, `_SEARCH_SQL_TENANT`, `_SEARCH_SQL_TENANT_ONLY`, com e sem `AND {_USO_EFETIVO} = 'fundamento'`) — todas incluem `c.source_type, {_USO_EFETIVO} AS uso_efetivo` no SELECT.

(c) `_init_tables`: após o `executescript` atual, migração idempotente:

```python
        try:
            self._conn.execute("ALTER TABLE chunks ADD COLUMN uso TEXT")
        except sqlite3.OperationalError:
            pass  # coluna já existe
```

(d) `upsert`: resolver e gravar — `uso_val = chunk.uso or resolve_uso(chunk.source_type).value` e incluir `uso` no INSERT (coluna adicional).

(e) `search_text(self, query, top_k=10, tenant_id=None, *, include_estilo=False, tenant_only=False)`: escolher a variante de SQL; construir `SearchResult(..., source_type=row_source_type, uso=row_uso_efetivo)`. `SearchResult` ganha os dois campos com default `""`.

(f) `corpus_queue.py` reingest: após `chunks = chunk_fonte(fonte)`, setar em cada chunk `chunk.uso = str(record.get("uso") or "") or resolve_uso(tipo).value` e `chunk.metadata["tipo_peticao"] = record.get("tipo_peticao")` (import de `resolve_uso` já feito na T2). `DocumentChunk` é frozen? **Não** — conferir: se for frozen/slots, usar `dataclasses.replace`.

- [ ] **Step 4:** Run: `uv run pytest tests/unit/repertory -q && uv run pytest tests/unit/web/test_corpus_upload.py -q` — Expected: PASS (novos + stores existentes; se algum teste existente de `search_text` cobrir MODELO_PETICAO no resultado default, atualizá-lo para `include_estilo=True` com comentário citando L2).

- [ ] **Step 5:** Gates + commit:

```bash
uv run ruff check src/juris tests && uv run mypy src/juris && uv run pytest -q
git add src/juris/repertory/chunking.py src/juris/repertory/vector_store.py src/juris/web/corpus_queue.py tests/unit/repertory/test_vector_store_uso.py
git commit -m "feat(repertory): filtro de uso no WHERE da store FTS + DocumentChunk.uso (L2)"
```

---

### Task 5: L2 — Qdrant: payload `uso` + filtro

**Files:**
- Modify: `src/juris/repertory/vector_store.py` (`QdrantVectorStore:114` — upsert payload e `search`)
- Test: `tests/unit/repertory/test_vector_store_uso.py` (estender)

**Interfaces:**
- Consumes: T4 (`SearchResult.uso/source_type`, `ESTILO_SOURCE_TYPES`).
- Produces: `QdrantVectorStore.search(..., include_estilo: bool = False, tenant_only: bool = False)`; payload dos pontos ganha `uso` e `source_type`.

- [ ] **Step 1: Ler** `QdrantVectorStore` inteiro (`vector_store.py:114-260`) — anotar como o payload é montado no upsert e como `_tenant_filter` compõe o `Filter`.

- [ ] **Step 2: Teste que falha** (sem servidor Qdrant — testa a construção do filtro):

```python
def test_qdrant_filter_exclui_estilo_por_default() -> None:
    pytest.importorskip("qdrant_client")
    from juris.repertory.vector_store import QdrantVectorStore

    flt = QdrantVectorStore._search_filter("escritorio-a", include_estilo=False, tenant_only=False)
    rendered = str(flt)
    assert "uso" in rendered and "estilo" in rendered  # must_not uso=estilo presente
    flt_all = QdrantVectorStore._search_filter("escritorio-a", include_estilo=True, tenant_only=False)
    assert "estilo" not in str(flt_all)
```

- [ ] **Step 3: Implementar**: novo classmethod `_search_filter(tenant_id, *, include_estilo, tenant_only)` que parte do filtro de tenant existente (variante `must=[tenant_match]` quando `tenant_only`) e, quando `not include_estilo`, adiciona `must_not=[FieldCondition(key="uso", match=MatchValue(value="estilo"))]`. `search()` ganha os dois kwargs e usa `_search_filter`. Upsert: payload ganha `"uso": chunk.uso or resolve_uso(chunk.source_type).value` e `"source_type": chunk.source_type.value`; resultado de busca popula `SearchResult.uso/source_type` do payload. Nota de operação (docstring): pontos legados sem `uso` não são excluídos pelo `must_not` de campo ausente? **Verificar semântica**: em Qdrant, `must_not` com match em campo ausente NÃO exclui o ponto — comportamento correto aqui (legado Qdrant já falha fechado por tenant e será reingerido; documentar no docstring).

- [ ] **Step 4:** Run: `uv run pytest tests/unit/repertory/test_vector_store_uso.py -q` — Expected: PASS (skip limpo se `qdrant_client` ausente).

- [ ] **Step 5:** Gates + commit:

```bash
uv run ruff check src/juris tests && uv run mypy src/juris
git add src/juris/repertory/vector_store.py tests/unit/repertory/test_vector_store_uso.py
git commit -m "feat(repertory): filtro de uso no payload Qdrant (L2)"
```

---

### Task 6: L2 — Retrieval service: `include_estilo`, `RetrievalResult.tipo/uso`, fix `find_template`, `find_style_exemplar`

**Files:**
- Modify: `src/juris/repertory/retrieval/hybrid.py:38` (`HybridRetriever.search`)
- Modify: `src/juris/repertory/retrieval/service.py` (`RetrievalResult:52`, `search_jurisprudencia:130`, `find_template:292`)
- Test: `tests/unit/repertory/test_retrieval_uso.py` (novo)

**Interfaces:**
- Consumes: stores com `include_estilo`/`tenant_only` (T4/T5).
- Produces: `search_jurisprudencia(..., include_estilo: bool = False, tenant_only: bool = False)`; `RetrievalResult.tipo: str = ""` e `.uso: str = ""`; `find_template` filtra por `tipo == "modelo_peticao"`; **novo** `find_style_exemplar(self, tipo_peticao: str, area_direito: str | None = None, tenant_id: str | None = None) -> RetrievalResult | None` (busca `include_estilo=True, tenant_only=True`, filtra `uso == "estilo"`, prioriza match de `metadata.tipo_peticao`). T7 consome `find_style_exemplar`.

- [ ] **Step 1: Testes que falham** — criar `tests/unit/repertory/test_retrieval_uso.py` usando o harness real da store (sem mock da própria lógica):

```python
"""search_jurisprudencia exclui estilo; find_style_exemplar é tenant-only — L2/L4."""

from __future__ import annotations

from pathlib import Path

import pytest

from juris.repertory.chunking import DocumentChunk
from juris.repertory.corpus.models import TipoFonte
from juris.repertory.retrieval.hybrid import HybridRetriever
from juris.repertory.retrieval.service import RepertoryService
from juris.repertory.vector_store import LocalFTSStore


class _NoopEmbedder:
    def embed_single(self, text: str):  # denso desligado: só o caminho FTS
        return None


def _service(tmp_path: Path) -> RepertoryService:
    store = LocalFTSStore(tmp_path / "repertory.db")
    store.upsert(
        [
            DocumentChunk(chunk_id="a1", source_id="src-acordao", source_type=TipoFonte.ACORDAO_PUBLICADO,
                          text="honorarios sucumbenciais fazenda publica equidade",
                          metadata={"hierarquia": 5, "tribunal": "tjmg"}),
            DocumentChunk(chunk_id="p1", source_id="src-peca", source_type=TipoFonte.PECA_ESCRITORIO,
                          text="honorarios sucumbenciais contestacao do escritorio",
                          metadata={"hierarquia": 7, "tipo_peticao": "contestacao"}, uso="estilo"),
        ],
        [[], []],
        tenant_id="escritorio-a",
    )
    retriever = HybridRetriever(dense_store=store, sparse_store=store, embedder=_NoopEmbedder())
    return RepertoryService(retriever=retriever)


def test_search_default_nao_traz_estilo(tmp_path: Path) -> None:
    results = _service(tmp_path).search_jurisprudencia("honorarios", tenant_id="escritorio-a")
    ids = {r.source_id for r in results}
    assert "src-acordao" in ids and "src-peca" not in ids
    hit = next(r for r in results if r.source_id == "src-acordao")
    assert hit.tipo == "acordao_publicado" and hit.uso == "fundamento"


def test_find_style_exemplar_tenant_only(tmp_path: Path) -> None:
    service = _service(tmp_path)
    exemplar = service.find_style_exemplar("contestacao", tenant_id="escritorio-a")
    assert exemplar is not None and exemplar.source_id == "src-peca"
    assert exemplar.uso == "estilo"
    # Outro tenant não vê a peça do escritório A:
    assert service.find_style_exemplar("contestacao", tenant_id="escritorio-b") is None
    # Sem tenant → nunca devolve peça privada:
    assert service.find_style_exemplar("contestacao", tenant_id=None) is None
```

Nota: conferir a assinatura real do construtor `RepertoryService` (`service.py:~118`, `self._retriever = retriever`) e ajustar a instânciação do teste ao padrão do arquivo (há testes existentes de service — copiar o setup deles se divergir).

- [ ] **Step 2:** Run: `uv run pytest tests/unit/repertory/test_retrieval_uso.py -q` — Expected: FAIL.

- [ ] **Step 3: Implementar.** (a) `HybridRetriever.search(..., include_estilo: bool = False, tenant_only: bool = False)`: repassar aos dois caminhos (`self._dense.search(..., include_estilo=include_estilo, tenant_only=tenant_only)` e `search_text(...)` idem; o ramo fallback não-FTS idem). A ABC `VectorStore.search` ganha os kwargs com defaults (atualizar contrato + docstring).

(b) `search_jurisprudencia(..., include_estilo: bool = False, tenant_only: bool = False)` → repassa ao retriever; na conversão final, `RetrievalResult(..., tipo=result.source_type, uso=result.uso)`. `RetrievalResult` ganha `tipo: str = ""` e `uso: str = ""` (docstring).

(c) `find_template`: trocar `templates = [r for r in results if r.source_id.startswith("modelo_peticao_")]` por `templates = [r for r in results if r.tipo == TipoFonte.MODELO_PETICAO.value]` e a chamada interna passa `include_estilo=True`.

(d) Novo método no service:

```python
    def find_style_exemplar(
        self,
        tipo_peticao: str,
        area_direito: str | None = None,
        tenant_id: str | None = None,
    ) -> RetrievalResult | None:
        """Peça/modelo do PRÓPRIO escritório para exemplar de estilo (L4).

        Busca só o tier privado do tenant (tenant_only) incluindo documentos de
        estilo; prioriza match exato de tipo_peticao nos metadados. Nunca devolve
        conteúdo de outro tenant nem do seed público.
        """
        if not tenant_id:
            return None
        query = f"{tipo_peticao} {area_direito or ''}".strip()
        results = self.search_jurisprudencia(
            query=query, top_k=5, tenant_id=tenant_id, include_estilo=True, tenant_only=True
        )
        style = [r for r in results if r.uso == UsoFonte.ESTILO.value]
        if not style:
            return None
        exact = [r for r in style if (r.metadata_tipo_peticao or "") == tipo_peticao]
        return (exact or style)[0]
```

`metadata_tipo_peticao`: o `RetrievalResult` não carrega metadata hoje — adicionar campo `metadata_tipo_peticao: str = ""` populado de `result.metadata.get("tipo_peticao", "")` na conversão (o metadata do chunk já recebe `tipo_peticao` desde a T4f).

- [ ] **Step 4:** Run: `uv run pytest tests/unit/repertory -q` — Expected: PASS (novos + `find_template` existentes: se algum teste usar o prefixo `modelo_peticao_` em source_id fake, ele continua passando pois esses fixtures também têm `source_type` correto — verificar e ajustar fixture se necessário citando o fix L2).

- [ ] **Step 5:** Gates + commit:

```bash
uv run ruff check src/juris tests && uv run mypy src/juris && uv run pytest -q
git add src/juris/repertory/retrieval/hybrid.py src/juris/repertory/retrieval/service.py tests/unit/repertory/test_retrieval_uso.py
git commit -m "feat(retrieval): include_estilo + tipo/uso no resultado; fix find_template; find_style_exemplar tenant-only (L2/L4)"
```

---

### Task 7: L4 — Estilo do escritório no drafter + TESTE DE ACEITAÇÃO CENTRAL

**Files:**
- Modify: `src/juris/agents/drafter.py` (novo step entre Step 5 e Step 5b, ~linha 249)
- Test: `tests/unit/agents/test_drafter_estilo_escritorio.py` (novo; harness espelha `tests/unit/agents/test_grounding.py` — FakeLLM/FakeResearcher/_agent/_request/_context)

**Interfaces:**
- Consumes: `find_style_exemplar` (T6).
- Produces: quando há exemplar do tenant, `style_text` começa com `EXEMPLO DE ESTILO DO SEU ESCRITÓRIO (não citar como fonte):` + trecho `[:2500]`; audit `draft.style_retrieved` ganha `{"origem": "escritorio", "source_id", "tipo", "uso"}`. Precedência: exemplar do escritório > templates `_templates` > scaffold `find_template`.

- [ ] **Step 1: Testes que falham** — criar o arquivo copiando o harness de `test_grounding.py` (FakeLLM com `model` param, FakeResearcher com `src-1`, `_request/_context`) e adicionando um fake de repertory com os dois métodos:

```python
class _FakeRepertoryStyle:
    """Repertory fake: sem templates genéricos; com exemplar do escritório."""

    def __init__(self, exemplar) -> None:
        self._exemplar = exemplar

    def find_style_exemplar(self, tipo_peticao, area_direito=None, tenant_id=None):
        return self._exemplar if tenant_id == "escritorio-a" else None

    def find_template(self, tipo_peticao, area_direito=None, tenant_id=None):
        return None


@pytest.mark.asyncio
async def test_exemplar_do_escritorio_entra_no_style_text() -> None:
    from juris.repertory.retrieval.service import RetrievalResult

    exemplar = RetrievalResult(
        source_id="src-peca", score=1.0, hierarchy=7, hierarchy_label="Nivel 7",
        tribunal="", texto="EXCELENTÍSSIMO SENHOR... estrutura da peça do escritório " * 50,
        tipo="peca_escritorio", uso="estilo",
    )
    captured: dict = {}

    class _SpyLLM(FakeLLM):
        async def complete(self, prompt, system=None, schema=None, max_tokens=1024, temperature=0.0):
            captured["prompt"] = prompt
            return await super().complete(prompt, system, schema, max_tokens, temperature)

    agent = DrafterAgent(
        llm=_SpyLLM("Minuta com [CITE:src-1]."),
        repertory=cast(RepertoryService, _FakeRepertoryStyle(exemplar)),
        researcher=cast(Researcher, FakeResearcher()),
        verifier=MarkerCitationVerifier(cast(RepertoryService, object())),
        tenant_id="escritorio-a",
    )
    result = await agent.draft(_request(), _context())
    assert "EXEMPLO DE ESTILO DO SEU ESCRITÓRIO (não citar como fonte)" in captured["prompt"]
    assert result.is_grounded


@pytest.mark.asyncio
async def test_ACEITACAO_CENTRAL_peca_interna_citada_e_bloqueada() -> None:
    """O critério da Fase 1: LLM cita a peça interna → verifier bloqueia."""
    exemplar = ...  # mesmo RetrievalResult acima
    agent = DrafterAgent(
        llm=FakeLLM("Conforme [CITE:src-peca], procede."),  # cita o EXEMPLAR (estilo!)
        repertory=cast(RepertoryService, _FakeRepertoryStyle(exemplar)),
        researcher=cast(Researcher, FakeResearcher()),      # allowed_ids = {src-1}
        verifier=MarkerCitationVerifier(cast(RepertoryService, object())),
        tenant_id="escritorio-a",
    )
    result = await agent.draft(_request(), _context())
    assert result.is_grounded is False
    assert "src-peca" in result.grounding_report.failed_citation_ids
```

Conferir a assinatura do construtor `DrafterAgent` (tem `tenant_id`? — o Step 5b usa `self._tenant_id`, então sim; confirmar nome do kwarg no `__init__`, `drafter.py:112`).

- [ ] **Step 2:** Run: `uv run pytest tests/unit/agents/test_drafter_estilo_escritorio.py -q` — Expected: primeiro teste FAIL (moldura ausente); o de aceitação já pode passar (verifier atual) — mantê-lo mesmo assim: é o pino de regressão do invariante.

- [ ] **Step 3: Implementar** — em `drafter.py`, imediatamente antes do bloco "Step 5b" (linha ~250), inserir:

```python
        # Step 5a-bis: exemplar de estilo do PRÓPRIO escritório (Biblioteca, L4).
        # Precede templates genéricos: a peça da própria firma ensina o estilo real.
        if not style_text:
            try:
                exemplar = self._repertory.find_style_exemplar(
                    tipo_peticao=request.tipo_peticao.value,
                    area_direito=context.ramo_justica,
                    tenant_id=self._tenant_id,
                )
            except Exception:  # noqa: BLE001 - estilo é enriquecimento, nunca derruba o draft
                logger.debug("style_exemplar_skipped")
                exemplar = None
            if exemplar is not None:
                style_text = (
                    "EXEMPLO DE ESTILO DO SEU ESCRITÓRIO (não citar como fonte):\n"
                    + exemplar.texto[:2500]
                )
                self._log_audit(
                    "draft.style_retrieved",
                    request.numero_cnj,
                    {
                        "origem": "escritorio",
                        "source_id": exemplar.source_id,
                        "tipo": exemplar.tipo,
                        "uso": exemplar.uso,
                    },
                    result,
                )
```

Atenção à ordem real: o Step 5 (`_templates`) roda antes e pode ter preenchido `style_text` — o spec manda exemplar do escritório vencer templates genéricos, então **mover** este bloco para ANTES do Step 5 atual (e o Step 5/5b só rodam `if not style_text`, como já fazem no 5b; adicionar o guard `if not style_text` ao Step 5 se não houver). Fakes existentes sem `find_style_exemplar`: o `getattr`-style do Step 5 não existe aqui — usar `getattr(self._repertory, "find_style_exemplar", None)` e só chamar se `callable`, para não quebrar os fakes dos testes existentes (`test_grounding.py` usa `cast(RepertoryService, object())`).

- [ ] **Step 4:** Run: `uv run pytest tests/unit/agents -q` — Expected: PASS (novos + grounding + ai_model existentes).

- [ ] **Step 5:** Gates + commit:

```bash
uv run ruff check src/juris tests && uv run mypy src/juris && uv run pytest -q
git add src/juris/agents/drafter.py tests/unit/agents/test_drafter_estilo_escritorio.py
git commit -m "feat(drafter): exemplar de estilo do escritório no style_text + pino de aceitação central (L4)"
```

---

### Task 8: L5 — APIs: `/api/library`, busca com tipo/uso, cobertura com tipo_peticao

**Files:**
- Modify: `src/juris/web/app.py` (novo endpoint + `search_corpus:1154`)
- Modify: `src/juris/web/corpus_queue.py` (coverage: contagem por `tipo_peticao` e `uso`)
- Test: `tests/unit/web/test_library_api.py` (novo; harness `tenant_env` de `test_corpus_upload.py`)

**Interfaces:**
- Consumes: registro com campos novos (T2); `RetrievalResult.tipo/uso` (T6).
- Produces: `GET /api/library` → `{"items": [{id, title, source_type, uso, area, tipo_peticao, source_date, status, provenance_kind, rights_basis}], "coverage": {...}}` (tenant-scoped); `GET /api/corpus/search?q=...&include_estilo=1` → resultados com `tipo` e `uso`; coverage ganha `tipo_peticao` e `uso` em `by`.

- [ ] **Step 1: Testes que falham** — criar `tests/unit/web/test_library_api.py`: upload de 1 fonte `peca_escritorio` (payload da T2) + 1 `acordao_publicado`; asserts: `GET /api/library` com a chave do tenant devolve os 2 itens com `uso` correto; sem chave → 401 (ou tenant público vazio, conforme o comportamento dos endpoints vizinhos — copiar o padrão de `test_corpus_upload`); `GET /api/corpus/search?q=honorarios` não traz a peça; com `include_estilo=1` traz, com `uso == "estilo"` no JSON; coverage inclui `{"tipo_peticao": {"contestacao": 1}}`.

```python
def test_library_lista_fontes_do_tenant(tenant_env) -> None:
    _upload_peca(tenant_env)      # helper local: payload T2 com key-a
    _upload_acordao(tenant_env)
    resp = tenant_env.get("/api/library", headers={"X-API-Key": "key-a"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    by_type = {i["source_type"]: i for i in items}
    assert by_type["peca_escritorio"]["uso"] == "estilo"
    assert by_type["peca_escritorio"]["tipo_peticao"] == "contestacao"
    assert by_type["acordao_publicado"]["uso"] == "fundamento"


def test_search_agrupavel_por_uso(tenant_env) -> None:
    _upload_peca(tenant_env)
    _upload_acordao(tenant_env)
    sem = tenant_env.get("/api/corpus/search?q=honorarios", headers={"X-API-Key": "key-a"}).json()
    assert all(r.get("uso") != "estilo" for r in sem["results"])
    com = tenant_env.get(
        "/api/corpus/search?q=honorarios&include_estilo=1", headers={"X-API-Key": "key-a"}
    ).json()
    assert any(r.get("uso") == "estilo" for r in com["results"])
```

- [ ] **Step 2:** Run: `uv run pytest tests/unit/web/test_library_api.py -q` — Expected: FAIL (404 /api/library).

- [ ] **Step 3: Implementar.** (a) Em `corpus_queue.py`: `coverage_report` (função existente que monta `"by"` com `_counts`) ganha `"tipo_peticao": _counts(sources, "tipo_peticao")` e `"uso": _counts(sources, "uso")`. Nova função:

```python
def list_library_items(root: Path) -> list[dict[str, object]]:
    """Fontes do tenant com os campos que a aba Biblioteca exibe (L5)."""
    fields = (
        "id", "title", "source_type", "uso", "area", "tipo_peticao",
        "source_date", "status", "provenance_kind", "rights_basis", "reingest_status",
    )
    return [
        {k: record.get(k, "") for k in fields}
        for record in list_accepted_sources(root)
    ]
```

(b) Em `app.py`, seguindo o padrão dos endpoints de corpus (tenant_scoped_dir + to_thread):

```python
@app.get("/api/library")
async def get_library(tenant: Tenant = Depends(current_tenant)) -> dict[str, object]:
    """Biblioteca do Escritório: fontes do tenant + cobertura (L5)."""
    from juris.web.auth import tenant_scoped_dir
    from juris.web.corpus_queue import coverage_report, list_library_items

    root = tenant_scoped_dir(tenant, _out_root())
    items = await asyncio.to_thread(list_library_items, root)
    coverage = await asyncio.to_thread(coverage_report, root)
    return {"items": items, "coverage": coverage}
```

(conferir o nome real da função de coverage no módulo — o endpoint `/api/corpus/coverage` existente a chama; reusar exatamente a mesma).

(c) `search_corpus` (app.py:1154): novo parâmetro `include_estilo: bool = Query(False)`; repassar ao `search_jurisprudencia`/`explain_ranking` (conferir qual dos dois monta o resultado — incluir `"tipo": r.tipo, "uso": r.uso` no dict serializado de cada hit).

- [ ] **Step 4:** Run: `uv run pytest tests/unit/web -q` — Expected: PASS.

- [ ] **Step 5:** Gates + commit:

```bash
uv run ruff check src/juris tests && uv run mypy src/juris
git add src/juris/web/app.py src/juris/web/corpus_queue.py tests/unit/web/test_library_api.py
git commit -m "feat(web): GET /api/library + busca com tipo/uso + cobertura por tipo_peticao (L5)"
```

---

### Task 9: L5 — Aba "Biblioteca" no console

**Files:**
- Modify: `src/juris/web/static/index.html` (nav, nova section `data-view="biblioteca"`, JS)

**Interfaces:**
- Consumes: `GET /api/library`, `POST /api/corpus/upload` (T2/T3), `GET /api/corpus/search?include_estilo=1` (T8).
- Produces: aba funcional com upload em lote sequencial (backoff 429), lista, busca agrupada, cobertura.

- [ ] **Step 1: Ler os padrões** — no `index.html`: (a) um botão do `#nav` (`data-nav="acervo"`) e sua section `data-view`; (b) o `showView`/registro de views (~linha 1951 e o array de botões); (c) o handler de upload single-file existente do corpus (buscar `corpus/upload` no arquivo) — reusar a montagem do payload/base64.

- [ ] **Step 2: HTML** — adicionar botão `<button data-nav="biblioteca">Biblioteca</button>` no `#nav` (depois de Acervo) e a section (antes da section `acessos`):

```html
    <section class="processos-panel" data-view="biblioteca" hidden>
      <h1>Biblioteca do Escritório</h1>
      <p class="lede">Peças, modelos e doutrina do seu escritório. Documentos de estilo ensinam a forma das minutas e nunca são citados como fonte. Seus arquivos ficam isolados por escritório e são apagáveis com certificado.</p>
      <form id="library-upload-form" class="connect-bar">
        <input id="library-files" type="file" multiple accept=".pdf,.docx,.txt,.md" />
        <select id="library-tipo">
          <option value="peca_escritorio">Peça do escritório (estilo)</option>
          <option value="modelo_peticao">Modelo de petição (estilo)</option>
          <option value="nota_interna">Tese/nota interna (estilo)</option>
          <option value="acordao_publicado">Decisão/acórdão (fonte citável)</option>
          <option value="doutrina_privada">Doutrina licenciada (fonte citável)</option>
        </select>
        <select id="library-tipo-peticao">
          <option value="">tipo de peça (opcional)</option>
          <option value="contestacao">contestação</option>
          <option value="inicial">inicial</option>
          <option value="agravo">agravo</option>
          <option value="recurso">recurso</option>
          <option value="parecer">parecer</option>
        </select>
        <input id="library-area" placeholder="área (ex.: cível)" />
        <button type="submit">Enviar para a biblioteca</button>
      </form>
      <p id="library-upload-status" class="field-note" hidden></p>
      <div id="library-coverage" class="proc-empty">Carregando…</div>
      <div id="library-list" class="proc-empty">Carregando…</div>
      <form id="library-search-form" class="connect-bar">
        <input id="library-search-q" placeholder="Buscar na biblioteca e no corpus" />
        <button type="submit">Buscar</button>
      </form>
      <div id="library-search-results" hidden>
        <h2>Fontes jurídicas para citar</h2>
        <div id="library-results-fundamento" class="proc-empty"></div>
        <h2>Modelos e peças do escritório (estilo)</h2>
        <div id="library-results-estilo" class="proc-empty"></div>
      </div>
    </section>
```

- [ ] **Step 3: JS** — junto das outras funções de view (padrão `loadAccessSummary`), adicionar (nomes exatos):

```javascript
    async function loadLibrary() {
      const box = document.querySelector("#library-list");
      const cov = document.querySelector("#library-coverage");
      try {
        const resp = await apiFetch("/api/library");
        const data = await resp.json();
        if (!resp.ok) throw new Error(apiErrorMessage(data, "Falha ao carregar a biblioteca"));
        const items = data.items || [];
        box.className = items.length ? "proc-list" : "proc-empty";
        box.innerHTML = "";
        if (!items.length) box.textContent = "Nenhum documento na biblioteca ainda. Envie peças e modelos acima.";
        items.forEach((item) => {
          const row = document.createElement("div");
          row.className = "proc-row";
          const usoLabel = item.uso === "estilo" ? "estilo (não citável)" : "fonte citável";
          row.innerHTML = `<div><div class="proc-cnj">${escHtml(item.title || item.id)}</div>` +
            `<div class="proc-meta">${escHtml(item.source_type)} · ${escHtml(usoLabel)}` +
            `${item.tipo_peticao ? " · " + escHtml(item.tipo_peticao) : ""}` +
            `${item.area ? " · " + escHtml(item.area) : ""}</div></div>` +
            `<div class="proc-meta">${escHtml(item.source_date || "")}</div>`;
          box.appendChild(row);
        });
        const byTipoPeticao = (data.coverage && data.coverage.by && data.coverage.by.tipo_peticao) || {};
        const parts = Object.entries(byTipoPeticao).map(([k, v]) => `${k}: ${v}`);
        cov.className = "proc-meta";
        cov.textContent = parts.length
          ? `Cobertura por tipo de peça — ${parts.join(" · ")}`
          : "Cobertura: nenhuma peça classificada por tipo ainda (defina o tipo de peça no envio).";
      } catch (error) {
        box.className = "proc-empty";
        box.textContent = error.message;
      }
    }

    async function uploadLibraryBatch(event) {
      event.preventDefault();
      const filesInput = document.querySelector("#library-files");
      const status = document.querySelector("#library-upload-status");
      const files = Array.from(filesInput.files || []);
      if (!files.length) return;
      const tipo = document.querySelector("#library-tipo").value;
      const tipoPeticao = document.querySelector("#library-tipo-peticao").value;
      const area = document.querySelector("#library-area").value.trim();
      status.hidden = false;
      let ok = 0;
      const errors = [];
      for (let i = 0; i < files.length; i += 1) {           // sequencial: endpoint é rate-limited
        const file = files[i];
        status.textContent = `Enviando ${i + 1}/${files.length}: ${file.name}…`;
        const payload = {
          filename: file.name,
          content_base64: await fileToBase64(file),
          title: file.name.replace(/\.[^.]+$/, ""),
          source_type: tipo,
          tipo_peticao: tipoPeticao,
          area,
          provenance_kind: "acervo_do_escritorio",
          source_publisher: "acervo do escritório",
          source_date: new Date().toISOString().slice(0, 10),
        };
        let attempt = 0;
        while (attempt < 3) {
          const resp = await apiFetch("/api/corpus/upload", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          if (resp.status === 429) {                         // backoff: prefixo caro (12/min)
            attempt += 1;
            status.textContent = `Limite de envio atingido — aguardando para continuar (${file.name})…`;
            await new Promise((r) => setTimeout(r, 6000 * attempt));
            continue;
          }
          if (resp.ok) ok += 1;
          else {
            const data = await resp.json().catch(() => ({}));
            errors.push(`${file.name}: ${apiErrorMessage(data, "falha no envio")}`);
          }
          break;
        }
      }
      status.textContent = `Concluído: ${ok}/${files.length} enviados.` +
        (errors.length ? ` Erros: ${errors.join(" · ")}` : "");
      filesInput.value = "";
      loadLibrary();
    }

    function fileToBase64(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
    }

    async function searchLibrary(event) {
      event.preventDefault();
      const q = document.querySelector("#library-search-q").value.trim();
      if (!q) return;
      const wrap = document.querySelector("#library-search-results");
      const fundEl = document.querySelector("#library-results-fundamento");
      const estEl = document.querySelector("#library-results-estilo");
      const resp = await apiFetch(`/api/corpus/search?q=${encodeURIComponent(q)}&include_estilo=1&top_k=12`);
      const data = await resp.json();
      const results = (data.results || []);
      const render = (el, rows, vazio) => {
        el.innerHTML = "";
        el.className = rows.length ? "proc-list" : "proc-empty";
        if (!rows.length) { el.textContent = vazio; return; }
        rows.forEach((r) => {
          const row = document.createElement("div");
          row.className = "proc-row";
          row.innerHTML = `<div><div class="proc-meta">${escHtml(r.fonte || r.tipo || "")}</div>` +
            `<div>${escHtml(String(r.texto || "").slice(0, 220))}…</div></div>`;
          el.appendChild(row);
        });
      };
      render(fundEl, results.filter((r) => r.uso !== "estilo"), "Nenhuma fonte citável encontrada.");
      render(estEl, results.filter((r) => r.uso === "estilo"), "Nenhum modelo/peça do escritório encontrado.");
      wrap.hidden = false;
    }
```

Registrar: `document.querySelector("#library-upload-form").addEventListener("submit", uploadLibraryBatch);` idem `#library-search-form` → `searchLibrary`; e no `showView`, carregar a view (seguir o padrão da view `acessos`: onde `loadAccessSummary()` é chamada ao entrar, chamar `loadLibrary()` para `biblioteca`).

- [ ] **Step 4: Verificar** — (a) `python3` extrai o script inline e roda `node --check` (padrão usado nas mudanças anteriores da SPA); (b) `uv run pytest tests/unit/web -q` (os pins de conteúdo/CSP: hash é runtime, nada a atualizar; o pin de honestidade não pode disparar — a copy da section usa a fórmula aprovada); (c) subir `uv run juris web --port 8010`, abrir a aba Biblioteca no browser, enviar 2 arquivos (txt + docx), ver lista/cobertura/busca agrupada, screenshot.

- [ ] **Step 5:** Gates + commit:

```bash
uv run ruff check src/juris tests && uv run pytest -q
git add src/juris/web/static/index.html
git commit -m "feat(web): aba Biblioteca — upload em lote com backoff, lista, busca agrupada e cobertura (L5)"
```

---

### Task 10: L6 — Erasure no nível certo + fechamento

**Files:**
- Test: `tests/unit/web/test_library_api.py` (estender)
- Modify: `docs/engineering_sprints.md` (registrar a entrega)

- [ ] **Step 1: Teste de erasure** — acrescentar (localizar o helper de erase usado em testes existentes: `grep -rn "erase_tenant_data\|erase-data" tests/unit | head` e usar a MESMA função/CLI):

```python
def test_erasure_remove_biblioteca_no_nivel_certo(tenant_env, tmp_path) -> None:
    _upload_peca(tenant_env)
    # (a) apaga o tenant pela via oficial (mesma função que o CLI erase-data usa)
    from juris.web.trial_access import ...  # conferir: função de erase usada nos testes existentes

    ...  # executar o erase do tenant "escritorio-a" com confirmação
    # (b) chave antiga rejeitada — tenant apagado não autentica
    resp = tenant_env.get("/api/library", headers={"X-API-Key": "key-a"})
    assert resp.status_code == 401
    # (c) repertory.db sem chunks do tenant
    import sqlite3
    conn = sqlite3.connect(<repertory path do harness>)
    n = conn.execute("SELECT count(*) FROM chunks WHERE tenant_id = 'escritorio-a'").fetchone()[0]
    assert n == 0
    # (d) certificado registrado
    assert "escritorio-a" in (<compliance-erasure.jsonl do harness>).read_text()
```

**Este passo exige conferir o harness real de erasure** (testes de `tenant erase-data` já existem — `grep -rln "erase" tests/unit | head`): copiar o setup de lá para preencher os `<...>` acima com os caminhos exatos do harness. Se o erase existente já tiver teste cobrindo (b)/(d), o teste novo cobre apenas (c) com uma fonte de biblioteca ingerida — sem duplicar.

- [ ] **Step 2:** Run: `uv run pytest tests/unit/web/test_library_api.py -q` — Expected: PASS (se falhar em (c), é bug real de erasure da biblioteca — investigar `erase-data` antes de prosseguir; o spec exige esse nível).

- [ ] **Step 3: Registrar no doc de sprints** — em `docs/engineering_sprints.md`, seção "Estado atual", acrescentar uma linha: "Biblioteca do Escritório (Fase 1, 2026-07-06): tier-3 com eixo uso fundamento/estilo, guarda determinística no retrieval+verifier, upload em lote (.pdf/.docx/.txt/.md), exemplar de estilo do próprio escritório no drafter e aba Biblioteca no console. Spec em docs/superpowers/specs/2026-07-06-biblioteca-escritorio-design.md."

- [ ] **Step 4: Suíte final + gates:**

```bash
uv run pytest -q                      # esperado: baseline 1891 + ~25 novos, tudo verde
uv run ruff check src/juris tests scripts/scan_secrets.py
uv run mypy src/juris
```

- [ ] **Step 5:** Commit + push:

```bash
git add tests/unit/web/test_library_api.py docs/engineering_sprints.md
git commit -m "test(library): erasure LGPD cobre a biblioteca no nível certo (L6) + registro no doc de sprints"
git push origin main
```

---

## Self-review (2026-07-06)

- **Cobertura do spec:** L1→T1, L1b→T2, L3→T3 (DOCX) + T9 (lote/backoff), L2→T4+T5+T6 (+pino em T7), L4→T7, L5→T8+T9, L6→T10. Incorporações da revisão externa: nº1 (uso legado por tipo) → T4 SQL COALESCE/CASE + teste de migração; nº2 → T2; nº3 → T1/T2; nº4 → T2/T8; nº5 → T8/T9 usam `/api/corpus/search`; nº6 → T4 (WHERE, não pós-top_k); nº7 → T6; nº8 → nada de novo sai cru (T7 usa o caminho normal do drafter); nº9 → T10; nº10 → T9 (sequencial + 429).
- **Consistência de tipos:** `find_style_exemplar(tipo_peticao, area_direito, tenant_id)` igual em T6 (produz) e T7 (consome); `SearchResult.source_type/uso` (T4) → `RetrievalResult.tipo/uso` (T6) → payload de busca (T8) → `r.uso` no JS (T9); `include_estilo`/`tenant_only` com os mesmos nomes em stores/hybrid/service.
- **Passos com leitura obrigatória** (não placeholders — dizem exatamente o que ler e extrair): T5 Step 1 (payload Qdrant), T7 Step 1 (kwarg do construtor), T9 Step 1 (padrões da SPA), T10 Step 1 (harness de erasure).
- **Riscos anotados:** fakes de repertory nos testes existentes (T7 usa `getattr` defensivo); testes existentes de store/find_template podem assumir estilo no default (T4/T6 Step 4 instruem o ajuste com justificativa); `DocumentChunk` mutável vs frozen (T4 Step 3f verifica).
