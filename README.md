# juris — Brazilian Legal AI for law firms

AI system that reads court movements via MNI, analyzes deadlines, drafts petitions with verified citations, and files via ICP-Brasil signed credentials.

## Quick Start

```bash
# Install dependencies
uv sync

# Start infrastructure
docker compose -f docker/docker-compose.yml up -d

# Copy and configure environment
cp .env.example .env

# Run database migrations
uv run alembic upgrade head

# Run tests
uv run pytest

# List available tribunals
uv run juris tribunais
```

## Architecture

See `docs/mni_integration_reference.md` for the full architecture specification.
