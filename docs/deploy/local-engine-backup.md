# Backup do engine local gitignored

O repositório público mantém algumas peças proprietárias fora do Git por design:

- `src/juris/repertory/retrieval/ranking.py`
- testes locais ignorados que cobrem essa peça

Antes de trocar de máquina, fazer limpeza de workspace ou rodar manutenção agressiva,
gere um backup criptografável/arquivável:

```bash
scripts/backup_local_engine.sh
```

Por padrão, o arquivo vai para:

```bash
~/.juris/backups/local-engine/juris-local-engine-<timestamp>.tar.gz
~/.juris/backups/local-engine/juris-local-engine-<timestamp>.tar.gz.sha256
```

Para outro destino:

```bash
JURIS_ENGINE_BACKUP_DIR=/Volumes/Secure/JurisBackups scripts/backup_local_engine.sh
```

Validação e restauração:

```bash
shasum -a 256 -c <arquivo>.sha256
tar -tzf <arquivo>.tar.gz
tar -xzf <arquivo>.tar.gz -C /Users/raphaellages/Desktop/juris
```

O script só inclui arquivos que existem e estão efetivamente ignorados pelo Git.
Isso evita copiar código público redundante e torna explícita a fronteira do engine
local.
