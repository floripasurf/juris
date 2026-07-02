# Backup/restore operacional

Esta rotina protege o estado local crítico do Juris:

- `JURIS_HOME`: bancos SQLite por tenant, `audit.jsonl`, âncora HMAC, filas e recibos de protocolo;
- `JURIS_OUT_ROOT`: artefatos gerados por caso, quando `--include-out-root` está ativo;
- `repertory.db`: corpus canônico, inclusive quando `JURIS_REPERTORY_PATH` aponta para fora do `JURIS_HOME`.

O backup é sensível: pode conter dados pessoais, peças, recibos e hashes de cadeia de custódia. Armazene o `.tar.gz` e o `.sha256` com criptografia em repouso e acesso owner-only.

## Criar backup

```bash
export JURIS_HOME=/var/lib/juris
export JURIS_OUT_ROOT=/var/lib/juris/out
export JURIS_BACKUP_DIR=/var/backups/juris

juris backup create
```

Saída esperada:

```text
Backup criado: /var/backups/juris/juris-backup-YYYYMMDDTHHMMSSZ.tar.gz
SHA-256: ...
Checksum: /var/backups/juris/juris-backup-YYYYMMDDTHHMMSSZ.tar.gz.sha256
Arquivos: ...
```

Para excluir artefatos de saída grandes e capturar só estado operacional:

```bash
juris backup create --no-out-root
```

Para escrever em um diretório específico:

```bash
juris backup create --output /Volumes/Encrypted/JurisBackups
```

## Restaurar para inspeção

O restore nunca escreve diretamente nos caminhos absolutos originais. Ele materializa a árvore em um diretório escolhido para inspeção:

```bash
juris backup restore /var/backups/juris/juris-backup-YYYYMMDDTHHMMSSZ.tar.gz /tmp/juris-restore
```

A árvore resultante usa estes prefixos:

```text
/tmp/juris-restore/juris_home/...
/tmp/juris-restore/out_root/...
/tmp/juris-restore/repertory/repertory.db
```

Depois de validar o conteúdo e parar o serviço, copie os arquivos necessários para o destino de produção durante uma janela controlada.

## Verificação

Antes de restaurar:

```bash
shasum -a 256 -c /var/backups/juris/juris-backup-YYYYMMDDTHHMMSSZ.tar.gz.sha256
```

Durante o restore, o Juris também confere o SHA-256 de cada arquivo listado no `manifest.json` e rejeita caminhos que tentem escapar do diretório de destino.

## Rotina recomendada

- Rode `juris backup create` antes de deploy, manutenção de agente ou migração de corpus.
- Guarde pelo menos uma cópia fora da máquina do operador.
- Teste `juris backup restore ... /tmp/juris-restore-smoke` periodicamente.
- Rode `juris audit verify <restore>/juris_home/audit.jsonl` quando o backup contiver uma cadeia de auditoria ativa.
