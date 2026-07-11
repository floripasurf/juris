"""Contrato + retenção do backup_daily.sh.

O script agenda `juris backup create` e faz rotação sem deletar (expirados vão
para .expired/, política de quarentena). O teste de retenção usa um `juris` falso
para exercitar o off-by-one do `tail -n +N` sem depender de um backup real.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backup_daily.sh"


def test_script_exists_and_is_valid_sh() -> None:
    assert SCRIPT.exists()
    subprocess.run(["/bin/sh", "-n", str(SCRIPT)], check=True)  # noqa: S603


def test_script_never_deletes_only_quarantines() -> None:
    body = SCRIPT.read_text()
    assert "rm " not in body
    assert "rm\t" not in body
    assert ".expired" in body
    assert "chmod 700" in body


def _fake_juris(app_dir: Path) -> Path:
    """Um `juris` falso: em `backup create -o <dir>` cria um .tar.gz + .sha256 novos."""
    bin_dir = app_dir / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    juris = bin_dir / "juris"
    juris.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "backup" ] && [ "$2" = "create" ]; then\n'
        '  dir="$4"\n'
        '  f="$dir/juris-backup-99999999T999999Z.tar.gz"\n'
        '  echo fake > "$f"\n'
        '  echo "hash  $(basename "$f")" > "$f.sha256"\n'
        "fi\n"
    )
    juris.chmod(juris.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return juris


def test_retention_keeps_n_newest_and_quarantines_rest(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    _fake_juris(app_dir)

    # Seed 5 backups pré-existentes com mtimes estritamente crescentes.
    for i in range(5):
        archive = backup_dir / f"juris-backup-2026010{i}T000000Z.tar.gz"
        archive.write_text("old")
        (backup_dir / f"{archive.name}.sha256").write_text("h")
        mtime = 1_700_000_000 + i  # epoch crescente → ordem de `ls -t` determinística
        os.utime(archive, (mtime, mtime))

    env = {
        **os.environ,
        "CAUSIA_APP_DIR": str(app_dir),
        "JURIS_BACKUP_DIR": str(backup_dir),
        "CAUSIA_BACKUP_KEEP": "3",
    }
    result = subprocess.run(  # noqa: S603
        ["/bin/sh", str(SCRIPT)], env=env, capture_output=True, text=True, check=True
    )

    active = sorted(backup_dir.glob("*.tar.gz"))
    expired = sorted((backup_dir / ".expired").glob("*.tar.gz"))
    # 5 seeded + 1 novo = 6; KEEP=3 → 3 ativos, 3 expirados. Nada deletado.
    assert len(active) == 3, result.stdout + result.stderr
    assert len(expired) == 3
    # O backup novo (mtime mais recente) sobrevive à rotação.
    assert any("99999999" in p.name for p in active)
    assert "3 arquivos ativos" in result.stdout
    assert oct(backup_dir.stat().st_mode)[-3:] == "700"
