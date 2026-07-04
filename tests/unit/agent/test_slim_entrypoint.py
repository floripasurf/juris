from __future__ import annotations

import subprocess
import sys
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
    for needed in ("zeep", "requests-pkcs12", "websockets", "python-pkcs11", "pyhanko", "cryptography", "certifi"):
        assert needed in agent_deps, f"grupo agent precisa de: {needed}"


def test_slim_entrypoint_imports_no_heavy_deps() -> None:
    # importar o entrypoint do agente NÃO pode carregar torch/transformers/fastapi-web
    code = (
        "import sys; "
        "import juris.agent.main; "
        "heavy=[m for m in sys.modules if any(h in m for h in "
        "('torch','transformers','sentence_transformers','qdrant','sqlalchemy'))]; "
        "print('HEAVY:'+','.join(heavy)); "
        "assert not heavy, heavy"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)  # noqa: S603
    assert r.returncode == 0, r.stdout + r.stderr
    assert "HEAVY:" in r.stdout and r.stdout.strip().endswith("HEAVY:")
