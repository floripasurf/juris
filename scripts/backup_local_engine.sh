#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
DEST="${JURIS_ENGINE_BACKUP_DIR:-$HOME/.juris/backups/local-engine}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="$DEST/juris-local-engine-$STAMP.tar.gz"
CHECKSUM="$ARCHIVE.sha256"

cd "$ROOT"
install -d -m 700 "$DEST"

tmp_list="$(mktemp)"
trap 'rm -f "$tmp_list"' EXIT

candidates=(
  "src/juris/repertory/retrieval/ranking.py"
)

for dir in tests/unit/repertory tests/unit/agents; do
  if [[ -d "$dir" ]]; then
    while IFS= read -r file; do
      candidates+=("$file")
    done < <(find "$dir" -type f -name '*.py' | sort)
  fi
done

for path in "${candidates[@]}"; do
  if [[ -f "$path" ]] && git check-ignore -q "$path"; then
    printf '%s\n' "$path" >> "$tmp_list"
  fi
done

if [[ ! -s "$tmp_list" ]]; then
  echo "No gitignored local engine files found to back up." >&2
  exit 1
fi

COPYFILE_DISABLE=1 tar -czf "$ARCHIVE" -C "$ROOT" -T "$tmp_list"
shasum -a 256 "$ARCHIVE" > "$CHECKSUM"
chmod 600 "$ARCHIVE" "$CHECKSUM"

echo "Backup created: $ARCHIVE"
echo "Checksum: $CHECKSUM"
