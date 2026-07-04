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
