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
        "('torch','transformers','sentence_transformers','qdrant','sqlalchemy',"
        "'juris.web.app','fitz','pymupdf','botocore','anthropic','PIL'))]; "
        "print('HEAVY:'+','.join(heavy)); "
        "assert not heavy, heavy"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)  # noqa: S603
    assert r.returncode == 0, r.stdout + r.stderr
    assert "HEAVY:" in r.stdout and r.stdout.strip().endswith("HEAVY:")


def test_web_auth_import_does_not_pull_in_web_app() -> None:
    # o agente só precisa de juris.web.auth (validate_tenant_id) — o __init__ lazy do
    # pacote juris.web não pode puxar juris.web.app (e sua árvore pesada: anthropic,
    # botocore, pymupdf/fitz, PIL) só por causa desse import de submódulo.
    code = (
        "import sys; "
        "from juris.web.auth import validate_tenant_id; "
        "assert 'juris.web.app' not in sys.modules, sorted(m for m in sys.modules if m.startswith('juris.web'))"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)  # noqa: S603
    assert r.returncode == 0, r.stdout + r.stderr
