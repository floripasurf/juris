# Project: juris — Brazilian Legal AI for law firms

## Mission

Build an AI system that, for a Brazilian law firm using the lawyer's own ICP-Brasil credentials, can:

1. **Read** every movement in the firm's active processes nightly via MNI (SOAP webservice of the CNJ Modelo Nacional de Interoperabilidade)
2. **Analyze** those movements: classify, score relevance, identify deadlines, recommend actions
3. **Draft** petitions with retrieval-grounded citations from a three-tier corpus (public jurisprudencia, tenant-uploaded doutrina, firm petition history)
4. **File** PAdES-signed petitions through a split-trust architecture where the lawyer's certificate stays on their machine

The full architecture is in `docs/mni_integration_reference.md` — read it before making major design decisions.

## Owner context

- Solo developer building this for a law firm operating in Brazil
- Has Brazilian OAB credentials and an ICP-Brasil A3 token (e-CPF) for testing real MNI calls
- Will start with the firm's own active caseload, then expand to multi-tenant SaaS
- Comfortable with Python, multi-agent systems, MCP, and Claude Code

## Tech stack (pinned — do not change without discussion)

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.12+ | Type hints required everywhere |
| Package manager | `uv` | Use `uv add`, `uv run`, `uv sync` |
| SOAP client | `zeep` | For MNI WSDL clients |
| Cert HTTP | `requests-pkcs12` | A3 token via PKCS#12 |
| PDF signing | `pyhanko` | PAdES-B and PAdES-T |
| XML signing | `signxml` | For tribunals requiring WS-Security |
| API framework | `FastAPI` | Both the orchestrator and local agent |
| Async | `asyncio` + `httpx` for non-SOAP calls | |
| Database | PostgreSQL 16 via `psycopg` (v3) + `asyncpg` for async paths | |
| Migrations | `alembic` | |
| ORM | `SQLAlchemy 2.x` (async) | |
| Vector DB | `qdrant` self-hosted via Docker | |
| Sparse search | PostgreSQL `tsvector` + GIN index | Per-tenant via tenant_id column |
| Embeddings | `sentence-transformers` with BGE-M3 | Run locally; reserve cloud for non-PII |
| Reranker | `BGE-reranker-v2-m3` locally; Cohere as optional | |
| LLM (cloud) | `anthropic` Python SDK with Claude | For non-PII tasks |
| LLM (local) | Ollama HTTP API; models: Qwen3, Llama 3.3 | For PII-bearing prompts |
| Queue | `arq` (async Redis queue) | Lightweight, native asyncio |
| Object storage | `LocalFileStorage` for v1; S3-compatible for multi-tenant | |
| Tests | `pytest` + `pytest-asyncio` + `pytest-cov` | |
| Lint | `ruff` (rules: E, F, I, N, B, UP, S, A, C4, RET, SIM) | |
| Types | `mypy --strict` on the core package | |
| Container | Docker with multi-stage builds | |

## Project structure

```
juris/
├── pyproject.toml
├── CLAUDE.md
├── docs/
│   ├── mni_integration_reference.md
│   └── architecture-decisions/
├── docker/
│   └── docker-compose.yml          # qdrant, postgres, redis
├── src/
│   └── juris/
│       ├── config.py                # pydantic-settings
│       ├── core/                    # shared kernel
│       │   ├── types.py             # NumeroCNJ, TenantId
│       │   ├── llm_router.py        # PII-aware LLM routing
│       │   ├── storage.py           # abstract StorageBackend
│       │   └── observability.py     # structlog + traces
│       ├── mni/                     # MNI SOAP integration
│       │   ├── client.py            # cached zeep clients
│       │   ├── auth.py              # cert + password strategies
│       │   ├── tribunais.py         # WSDL registry
│       │   ├── tpu.py               # CNJ TPU code mapper
│       │   ├── retry.py             # backoff + circuit breaker
│       │   ├── operations/
│       │   └── parsers/
│       ├── prazo/                   # deterministic deadline engine
│       ├── repertory/               # three-tier corpus + retrieval
│       ├── agents/                  # AI agents (analyzer, reviewer, researcher, drafter)
│       ├── signing/                 # PAdES + WS-Security
│       ├── persistence/             # SQLAlchemy models + repositories
│       ├── api/                     # FastAPI (orchestrator + local agent)
│       ├── llm/                     # LLM abstraction (Claude + Ollama)
│       ├── prompts/                 # versioned prompt templates
│       ├── jobs/                    # background jobs (overnight reads)
│       ├── alerts/                  # deadline alert scheduling
│       └── cli/                     # typer CLI entry point
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── scripts/
└── data/                            # TPU JSONs, calendar YAMLs, prazo rules
```

## Coding standards (enforced by CI)

- **Type hints required** on every function signature and class attribute.
- **Docstrings** on all public functions and classes (Google style).
- **No bare `except`** — always specify exception types.
- **No `print()` for logging** — use `structlog`.
- **`async def` for I/O** — sync only for CPU-bound or trivial helpers.
- **`@dataclass(frozen=True, slots=True)`** for value objects; SQLAlchemy models for persistence.
- **`pydantic` for boundary validation** — at API ingress and external service responses.
- **Tests live next to features**; coverage target 80% for the core package.
- **No business logic in API handlers** — they orchestrate, services do the work.
- **Secrets via environment variables only**; never commit `.env`.
- **Keep modules small** — if a module exceeds ~400 lines, split it.

## Naming conventions

- Modules and packages: `snake_case`
- Classes: `PascalCase`
- Functions, variables: `snake_case`
- Constants: `SCREAMING_SNAKE`
- Domain terms in Portuguese where they have specific legal meaning (`processo`, `peticao`, `prazo`, `movimento`, `consulta`, `peticionamento`, `intimacao`, `comarca`, `vara`, `acordao`, `ementa`, `voto`, `dispositivo`). English for engineering terms (`client`, `repository`, `service`, `handler`).

## Working principles

1. **Start with the lawyer's own caseload**, never with synthetic data.
2. **Test against the real MNI WSDL** for at least one tribunal early.
3. **Determinism over cleverness for legal-critical paths**. Prazo engine = rules-based. Citation verification = deterministic.
4. **Tenant isolation is non-negotiable**. Every query carries `tenant_id`.
5. **Audit everything**. Every AI decision, retrieval, draft, signing event, filing — write to the audit log with hashes.
6. **Local LLM for PII-bearing prompts; cloud LLM only for de-identified or public-corpus tasks.**
7. **Do not invent jurisprudence references.**

## What NOT to build now (deferred)

- Adversario intelligence (Phase 3)
- Tribunal/judge intelligence (Phase 3)
- WhatsApp client (Phase 2)
- Document understanding for incoming evidence (Phase 2)
- Honorarios/economics layer (Phase 3)
- Research mode as separate UI (Phase 2)
- Multi-tenant SaaS infrastructure (Phase 2)

If a feature isn't in the current sprint scope, do not start it.

## Common commands

```bash
# Setup
uv sync
docker compose -f docker/docker-compose.yml up -d

# Develop
uv run pytest
uv run pytest --cov=juris
uv run ruff check .
uv run ruff format .
uv run mypy src/juris

# CLI
uv run juris consulta <numero_cnj>
uv run juris tribunais
uv run juris draft <numero_cnj> contestacao
uv run juris draft <numero_cnj> inicial --cloud --thesis "..."
uv run juris search --tema "improbidade administrativa" --courts tst
uv run juris search --cnj "0001234-56.2024.8.26.0001"   # auto-detects court
uv run juris search doctor                               # adapter health checks
# Portal automation status: see docs/usage/search.md (most portals WAF/captcha-gated)

# Database
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "msg"

# Or use Makefile
make setup
make docker-up
make test
make check
```

## Commit hygiene

- Commit messages: `type(scope): subject` (e.g., `feat(mni): add consultarProcesso`)
- Types: feat, fix, refactor, test, docs, chore, perf
- One logical change per commit; no mega-commits
