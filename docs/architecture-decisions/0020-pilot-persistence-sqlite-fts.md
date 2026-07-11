# ADR-0020: Pilot Persistence Uses SQLite + FTS5

## Status

Accepted for the production pilot.

## Context

Older project scaffolding and `CLAUDE.md` described the intended scale-out stack:
PostgreSQL, SQLAlchemy/Alembic, Qdrant and PostgreSQL `tsvector`. The deployed
pilot evolved differently. The active Mac Mini runtime stores tenant operational
state in tenant-scoped SQLite files and stores the repertory in SQLite FTS5
(`LocalFTSStore`).

Leaving the old stack documented as the primary runtime makes new contributors
start Docker/Postgres/Qdrant and assume those paths are authoritative, while the
lawyer-facing product is actually exercising the local SQLite path.

## Decision

For the pilot:

- tenant case state lives in local SQLite under `JURIS_HOME`/tenant storage;
- corpus search uses `repertory.db` plus SQLite FTS5;
- dense embeddings are required in production for semantic retrieval, but the
  local store remains the source queried by the pilot;
- `src/juris/persistence/database.py`, SQLAlchemy models, Alembic migrations and
  `QdrantVectorStore` are compatibility/future-scale surfaces, not the default
  runtime path.

## Consequences

- Operational docs and preflight checks must describe SQLite/FTS5 as the real
  current path.
- Code changes that affect lawyer-facing persistence should target the local
  SQLite services first.
- Postgres/Qdrant migration requires a new implementation plan and parity tests
  before the docs can call it production.
- The public corpus depth remains a separate product risk: FTS5 over shallow
  seed data is not equivalent to full-text acórdão retrieval.
