.PHONY: setup dev test lint types check fmt clean docker-up docker-down migrate

# === Setup ===
setup:
	uv sync
	cp -n .env.example .env || true

# === Docker ===
docker-up:
	docker compose -f docker/docker-compose.yml up -d

docker-down:
	docker compose -f docker/docker-compose.yml down

# === Database ===
migrate:
	uv run alembic upgrade head

migration:
	uv run alembic revision --autogenerate -m "$(msg)"

# === Development ===
dev:
	uv run uvicorn juris.api.orchestrator:app --reload --port 8000

# === Quality ===
test:
	uv run pytest

test-cov:
	uv run pytest --cov=juris --cov-report=term-missing

lint:
	uv run ruff check .

types:
	uv run mypy src/juris

fmt:
	uv run ruff format .
	uv run ruff check --fix .

check: lint types test

# === Cleanup ===
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .mypy_cache .ruff_cache .pytest_cache htmlcov dist build
