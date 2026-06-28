# juris — IA jurídica para escritórios brasileiros

Lê os andamentos dos processos via **MNI** (com o e-CPF A3 do advogado), analisa e
calcula prazos, **busca jurisprudência** e seleciona a **linha argumentativa**,
**minuta** petições com citações verificadas, e **peticiona** com assinatura
PAdES — tudo com **trilha de auditoria encadeada** e **de-identificação de PII**.

> Python 3.12 · `uv` · FastAPI · pytest/ruff/mypy. Foco atual: piloto Fase 1
> (escritório único, co-localizado no Mac Mini).

## Quick start

```bash
uv sync
docker compose -f docker/docker-compose.yml up -d   # qdrant, postgres, redis
cp .env.example .env
uv run pytest
uv run juris tribunais
```

Sessão de piloto ao vivo: **`docs/pilot/onboarding.md`** (pré-requisitos + a
sequência de comandos no Mac Mini). Rode `uv run juris pilot preflight --live`
antes — um comando verifica token A3, corpus, embeddings, Ollama e o modelo NER.

## Subsistemas

| Área | O quê | Ref |
|---|---|---|
| **MNI** (`mni/`) | Leitura mTLS por CNJ + token A3; serviços atrás de interfaces | ADR-0015 |
| **Corpus** (`repertory/`) | Espinha (súmulas/temas) + escavação (inteiro teor = o fosso); busca híbrida + escore composto | ADR-0017 |
| **Filtro** (`busca/`, `agents/estrategia.py`) | Source Mesh redundante → ranking determinístico → **linha argumentativa** (auditor 9 módulos) | ADR-0017 |
| **Agentes** (`agents/`) | analyzer, researcher, drafter, reviewer (verificação de citações) | — |
| **Prazo** (`prazo/`) | Motor de prazos determinístico (dias úteis BR) | — |
| **Signing** (`signing/`) | PAdES via token; peticionamento MNI | ADR-0015 |
| **De-id** (`core/deid*`, `core/ner.py`) | CPF/CNPJ/CNJ/OAB (regex) + nomes (LeNER-Br) antes de qualquer LLM externo | ADR-0016 |
| **Escavação** (`escavacao/`) | Fila priorizada dos casos-líderes → coleta de inteiro teor | — |
| **Web** (`web/`) | Console do operador: conectar, processos, prazos, minuta, estratégia, review, auditoria | — |
| **Multi-tenant** (`web/auth.py`) | Fundação: API-key por escritório + storage por-conta | ADR-0019 |

## Modos de IA (PII — ADR-0016)

| Modo | Quando | Privacidade |
|---|---|---|
| **Local** (Ollama) | default; PII fica na máquina | 🟢 dado não sai |
| **Cloud de-id** (API Claude/GPT) | `--cloud`; PII de-identificada antes de sair (CPF/CNPJ/CNJ/OAB + **nomes via LeNER-Br**), gate **falha fechado** sem NER | 🟢 não-treina + DPA |
| **Browser session** (assinatura) | extensão dirige Claude.ai/ChatGPT do advogado; de-id ligado; desligar treino no onboarding (ADR-0018) | 🟡 ToS/treino |

## Fluxos principais

```bash
# 1. Conectar o token → importar acervo + calcular prazos (1ª vez tudo, depois deltas)
uv run juris connect --cpf <CPF> --file acervo.txt

# 2. Ler → analisar → minutar (com a linha estratégica selecionada)
uv run juris demo <CNJ> contestacao --source mni

# 3. Verificar a integridade da auditoria
uv run juris audit verify juris-out/<CNJ>/audit.jsonl

# Outros
uv run juris repertory search "<tema>"      # busca corpus (com breakdown do score)
uv run juris repertory consolidate          # consolida banco legado no canônico
uv run juris escavacao run --seed espinha.json --out escavacao-out
uv run juris file <CNJ> <tipo> --cpf <CPF>  # assina (PAdES) + peticiona
```

Console web: `uv run uvicorn juris.web.app:app` → conectar / Acervo / Agenda /
Novo caso, com painéis de estratégia, review e auditoria.

## Matriz de segurança

- **PII → de-identificada** antes de qualquer LLM externo; gate falha fechado.
- **Auditoria encadeada** (hash) de cada decisão de IA / leitura / assinatura;
  `juris audit verify` valida a cadeia (e o console mostra na tela).
- **Token A3 nunca exportado** — ops com chave rodam na máquina do advogado.
- **Não inventar jurisprudência**: citações verificadas pelo `MarkerCitationVerifier`;
  a estratégia penaliza citação alucinada (grounding).
- **Veto deontológico** (CED/EOAB): flagra "êxito garantido"/inevitabilidade.
- **Multi-tenant**: API-key (plaintext dev / sha256 prod), storage por-conta.

## Público vs engine local

O motor proprietário de NLP (`repertory/retrieval/`, `repertory/chunking.py`,
`agents/` de engine, `llm/`) é **gitignored** — desenvolvido localmente, fora do
GitHub. O checkout público **degrada graciosamente**:

- `repertory/retrieval/service.py` faz **import opcional** do ranker composto
  (`ranking.py`): com o engine, re-ranqueia por relevância+autoridade+vigência e
  expõe o breakdown; **sem o engine, cai para ordem por relevância** (sem score
  composto). Não quebra.
- Backends de LLM (`llm/`) e o `BrowserSessionLLM` são locais; o protocolo +
  transporte do bridge (`api/`) são públicos.

## Limites (hoje)

- **Só TST** é totalmente automatizável; demais portais têm WAF/captcha (o juris
  **não burla** — usa fontes públicas/DataJud).
- **Escavação**: DataJud entrega a trilha de movimentos (`parcial=True`), não o
  acórdão integral (fonte gated); a fila/executor estão prontos.
- **Browser session**: o lado Python está pronto e testado; a extensão Chrome
  (DOM) precisa de Chrome/Node (`docs/browser-extension/`).
- **Multi-tenant**: fundação ativada (auth + scoping de leitura/demo/audit); o
  caminho de escrita do connect + agente Remote são Fase 2.

## Comandos de desenvolvimento

```bash
uv run pytest                 # testes
uv run ruff check src/juris   # lint
uv run mypy src/juris         # tipos (core estrito)
```

## Decisões de arquitetura

`docs/architecture-decisions/` — ADR-0015 (agente local), 0016 (PII/IA de
preferência), 0017 (Source Mesh + filtro), 0018 (sessão de navegador), 0019
(multi-tenant). Referência completa do MNI: `docs/mni_integration_reference.md`.
