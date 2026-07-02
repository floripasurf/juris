# Deleção LGPD / encerramento de piloto

Use este runbook quando um escritório encerrar o piloto ou pedir apagamento dos
dados de cliente em posse da Juris. A operação é destrutiva e deve ser precedida
por backup quando houver obrigação de retenção ou janela de contestação.

## 1. Backup antes da deleção

```bash
juris backup create
```

Guarde o backup apenas se houver base legal/contratual para retenção. Caso
contrário, apague também o backup ao final do prazo acordado.

## 2. Dry-run obrigatório

```bash
juris tenant erase-data escritorio-alfa
```

O dry-run mostra:

- diretórios/arquivos que serão removidos em `JURIS_HOME` e `JURIS_OUT_ROOT`;
- quantidade de arquivos e bytes;
- linhas de `connect_jobs` do tenant;
- chunks privados do tenant em `repertory.db`;
- frase de confirmação exigida para executar.

Para automação:

```bash
juris tenant erase-data escritorio-alfa --json
```

## 3. Execução com confirmação

```bash
juris tenant erase-data escritorio-alfa --execute --confirm ERASE-escritorio-alfa
```

O comando remove apenas dados escopados ao tenant:

- `<JURIS_HOME>/tenants/<tenant>`;
- `<JURIS_OUT_ROOT>/tenants/<tenant>`;
- rows do tenant em `connect_jobs.db`;
- chunks privados do tenant no `repertory.db`.

O seed público do corpus (`tenant_id IS NULL`) não é removido.

## 4. Certificado de deleção

Após executar, o Juris grava um certificado sem conteúdo sensível em:

```text
${JURIS_HOME:-~/.juris}/compliance-erasure.jsonl
```

Ele registra timestamp, tenant, contadores de arquivos/bytes, connect jobs e
chunks removidos. Não contém peça, prompt, CPF, CNJ ou dados de cliente.

## 5. Tenant legado `public`

O tenant `public` é legado/single-user e pode misturar dados de piloto com estado
operacional local. Por isso exige flag explícita:

```bash
juris tenant erase-data public --allow-public
juris tenant erase-data public --allow-public --execute --confirm ERASE-public
```

Nesse modo, o comando não apaga o diretório `JURIS_HOME` inteiro. Ele remove
artefatos conhecidos de cliente (`juris.db`, `audit.jsonl`, `filings`,
`cache/datajud`) e entradas diretas de `JURIS_OUT_ROOT`, preservando backups,
raízes de tenants configurados e o certificado de deleção.
