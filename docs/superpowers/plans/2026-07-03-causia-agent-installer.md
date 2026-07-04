# Instalador do Agente Causia (macOS + Windows) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Empacotar o agente local do Causia (guardião do token A3 + ponte PKCS#11 + `connect-relay`) num instalador de um clique para macOS e Windows, que instala sem repo/`uv sync`, sobe como item de login, se auto-atualiza com segurança e minimiza atrito de antivírus/firewall — para que um advogado não-técnico o instale sozinho.

**Architecture:** O agente já não importa deps pesadas de ML (verificado). Extraímos um entrypoint slim (`juris-agent`) e um grupo de deps `agent` (sem torch/transformers/fastapi-web). Empacotamos com **PyInstaller** (onedir, sem UPX, com metadados de versão) em cada plataforma via **GitHub Actions** (runner macOS + runner Windows). O agente instalado roda `agent serve` (loopback 8765) e o pareamento/credenciais é 100% **browser-first** (o console em causia.com.br dirige `/pair-relay` + `/credentials` no loopback — código que o Codex já entregou). Auto-update segue o padrão **manifesto assinado Ed25519** aprendido no conector do lida (Smart Milk): o agente baixa um `latest.json` assinado, valida sha256 + assinatura, e troca o binário atomicamente. Distribuição via GitHub Releases + um endpoint no app que serve o manifesto assinado.

**Tech Stack:** Python 3.12, PyInstaller, `cryptography` (Ed25519, já é dep transitiva), GitHub Actions (macos-latest + windows-latest runners), launchd (macOS LaunchAgent), Windows Registry Run key / Task Scheduler, `httpx` (já é dep).

## Global Constraints

- **Sem repo, sem `uv sync` no cliente**: o instalador é autocontido (PyInstaller bundla o Python + só as deps do agente).
- **O agente nunca expõe porta de entrada**: liga só em `127.0.0.1` e **disca para fora** (`connect-relay`) — logo **não precisa de regra de firewall de entrada** (dizer isso ao usuário; é uma vantagem real). Segredos (CPF/senha PJe/PIN) ficam só na máquina do advogado, nunca no servidor (ADR-0015).
- **Sem assinatura de código nesta fase** (decisão do owner): distribuir não-assinado com instruções claras de "abrir mesmo assim" (macOS: clique-direito → Abrir; Windows: Mais informações → Executar assim mesmo). Metadados de versão legítimos reduzem falso-positivo de AV. Deixar o caminho de assinatura documentado (macOS Developer ID; Windows Azure Trusted Signing) como follow-up.
- **Sem UPX** no PyInstaller (packing dispara heurística de AV).
- **Auto-update com verificação de assinatura Ed25519** — um servidor comprometido não pode empurrar binário malicioso (a chave privada de assinatura fica fora do servidor).
- **Reusar o browser-first do Codex** para pareamento/credenciais — não construir GUI nativa.
- **Versão do agente no esquema `AAAA.M.D.seq`** (espelha o `version_info.txt` do lida).
- Toda dependência nova entra no grupo opcional `agent` do `pyproject.toml`, não no `dependencies` base.

---

## File Structure

**Novos arquivos (código do agente slim + update):**
- `src/juris/agent/__init__.py` — pacote do agente empacotável.
- `src/juris/agent/main.py` — entrypoint slim `juris-agent` (importa só o caminho do agente).
- `src/juris/agent/update.py` — auto-update: verificação de manifesto assinado Ed25519 + download/swap.
- `tests/unit/agent/test_slim_entrypoint.py` — pin: entrypoint slim não carrega deps pesadas.
- `tests/unit/agent/test_update.py` — verificação de assinatura/sha256 do auto-update.

**Empacotamento:**
- `packaging/agent/causia-agent.spec` — PyInstaller spec (compartilhado; datas/hiddenimports).
- `packaging/agent/version_info.txt` — metadados VSVersionInfo (Windows, reduz falso-positivo de AV).
- `packaging/agent/macos/com.causia.agent.plist` — template LaunchAgent (auto-start + KeepAlive).
- `packaging/agent/macos/build_dmg.sh` — .app → .dmg (não assinado).
- `packaging/agent/windows/install.bat` — instalador (copia p/ %LOCALAPPDATA%, cria Run key, primeira execução).
- `packaging/agent/windows/uninstall.bat` — remove Run key + arquivos.
- `packaging/agent/LEIA-ME.txt` — instruções ao advogado (abrir-mesmo-assim + pareamento).

**Distribuição/servidor:**
- `.github/workflows/agent-release.yml` — build macOS + Windows, assina manifesto, publica no Release.
- `scripts/sign_agent_manifest.py` — gera `latest.json` assinado (roda no CI com a chave secreta).
- `src/juris/web/agent_dist.py` — endpoint `/api/agent/latest` que serve o manifesto assinado + links.
- `tests/unit/web/test_agent_dist.py` — o endpoint serve o manifesto e é público.

**Frontend (reuso do browser-first):**
- `src/juris/web/static/index.html` — adicionar "Baixar o agente" (link p/ o instalador do SO do usuário) no fluxo Acervo → Conectar agente.

---

## Task 1: Grupo de deps `agent` (slim) no pyproject

**Files:**
- Modify: `pyproject.toml:67` (bloco `[project.optional-dependencies]`)
- Test: `tests/unit/agent/test_slim_entrypoint.py`

**Interfaces:**
- Produces: grupo opcional `agent` com apenas as deps de runtime do agente (`zeep`, `requests-pkcs12`, `websockets`, `httpx`, `pyhanko`, `python-pkcs11`, `signxml`, `typer`, `structlog`, `cryptography`, `certifi`) — SEM `sentence-transformers`, `torch`, `qdrant`, `alembic`, `sqlalchemy` do caminho web/corpus.

- [ ] **Step 1: Ver as deps atuais e classificar**

Run: `grep -n "^dependencies = \[" -A 40 pyproject.toml`
Expected: a lista base com ~30 deps. Identifique as que o agente usa (import em `src/juris/api/local_agent.py`, `src/juris/api/relay.py`, `src/juris/mni/remote.py`, `src/juris/signing/remote.py`, `src/juris/cli/commands/agent.py`).

- [ ] **Step 2: Escrever o teste que fixa o grupo `agent`**

```python
# tests/unit/agent/test_slim_entrypoint.py
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
```

- [ ] **Step 3: Rodar o teste (deve falhar — grupo não existe)**

Run: `uv run pytest tests/unit/agent/test_slim_entrypoint.py -v`
Expected: FAIL com `KeyError: 'agent'`.

- [ ] **Step 4: Adicionar o grupo `agent` ao pyproject**

Em `pyproject.toml`, dentro de `[project.optional-dependencies]`, adicionar (copiando os pins exatos das mesmas libs já em `dependencies`):

```toml
agent = [
    "zeep>=4.2.1",
    "requests-pkcs12>=1.16",
    "websockets>=13.0",
    "httpx>=0.27.0",
    "pyhanko>=0.25.0",
    "signxml>=3.2.0",
    "python-pkcs11>=0.9.4",
    "typer>=0.14.0",
    "structlog>=24.0.0",
    "cryptography>=43.0.0",
    "certifi>=2024.0.0",
]
```

(Ajuste cada pin para bater com o valor exato já presente em `dependencies` — rode `grep -n 'websockets\|pyhanko\|signxml\|python-pkcs11\|cryptography\|certifi\|structlog\|httpx' pyproject.toml` e copie os operadores de versão.)

- [ ] **Step 5: Rodar o teste (deve passar)**

Run: `uv run pytest tests/unit/agent/test_slim_entrypoint.py -v`
Expected: PASS (2 testes).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tests/unit/agent/test_slim_entrypoint.py
git commit -m "build(agent): grupo de deps slim 'agent' (sem ML) para empacotar o agente"
```

---

## Task 2: Entrypoint slim `juris-agent`

**Files:**
- Create: `src/juris/agent/__init__.py`
- Create: `src/juris/agent/main.py`
- Modify: `pyproject.toml:64` (bloco `[project.scripts]`)
- Test: `tests/unit/agent/test_slim_entrypoint.py` (adiciona teste de import)

**Interfaces:**
- Produces: `juris.agent.main:main` — entrypoint que roda `agent serve` (loopback) sem importar o CLI inteiro nem o app web. Console script `juris-agent`.

- [ ] **Step 1: Escrever o teste que fixa import slim (sem deps pesadas)**

Adicionar a `tests/unit/agent/test_slim_entrypoint.py`:

```python
import subprocess
import sys


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
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "HEAVY:" in r.stdout and r.stdout.strip().endswith("HEAVY:")
```

- [ ] **Step 2: Rodar (deve falhar — módulo não existe)**

Run: `uv run pytest tests/unit/agent/test_slim_entrypoint.py::test_slim_entrypoint_imports_no_heavy_deps -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'juris.agent'`.

- [ ] **Step 3: Criar o pacote e o entrypoint slim**

```python
# src/juris/agent/__init__.py
"""Agente local empacotável (guardião do token A3). Import slim: só o caminho do agente."""
```

```python
# src/juris/agent/main.py
"""Entrypoint standalone do agente Causia — para o PyInstaller empacotar sem o CLI/web.

Roda o agente loopback (`serve`). Pareamento e credenciais são browser-first
(o console dirige /pair-relay e /credentials no loopback). Auto-update roda no
start. NÃO importa juris.cli.main nem juris.web (evita puxar deps pesadas)."""
from __future__ import annotations

import os


def main() -> None:
    from juris.agent.update import maybe_self_update

    # Auto-update antes de servir (best-effort; nunca bloqueia o start).
    try:
        maybe_self_update()
    except Exception:  # noqa: BLE001 - update é best-effort, jamais derruba o agente
        pass

    import uvicorn

    from juris.api.local_agent import app as agent_asgi
    from juris.api.local_agent import validate_local_agent_host

    host = validate_local_agent_host(os.environ.get("JURIS_AGENT_HOST", "127.0.0.1"))
    port = int(os.environ.get("JURIS_AGENT_PORT", "8765"))
    uvicorn.run(agent_asgi, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Registrar o console script**

Em `pyproject.toml`, no bloco `[project.scripts]` (linha 64):

```toml
[project.scripts]
juris = "juris.cli.main:app"
juris-agent = "juris.agent.main:main"
```

- [ ] **Step 5: Sincronizar e rodar o teste (deve passar)**

Run: `uv sync && uv run pytest tests/unit/agent/test_slim_entrypoint.py -v`
Expected: PASS (3 testes). Se `HEAVY:` listar algo, adicionar `excludes` no import (mas o teste anterior já confirmou que `local_agent` é limpo).

- [ ] **Step 6: Verificar que o agente slim sobe**

Run: `JURIS_AGENT_TOKEN=teste-token uv run juris-agent &` então `sleep 3 && curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/health; kill %1`
Expected: um código HTTP (200/404) — prova que o ASGI subiu. (Sem token válido pode recusar; o importante é o processo iniciar.)

- [ ] **Step 7: Commit**

```bash
git add src/juris/agent/ pyproject.toml tests/unit/agent/test_slim_entrypoint.py
git commit -m "feat(agent): entrypoint slim juris-agent para empacotamento standalone"
```

---

## Task 3: Auto-update com manifesto assinado Ed25519

**Files:**
- Create: `src/juris/agent/update.py`
- Test: `tests/unit/agent/test_update.py`

**Interfaces:**
- Consumes: `cryptography.hazmat.primitives.asymmetric.ed25519` (já disponível).
- Produces:
  - `verify_manifest(meta: dict, public_key_pem: str) -> bool` — valida assinatura Ed25519 sobre `{version, sha256, url}`.
  - `maybe_self_update(*, current_version: str | None = None, now: ... ) -> bool` — checa `/api/agent/latest`, se houver versão maior + assinatura válida + sha256 conferido, baixa e troca; retorna True se atualizou.
  - Constante `_UPDATE_PUBLIC_KEY_PEM` (chave pública embutida) e `_MANIFEST_URL` (`https://causia.com.br/api/agent/latest`).

- [ ] **Step 1: Escrever os testes de verificação de assinatura (porta do padrão lida)**

```python
# tests/unit/agent/test_update.py
from __future__ import annotations

import base64
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization


def _keypair() -> tuple[str, Ed25519PrivateKey]:
    priv = Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return pub_pem, priv


def _sign(priv: Ed25519PrivateKey, meta: dict) -> dict:
    from juris.agent.update import _signed_payload

    sig = priv.sign(_signed_payload(meta))
    return {**meta, "signature_alg": "ed25519", "signature": base64.b64encode(sig).decode()}


def test_valid_manifest_verifies() -> None:
    from juris.agent.update import verify_manifest

    pub, priv = _keypair()
    meta = _sign(priv, {"version": "2026.7.4.1", "sha256": "a" * 64, "url": "https://x/y"})
    assert verify_manifest(meta, pub) is True


def test_tampered_manifest_rejected() -> None:
    from juris.agent.update import verify_manifest

    pub, priv = _keypair()
    meta = _sign(priv, {"version": "2026.7.4.1", "sha256": "a" * 64, "url": "https://x/y"})
    meta["sha256"] = "b" * 64  # adulterado após assinar
    assert verify_manifest(meta, pub) is False


def test_wrong_key_rejected() -> None:
    from juris.agent.update import verify_manifest

    pub_other, _ = _keypair()
    _, priv = _keypair()
    meta = _sign(priv, {"version": "2026.7.4.1", "sha256": "a" * 64, "url": "https://x/y"})
    assert verify_manifest(meta, pub_other) is False


def test_version_newer_comparison() -> None:
    from juris.agent.update import is_newer

    assert is_newer("2026.7.4.2", current="2026.7.4.1") is True
    assert is_newer("2026.7.4.1", current="2026.7.4.1") is False
    assert is_newer("2026.6.30.9", current="2026.7.1.0") is False
```

- [ ] **Step 2: Rodar (deve falhar — módulo não existe)**

Run: `uv run pytest tests/unit/agent/test_update.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'juris.agent.update'`.

- [ ] **Step 3: Implementar `update.py` (assinatura + comparação de versão)**

```python
# src/juris/agent/update.py
"""Auto-update do agente com manifesto assinado Ed25519 (padrão do conector lida).

Um servidor comprometido não injeta binário malicioso: o manifesto é assinado com
uma chave privada que vive fora do servidor (só no CI), e o agente valida com a
chave pública embutida antes de trocar o binário."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

_MANIFEST_URL = os.environ.get("JURIS_AGENT_UPDATE_URL", "https://causia.com.br/api/agent/latest")
# Substituída na release pela chave pública real (a privada fica só no CI).
_UPDATE_PUBLIC_KEY_PEM = os.environ.get("JURIS_AGENT_UPDATE_PUBKEY", "")
_SIGNED_FIELDS = ("version", "sha256", "url")


def _signed_payload(meta: dict[str, Any]) -> bytes:
    payload = {k: meta[k] for k in _SIGNED_FIELDS if k in meta}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _load_pub(pem: str) -> Ed25519PublicKey:
    key = load_pem_public_key(pem.encode("utf-8"))
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("chave pública não é Ed25519")
    return key


def verify_manifest(meta: dict[str, Any], public_key_pem: str) -> bool:
    if str(meta.get("signature_alg") or "").lower() != "ed25519":
        return False
    sig = str(meta.get("signature") or "")
    if not sig or not public_key_pem.strip():
        return False
    try:
        _load_pub(public_key_pem).verify(base64.b64decode(sig), _signed_payload(meta))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def is_newer(candidate: str, *, current: str) -> bool:
    def parts(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.split(".") if x.isdigit())

    return parts(candidate) > parts(current)


def current_version() -> str:
    from juris import __version__

    return os.environ.get("JURIS_AGENT_VERSION", __version__)


def maybe_self_update(*, public_key_pem: str | None = None) -> bool:
    """Best-effort: baixa+troca se houver versão maior assinada. Retorna True se atualizou."""
    import httpx

    pub = public_key_pem if public_key_pem is not None else _UPDATE_PUBLIC_KEY_PEM
    if not pub:
        return False  # sem chave embutida → auto-update desligado (dev)
    try:
        meta = httpx.get(_MANIFEST_URL, timeout=10.0).json()
    except (httpx.HTTPError, ValueError):
        return False
    if not verify_manifest(meta, pub) or not is_newer(str(meta.get("version") or ""), current=current_version()):
        return False
    try:
        blob = httpx.get(str(meta["url"]), timeout=120.0, follow_redirects=True).content
    except httpx.HTTPError:
        return False
    if hashlib.sha256(blob).hexdigest() != str(meta.get("sha256") or ""):
        return False  # payload não confere com o manifesto assinado
    return _apply_update(blob)


def _apply_update(blob: bytes) -> bool:
    """Troca atômica do executável empacotado. No-op fora do PyInstaller."""
    if not getattr(sys, "frozen", False):
        return False
    target = sys.executable
    tmp = f"{target}.new"
    with open(tmp, "wb") as fh:
        fh.write(blob)
    os.chmod(tmp, 0o755)
    os.replace(tmp, target)  # atômico; efetiva no próximo start (launchd/Run key reinicia)
    return True
```

- [ ] **Step 4: Rodar os testes (devem passar)**

Run: `uv run pytest tests/unit/agent/test_update.py -v`
Expected: PASS (4 testes).

- [ ] **Step 5: mypy + ruff**

Run: `uv run mypy src/juris/agent && uv run ruff check src/juris/agent`
Expected: sem erros.

- [ ] **Step 6: Commit**

```bash
git add src/juris/agent/update.py tests/unit/agent/test_update.py
git commit -m "feat(agent): auto-update com manifesto assinado Ed25519 (padrão do conector lida)"
```

---

## Task 4: Endpoint público do manifesto + link de download

**Files:**
- Create: `src/juris/web/agent_dist.py`
- Modify: `src/juris/web/app.py` (nova rota `/api/agent/latest`, aberta)
- Test: `tests/unit/web/test_agent_dist.py`

**Interfaces:**
- Consumes: um arquivo `agent-latest.json` (assinado, publicado pelo CI) no diretório servido (`JURIS_AGENT_DIST_DIR`, default `~/juris-pilot/agent-dist`).
- Produces: `GET /api/agent/latest` → o manifesto assinado (público, sem tenant); `GET /api/agent/download/{platform}` → 302 para a URL do instalador do Release.

- [ ] **Step 1: Escrever o teste do endpoint (público, serve manifesto)**

```python
# tests/unit/web/test_agent_dist.py
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from juris.web.app import app


def test_agent_latest_is_public_and_serves_manifest(monkeypatch, tmp_path) -> None:
    (tmp_path / "agent-latest.json").write_text(
        json.dumps({"version": "2026.7.4.1", "sha256": "a" * 64, "url": "https://x/y",
                    "signature_alg": "ed25519", "signature": "Zg=="}),
        encoding="utf-8",
    )
    monkeypatch.setenv("JURIS_AGENT_DIST_DIR", str(tmp_path))
    r = TestClient(app).get("/api/agent/latest")  # sem X-API-Key → deve ser público
    assert r.status_code == 200
    assert r.json()["version"] == "2026.7.4.1"


def test_agent_latest_404_when_absent(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("JURIS_AGENT_DIST_DIR", str(tmp_path))
    assert TestClient(app).get("/api/agent/latest").status_code == 404
```

- [ ] **Step 2: Rodar (deve falhar — rota não existe)**

Run: `uv run pytest tests/unit/web/test_agent_dist.py -v`
Expected: FAIL (404 no primeiro teste, ou rota inexistente).

- [ ] **Step 3: Implementar o serviço + rota**

```python
# src/juris/web/agent_dist.py
"""Distribuição do agente: serve o manifesto de update assinado (público)."""
from __future__ import annotations

import json
import os
from pathlib import Path


def agent_dist_dir() -> Path:
    return Path(os.environ.get("JURIS_AGENT_DIST_DIR", str(Path.home() / "juris-pilot" / "agent-dist")))


def latest_manifest() -> dict[str, object] | None:
    path = agent_dist_dir() / "agent-latest.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
```

Em `src/juris/web/app.py`, ao lado das outras rotas públicas (ex.: após `/api/trial/start`), adicionar (SEM `Depends(current_tenant)` — é público, o manifesto já é assinado):

```python
@app.get("/api/agent/latest")
async def get_agent_latest() -> dict[str, object]:
    """Manifesto de auto-update do agente (público; a integridade vem da assinatura Ed25519)."""
    from juris.web.agent_dist import latest_manifest

    manifest = await asyncio.to_thread(latest_manifest)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Nenhuma versão do agente publicada.")
    return manifest
```

- [ ] **Step 4: Rodar os testes (devem passar)**

Run: `uv run pytest tests/unit/web/test_agent_dist.py -v`
Expected: PASS (2 testes).

- [ ] **Step 5: Garantir que a rota é pública (não quebra o gate de tenant)**

Run: `uv run pytest tests/unit/web/test_security_hardening.py tests/unit/web/test_ui_login_seam.py -q`
Expected: PASS (as rotas abertas conhecidas continuam abertas; a nova é intencionalmente pública).

- [ ] **Step 6: Commit**

```bash
git add src/juris/web/agent_dist.py src/juris/web/app.py tests/unit/web/test_agent_dist.py
git commit -m "feat(web): endpoint público /api/agent/latest (manifesto de update assinado)"
```

---

## Task 5: PyInstaller spec + metadados de versão

**Files:**
- Create: `packaging/agent/causia-agent.spec`
- Create: `packaging/agent/version_info.txt`
- Test: (build-and-verify — sem pytest)

**Interfaces:**
- Consumes: entrypoint `src/juris/agent/main.py`.
- Produces: `dist/causia-agent/` (onedir) com o executável `causia-agent` (macOS) / `causia-agent.exe` (Windows).

- [ ] **Step 1: Criar o `version_info.txt` (metadados legítimos — reduz falso-positivo de AV)**

```
# packaging/agent/version_info.txt — VSVersionInfo do causia-agent.exe.
# Metadados legítimos de editor/produto reduzem falso-positivo de AV em .exe não
# assinado; a solução definitiva é assinar (Azure Trusted Signing — follow-up).
VSVersionInfo(
  ffi=FixedFileInfo(filevers=(2026, 7, 4, 1), prodvers=(2026, 7, 4, 1),
    mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable("041604B0", [
      StringStruct("CompanyName", "Causia"),
      StringStruct("FileDescription", "Agente local do Causia (guardião do token A3 — assina e lê processos com consentimento)"),
      StringStruct("FileVersion", "2026.7.4.1"),
      StringStruct("InternalName", "causia-agent"),
      StringStruct("LegalCopyright", "Causia - uso autorizado pelo escritório"),
      StringStruct("OriginalFilename", "causia-agent.exe"),
      StringStruct("ProductName", "Agente Causia"),
      StringStruct("ProductVersion", "2026.7.4.1"),
    ])]),
    VarFileInfo([VarStruct("Translation", [1046, 1200])]),
  ],
)
```

- [ ] **Step 2: Criar o `.spec` (onedir, sem UPX; hiddenimports do agente)**

```python
# packaging/agent/causia-agent.spec — PyInstaller. Build:
#   uv pip install pyinstaller && pyinstaller packaging/agent/causia-agent.spec
# Saída: dist/causia-agent/ (onedir). SEM UPX (packing dispara AV).
import os, sys

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
ENTRY = os.path.join(ROOT, "src", "juris", "agent", "main.py")
IS_WIN = sys.platform.startswith("win")

a = Analysis(
    [ENTRY],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=[],
    hiddenimports=[
        "juris.api.local_agent", "juris.api.relay", "juris.api.pairing",
        "juris.mni.remote", "juris.signing.remote", "juris.agent.update",
        "uvicorn", "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on", "websockets", "zeep", "pyhanko", "pkcs11",
    ],
    excludes=["torch", "transformers", "sentence_transformers", "sklearn",
              "scipy", "matplotlib", "qdrant_client", "sqlalchemy", "alembic", "pandas"],
    hookspath=[], runtime_hooks=[], cipher=None, noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="causia-agent",
    debug=False, strip=False, upx=False, console=True,
    version=(os.path.join(SPECPATH, "version_info.txt") if IS_WIN else None))
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="causia-agent")
```

- [ ] **Step 3: Build local no macOS (verificação)**

Run:
```bash
uv pip install pyinstaller
uv run pyinstaller packaging/agent/causia-agent.spec --distpath dist --workpath build/pyi --noconfirm
ls dist/causia-agent/causia-agent
```
Expected: o executável existe em `dist/causia-agent/causia-agent`.

- [ ] **Step 4: Rodar o binário empacotado e confirmar que serve loopback**

Run:
```bash
JURIS_AGENT_TOKEN=teste ./dist/causia-agent/causia-agent &
sleep 4 && curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/health; kill %1
```
Expected: um código HTTP — o agente empacotado subiu **sem repo/venv**.

- [ ] **Step 5: Confirmar que o bundle é slim (sem torch)**

Run: `du -sh dist/causia-agent && find dist/causia-agent -iname "*torch*" -o -iname "*sentence*" | head`
Expected: bundle na casa de dezenas de MB (não GB); nenhum arquivo torch/sentence.

- [ ] **Step 6: Commit**

```bash
git add packaging/agent/causia-agent.spec packaging/agent/version_info.txt
echo "dist/" >> .gitignore; echo "build/pyi/" >> .gitignore
git add .gitignore
git commit -m "build(agent): PyInstaller spec slim + version_info (sem UPX, metadados p/ AV)"
```

---

## Task 6: Empacotamento macOS (.app + .dmg + LaunchAgent)

**Files:**
- Create: `packaging/agent/macos/com.causia.agent.plist`
- Create: `packaging/agent/macos/build_dmg.sh`
- Create: `packaging/agent/LEIA-ME.txt`

**Interfaces:**
- Consumes: `dist/causia-agent/` (Task 5).
- Produces: `dist/CausiaAgente.dmg` — instalador não assinado; ao instalar, copia p/ `~/Applications` e instala o LaunchAgent.

- [ ] **Step 1: LaunchAgent (auto-start + KeepAlive + reconecta)**

```xml
<!-- packaging/agent/macos/com.causia.agent.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.causia.agent</string>
  <key>ProgramArguments</key>
  <array><string>__APP_PATH__/Contents/MacOS/causia-agent</string></array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>__HOME__/Library/Logs/causia-agent.log</string>
  <key>StandardErrorPath</key><string>__HOME__/Library/Logs/causia-agent.err</string>
</dict></plist>
```

- [ ] **Step 2: Script de empacotamento .dmg**

```bash
# packaging/agent/macos/build_dmg.sh — gera dist/CausiaAgente.dmg (não assinado).
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
APP="$ROOT/dist/Causia Agente.app"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp -R "$ROOT/dist/causia-agent/." "$APP/Contents/MacOS/"
cat > "$APP/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Causia Agente</string>
  <key>CFBundleIdentifier</key><string>br.com.causia.agent</string>
  <key>CFBundleVersion</key><string>2026.7.4.1</string>
  <key>CFBundleExecutable</key><string>causia-agent</string>
  <key>LSUIElement</key><true/>
</dict></plist>
PL
# instalador embutido: um script que copia o .app e carrega o LaunchAgent
cp "$ROOT/packaging/agent/macos/com.causia.agent.plist" "$APP/Contents/Resources/"
cp "$ROOT/packaging/agent/LEIA-ME.txt" "$ROOT/dist/LEIA-ME.txt"
hdiutil create -volname "Causia Agente" -srcfolder "$ROOT/dist/Causia Agente.app" \
  -srcfolder "$ROOT/dist/LEIA-ME.txt" -ov -format UDZO "$ROOT/dist/CausiaAgente.dmg"
echo "→ dist/CausiaAgente.dmg"
```

(O `LEIA-ME.txt` instrui: arrastar o app para Aplicativos; primeiro abrir = clique-direito → Abrir (contorna o Gatekeeper de app não assinado); o app instala o LaunchAgent na 1ª execução copiando o plist com `__APP_PATH__`/`__HOME__` substituídos.)

- [ ] **Step 3: LEIA-ME do advogado**

```
# packaging/agent/LEIA-ME.txt
AGENTE CAUSIA — instala uma vez, roda sozinho.

O que faz: guarda o seu token A3 no SEU computador e conversa com o Causia.
Seu token e sua senha NUNCA saem da sua máquina.

INSTALAR (macOS):
1. Abra o CausiaAgente.dmg e arraste "Causia Agente" para a pasta Aplicativos.
2. Na PRIMEIRA vez: clique com o botão direito em "Causia Agente" -> Abrir ->
   Abrir. (O aviso de "desenvolvedor não identificado" é esperado — é porque o
   app ainda não é assinado; só nesta primeira vez.)
3. Pronto: o agente sobe sozinho sempre que você liga o computador.

CONECTAR (uma vez):
1. Abra causia.com.br, entre, e vá em Acervo -> Conectar agente local.
2. Cole o código que aparece na tela e informe CPF, senha do PJe e PIN do token.
   Isso vai direto para o agente no SEU computador — o site não recebe.

Não precisa mexer em firewall: o agente não abre porta; ele só liga para fora.
Atualiza sozinho — você nunca precisa baixar de novo.
```

- [ ] **Step 4: Build e verificação**

Run: `bash packaging/agent/macos/build_dmg.sh && ls -la dist/CausiaAgente.dmg`
Expected: o `.dmg` é criado. (Montar e verificar o app abre é passo manual do revisor.)

- [ ] **Step 5: Commit**

```bash
git add packaging/agent/macos/ packaging/agent/LEIA-ME.txt
git commit -m "build(agent): empacotamento macOS (.app/.dmg não assinado) + LaunchAgent + LEIA-ME"
```

---

## Task 7: Empacotamento Windows (.exe + instalador + auto-start)

**Files:**
- Create: `packaging/agent/windows/install.bat`
- Create: `packaging/agent/windows/uninstall.bat`

**Interfaces:**
- Consumes: `dist/causia-agent/` buildado no runner Windows (Task 8).
- Produces: pasta distribuível com `install.bat` que copia p/ `%LOCALAPPDATA%\CausiaAgente`, cria a Run key (auto-start no login), e inicia o agente.

- [ ] **Step 1: install.bat (sem admin; sem porta de entrada; SmartScreen documentado)**

```bat
@echo off
REM packaging/agent/windows/install.bat — instala o Agente Causia no perfil do usuário.
REM Sem admin, sem abrir porta (o agente só disca para fora). SmartScreen pode avisar
REM em .exe nao assinado: "Mais informacoes" -> "Executar assim mesmo" (esperado).
setlocal
set DEST=%LOCALAPPDATA%\CausiaAgente
echo Instalando em %DEST% ...
if exist "%DEST%" rmdir /s /q "%DEST%"
xcopy /e /i /y "%~dp0causia-agent" "%DEST%" >nul
REM auto-start no login (Run key do usuario — nao precisa de admin)
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v CausiaAgente ^
  /t REG_SZ /d "\"%DEST%\causia-agent.exe\"" /f >nul
echo Iniciando o agente...
start "" "%DEST%\causia-agent.exe"
echo.
echo Pronto! Agora abra causia.com.br -^> Acervo -^> Conectar agente local.
pause
```

- [ ] **Step 2: uninstall.bat**

```bat
@echo off
setlocal
taskkill /im causia-agent.exe /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v CausiaAgente /f >nul 2>&1
rmdir /s /q "%LOCALAPPDATA%\CausiaAgente" >nul 2>&1
echo Agente Causia removido.
pause
```

- [ ] **Step 3: Verificação (documental — build/run reais são na Task 8, no runner Windows)**

Run: `cat packaging/agent/windows/install.bat | grep -c "reg add"`
Expected: `1` (a Run key é criada). Revisar que não há `runas`/admin e nenhuma porta de entrada.

- [ ] **Step 4: Commit**

```bash
git add packaging/agent/windows/
git commit -m "build(agent): instalador Windows (Run key, sem admin, sem porta de entrada)"
```

---

## Task 8: CI de release — build cross-platform + manifesto assinado

**Files:**
- Create: `.github/workflows/agent-release.yml`
- Create: `scripts/sign_agent_manifest.py`

**Interfaces:**
- Consumes: secrets do repo — `AGENT_UPDATE_PRIVKEY` (Ed25519 PEM, gerada offline) e a pública embutida via `JURIS_AGENT_UPDATE_PUBKEY` no build.
- Produces: no Release (tag `agent-vAAAA.M.D.seq`): `CausiaAgente.dmg`, `CausiaAgente-win.zip`, e `agent-latest.json` (assinado). O deploy copia `agent-latest.json` para `JURIS_AGENT_DIST_DIR` do Mac Mini.

- [ ] **Step 1: Script que assina o manifesto (roda no CI)**

```python
# scripts/sign_agent_manifest.py — gera agent-latest.json assinado (Ed25519).
# Uso: python scripts/sign_agent_manifest.py <version> <installer_url> <artifact_path> > agent-latest.json
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from juris.agent.update import _signed_payload


def main() -> None:
    version, url, artifact = sys.argv[1], sys.argv[2], sys.argv[3]
    priv = load_pem_private_key(os.environ["AGENT_UPDATE_PRIVKEY"].encode(), password=None)
    assert isinstance(priv, Ed25519PrivateKey)
    sha = hashlib.sha256(open(artifact, "rb").read()).hexdigest()
    meta = {"version": version, "sha256": sha, "url": url}
    sig = priv.sign(_signed_payload(meta))
    print(json.dumps({**meta, "signature_alg": "ed25519",
                      "signature": base64.b64encode(sig).decode()}, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Workflow de release (macOS + Windows)**

```yaml
# .github/workflows/agent-release.yml
name: agent-release
on:
  push:
    tags: ["agent-v*"]
jobs:
  build:
    strategy:
      matrix:
        include:
          - { os: macos-latest, artifact: CausiaAgente.dmg, pack: "bash packaging/agent/macos/build_dmg.sh" }
          - { os: windows-latest, artifact: CausiaAgente-win.zip, pack: "powershell Compress-Archive -Path dist/causia-agent,packaging/agent/windows/install.bat,packaging/agent/windows/uninstall.bat,packaging/agent/LEIA-ME.txt -DestinationPath dist/CausiaAgente-win.zip" }
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --extra agent
      - run: uv pip install pyinstaller
      - env:
          JURIS_AGENT_UPDATE_PUBKEY: ${{ secrets.AGENT_UPDATE_PUBKEY }}
        run: uv run pyinstaller packaging/agent/causia-agent.spec --distpath dist --workpath build/pyi --noconfirm
      - run: ${{ matrix.pack }}
      - uses: actions/upload-artifact@v4
        with: { name: "${{ matrix.artifact }}", path: "dist/${{ matrix.artifact }}" }
  sign-and-release:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with: { path: dist }
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --extra agent
      - env:
          AGENT_UPDATE_PRIVKEY: ${{ secrets.AGENT_UPDATE_PRIVKEY }}
        run: |
          VER="${GITHUB_REF_NAME#agent-v}"
          URL="https://github.com/${GITHUB_REPOSITORY}/releases/download/${GITHUB_REF_NAME}/CausiaAgente.dmg"
          uv run python scripts/sign_agent_manifest.py "$VER" "$URL" dist/CausiaAgente.dmg/CausiaAgente.dmg > agent-latest.json
      - uses: softprops/action-gh-release@v2
        with:
          files: |
            dist/**/CausiaAgente.dmg
            dist/**/CausiaAgente-win.zip
            agent-latest.json
```

- [ ] **Step 3: Validar o YAML e o script localmente**

Run: `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/agent-release.yml'))" && uv run python -c "import ast; ast.parse(open('scripts/sign_agent_manifest.py').read())"`
Expected: sem erro (YAML válido; script parseia).

- [ ] **Step 4: Gerar o par de chaves Ed25519 (offline, uma vez) e registrar os secrets**

Run (local, guardar a privada FORA do repo):
```bash
uv run python -c "
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization as s
k=Ed25519PrivateKey.generate()
open('agent_update_priv.pem','wb').write(k.private_bytes(s.Encoding.PEM,s.PrivateFormat.PKCS8,s.NoEncryption()))
print(k.public_key().public_bytes(s.Encoding.PEM,s.PublicFormat.SubjectPublicKeyInfo).decode())
"
```
Depois: `gh secret set AGENT_UPDATE_PRIVKEY < agent_update_priv.pem`, `gh secret set AGENT_UPDATE_PUBKEY` (a PEM pública impressa), e apagar `agent_update_priv.pem` da máquina após guardar num cofre. (Passo humano — envolve segredo; não automatizar no plano.)

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/agent-release.yml scripts/sign_agent_manifest.py
git commit -m "ci(agent): release cross-platform (PyInstaller macOS+Windows) + manifesto assinado"
```

---

## Task 9: Console — "Baixar o agente" no fluxo de conexão

**Files:**
- Modify: `src/juris/web/static/index.html` (seção Acervo → Conectar agente)
- Test: `tests/unit/web/test_ui_causia_ux.py` (adiciona pin)

**Interfaces:**
- Consumes: `/api/agent/latest` (Task 4) para exibir a versão; links de download do Release por SO.

- [ ] **Step 1: Escrever o pin estático (o console oferece o download do agente)**

Adicionar a `tests/unit/web/test_ui_causia_ux.py`:

```python
def test_console_offers_agent_download() -> None:
    from pathlib import Path

    html = (Path(__file__).resolve().parents[3] / "src" / "juris" / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert "Baixar o agente" in html
    assert "CausiaAgente.dmg" in html or "agent/download" in html
```

- [ ] **Step 2: Rodar (deve falhar)**

Run: `uv run pytest tests/unit/web/test_ui_causia_ux.py::test_console_offers_agent_download -v`
Expected: FAIL.

- [ ] **Step 3: Adicionar o bloco de download no Acervo (perto de "Conectar agente local")**

Localizar em `index.html` o ponto onde o console instrui conectar o agente (busca: `Conectar agente`), e inserir:

```html
<p class="field-note">
  Ainda não instalou? <a id="agent-download-mac" href="#" target="_blank" rel="noopener">Baixar o agente (macOS)</a>
  · <a id="agent-download-win" href="#" target="_blank" rel="noopener">Windows</a>
  <span id="agent-latest-version" class="muted"></span>
</p>
```

E no script, no boot do console (perto de `loadAgentMode()`), preencher os links a partir do Release + versão:

```javascript
async function loadAgentDownload() {
  const REL = "https://github.com/floripasurf/juris/releases/latest/download";
  const mac = document.querySelector("#agent-download-mac");
  const win = document.querySelector("#agent-download-win");
  if (mac) mac.href = `${REL}/CausiaAgente.dmg`;
  if (win) win.href = `${REL}/CausiaAgente-win.zip`;
  try {
    const r = await window.fetch("/api/agent/latest");   // público (pré-auth ok)
    if (r.ok) { const d = await r.json(); const v = document.querySelector("#agent-latest-version"); if (v && d.version) v.textContent = `· versão ${d.version}`; }
  } catch (_) { /* opcional */ }
}
```

E chamar `loadAgentDownload();` dentro de `bootConsole()` (junto aos outros loaders).

- [ ] **Step 4: Rodar os testes (devem passar) + JS válido**

Run: `uv run pytest tests/unit/web/test_ui_causia_ux.py -q && python3 -c "import re,sys; h=open('src/juris/web/static/index.html').read(); m=re.search(r'<script>(.*)</script>', h, re.S); open('/tmp/spa.js','w').write(m.group(1))" && node --check /tmp/spa.js`
Expected: PASS + `node --check` sem erro.

- [ ] **Step 5: Verificar o invariante apiFetch (o fetch novo é `window.fetch`, pré-auth, permitido)**

Run: `uv run pytest tests/unit/web/test_ui_login_seam.py::TestSpaLoginGate::test_every_api_call_goes_through_api_fetch -q`
Expected: PASS (o novo é `window.fetch`, não `fetch(` cru).

- [ ] **Step 6: Commit**

```bash
git add src/juris/web/static/index.html tests/unit/web/test_ui_causia_ux.py
git commit -m "feat(web): console oferece download do agente (macOS/Windows) + versão publicada"
```

---

## Task 10: Verificação end-to-end + docs

**Files:**
- Modify: `docs/deploy/blackcube-pilot.md` (§7 — apontar o instalador em vez do setup manual)
- Modify: `docs/deploy/agent-install.md` (nota: caminho empacotado)

- [ ] **Step 1: Smoke do build slim (macOS local) contra o orquestrador real**

Run (com o agente empacotado rodando e o token A3 plugado):
```bash
JURIS_AGENT_TOKEN=<pareado> ./dist/causia-agent/causia-agent &
sleep 4
curl -s -H "X-API-Key: <chave>" https://causia.com.br/api/agent-health | python3 -c "import json,sys;print(json.load(sys.stdin)['status'])"
kill %1
```
Expected: `ready` (o agente empacotado, sem repo/venv, fecha a cadeia split-trust).

- [ ] **Step 2: Atualizar o runbook §7**

Substituir o passo manual de `com.juris.agent.plist` por: "baixar o instalador no console (Acervo → Baixar o agente), instalar (abrir-mesmo-assim na 1ª vez), e parear pelo próprio console". Manter o caminho manual como apêndice para técnicos.

- [ ] **Step 3: Commit**

```bash
git add docs/deploy/blackcube-pilot.md docs/deploy/agent-install.md
git commit -m "docs(agent): runbook aponta o instalador empacotado (advogado instala sozinho)"
```

---

## Notas de escopo e sequência

- **macOS pode entregar primeiro** (Tasks 1–6, 8–10) e **Windows em seguida** (Task 7 + a matriz Windows da Task 8) — as Tasks 1–4 são compartilhadas e independentes de plataforma.
- **Firewall:** nada a fazer — o agente não abre porta de entrada (liga loopback + disca para fora). Dizer isso ao usuário é parte da UX.
- **Antivírus:** metadados de versão + sem UPX reduzem falso-positivo; a **solução definitiva** é assinar. Follow-up documentado: macOS Developer ID (`codesign` + `notarytool`), Windows **Azure Trusted Signing** (mais barato que EV cert; foi o caminho anotado no projeto lida).
- **Segurança do auto-update:** a chave privada de assinatura vive **só nos secrets do CI**, nunca no servidor nem no cliente — um servidor comprometido não empurra binário malicioso.
