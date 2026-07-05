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
	uv run juris web --port 8000

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

# Mypy-clean + fully-tracked packages (no engine-local files ⇒ local == CI) — a
# hard gate (must not regress). Grow this list as tracks are cleaned, until it
# covers src/juris and the `|| true` below can be dropped.
MYPY_CLEAN := src/juris/alerts src/juris/api src/juris/busca \
	src/juris/demo src/juris/escavacao src/juris/mni \
	src/juris/signing src/juris/web

# CI gate (mirrors .github/workflows/ci.yml): ruff + tests + mypy-on-clean-packages
# are hard gates; the full mypy run is informational until the debt is zeroed.
gate:
	uv run ruff check src/juris tests
	uv run pytest tests/unit -q
	uv run mypy $(MYPY_CLEAN)
	uv run mypy src/juris || true

# === Cleanup ===
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .mypy_cache .ruff_cache .pytest_cache htmlcov dist build
