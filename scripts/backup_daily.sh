#!/bin/sh
# Backup diário do CAUSIA no Mac Mini. Chamado pelo launchd com.causia.backup
# com as MESMAS env vars de com.causia.web (JURIS_HOME, JURIS_OUT_ROOT, ...).
#
# `juris backup create -o <dir>` grava juris-backup-<timestamp>.tar.gz (+ .sha256)
# com manifesto e SHA-256 por arquivo, cobrindo JURIS_HOME, JURIS_OUT_ROOT,
# repertory.db, audit logs e recibos.
#
# Retenção: mantém os N .tar.gz mais recentes; expirados vão para .expired/
# (purge manual — nada é deletado automaticamente, conforme política de quarentena).
set -eu

APP_DIR="${CAUSIA_APP_DIR:-$HOME/juris-pilot/app}"
BACKUP_DIR="${JURIS_BACKUP_DIR:-$HOME/juris-pilot/backups}"
KEEP="${CAUSIA_BACKUP_KEEP:-14}"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

"$APP_DIR/.venv/bin/juris" backup create -o "$BACKUP_DIR"

mkdir -p "$BACKUP_DIR/.expired"
# Lista os .tar.gz por mtime decrescente e move do (KEEP+1)-ésimo em diante,
# junto do respectivo .sha256. Sem rm: expirados apenas migram para .expired/.
ls -t "$BACKUP_DIR"/*.tar.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | while IFS= read -r old; do
  mv "$old" "$BACKUP_DIR/.expired/"
  if [ -f "$old.sha256" ]; then
    mv "$old.sha256" "$BACKUP_DIR/.expired/"
  fi
done

echo "backup_daily ok: $(ls "$BACKUP_DIR"/*.tar.gz 2>/dev/null | wc -l | tr -d ' ') arquivos ativos"
