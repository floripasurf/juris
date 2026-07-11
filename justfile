# juris / CAUSIA — recipes. Comandos pesados rodam com `nice -n 10` para não
# disputar CPU com produção neste Mac Mini. Uso: `just <recipe>`.
heavy := "nice -n 10"

# lista as recipes
default:
    @just --list

# suíte unitária
test:
    {{heavy}} uv run pytest tests/unit -q

# lint (escopo do CI)
lint:
    {{heavy}} uv run ruff check src/juris tests scripts/scan_secrets.py

# type check
types:
    {{heavy}} uv run mypy src/juris

# gate completo de CI (lint + types + testes)
check: lint types test

# console web local para revisão (porta configurável)
web port="8011":
    uv run juris web --port {{port}}
