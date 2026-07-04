from __future__ import annotations

import tomllib
from pathlib import Path

_PYPROJECT = tomllib.loads(
    (Path(__file__).resolve().parents[3] / "pyproject.toml").read_text(encoding="utf-8")
)


def test_agent_dep_group_excludes_heavy_ml() -> None:
    agent_deps = " ".join(_PYPROJECT["project"]["optional-dependencies"]["agent"]).lower()
    for heavy in ("sentence-transformers", "torch", "transformers", "qdrant", "sqlalchemy", "alembic"):
        assert heavy not in agent_deps, f"grupo agent não pode incluir dep pesada: {heavy}"


def test_agent_dep_group_has_token_and_relay_deps() -> None:
    agent_deps = " ".join(_PYPROJECT["project"]["optional-dependencies"]["agent"]).lower()
    for needed in ("zeep", "requests-pkcs12", "websockets", "python-pkcs11", "pyhanko", "cryptography"):
        assert needed in agent_deps, f"grupo agent precisa de: {needed}"
