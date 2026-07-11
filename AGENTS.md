# juris / CAUSIA — orientação para agentes

**Orientar primeiro:** `graphify explain` / `graphify query <termo>` (grafo em
`graphify-out/`) antes de grepar/ler muitos arquivos. Fluxos em `docs/`.

## O que é
IA jurídica brasileira (advocacia). Produto no ar: **causia.com.br**, roda neste
Mac Mini (launchd `com.causia.*`, porta 8100). Arquitetura split-trust: nuvem +
agente local que guarda o token ICP-Brasil A3 e assina PAdES.

## Stack (pinado)
Python 3.12, `uv`, FastAPI. Persistência do piloto = **SQLite + FTS5** (ADR-0020;
Postgres/SQLAlchemy/Qdrant são superfícies diferidas, NÃO o caminho ativo).
Embeddings BGE-M3 locais; reranker BGE local.

## Rodar / testar (via just, já com nice)
`just check` (lint+types+test) · `just test` · `just web`. Gates de CI: ruff
(`src/juris tests scripts/scan_secrets.py`) + `mypy src/juris` + `pytest tests/unit`
+ pip-audit. Rodar comandos pesados fora do just com `heavy <cmd>`.

## Regras invioláveis
- Isolamento por tenant em toda query. Determinismo em prazo/citação (sem LLM
  decidindo). Não inventar jurisprudência. Local LLM p/ PII; nuvem só de-identificado.
- Copy honesta: nunca "criptografado em repouso" nem "nunca sai do seu computador".

## Gotchas
- Criar trial em dev escreve `config/tenants.json` no cwd → quebra testes web (quarentenar).
- CSP faz hash dos scripts inline no boot → reiniciar o server após editar `index.html`.
- Busca semântica: `LocalFTSStore` agora tem busca densa real (embeddings persistidos
  como float32); rodar `juris repertory backfill-embeddings` no corpus existente.
- Fonte de verdade é este repo no Mini; a cópia em ~/Desktop/juris do Air pode divergir.
