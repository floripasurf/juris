# DataJud API Pública — snapshot operacional (2026-05-09)

Este snapshot orienta o uso do DataJud no Juris durante pilotos. Ele não
substitui o Termo de Uso oficial. Antes de rodar batches grandes, revalidar
as páginas abaixo.

## Fontes consultadas

- Portal CNJ — API Pública: https://www.cnj.jus.br/sistemas/datajud/api-publica/
- DataJud Wiki — API Pública: https://datajud-wiki.cnj.jus.br/api-publica/
- DataJud Wiki — Termo de Uso: https://datajud-wiki.cnj.jus.br/api-publica/termo-uso/
- DataJud Wiki — Acesso/API Key: https://datajud-wiki.cnj.jus.br/api-publica/acesso/
- DataJud Wiki — Endpoints: https://datajud-wiki.cnj.jus.br/api-publica/endpoints/

## O que a API disponibiliza

A API Pública do DataJud dá acesso público a metadados, capas processuais e
movimentações de processos públicos, respeitando processos sigilosos e dados
de partes conforme os critérios da Base Nacional de Dados do Poder Judiciário.
O uso indicado pela documentação inclui pesquisa, desenvolvimento de
aplicações de acesso à informação jurídica e análise de tendências do sistema
de Justiça, observando o Termo de Uso.

## Autenticação

A Wiki informa que a autenticação usa chave pública no cabeçalho:

```http
Authorization: APIKey <chave-publica-vigente>
```

Em 2026-05-09, a chave pública exibida pela Wiki coincide com a chave já usada
em `src/juris/datajud/client.py`. A própria Wiki alerta que o CNJ pode alterar
a chave a qualquer momento.

## Endpoints

A URL base pública é:

```text
https://api-publica.datajud.cnj.jus.br/
```

Cada tribunal usa um alias próprio seguido de `/_search`, por exemplo:

```text
https://api-publica.datajud.cnj.jus.br/api_publica_tjmg/_search
```

## Pontos do Termo de Uso relevantes para o Juris

O usuário aceita as condições ao consumir a API. A Wiki destaca que o usuário
é responsável pelo uso da interface e das informações derivadas, que a API deve
ser usada somente para fins legais, não abusivos e autorizados, que o CNJ não
garante precisão/integridade/atualidade dos dados, e que disponibilizações
públicas de estudos/relatórios/documentos derivados devem dar ciência ao CNJ
conforme o Termo de Uso.

## Política operacional no Juris

- **Smoke test unitário:** `juris demo <cnj> <tipo> --source datajud` pode
  consultar um processo real por vez. É read-only, não usa A3, não assina e não
  protocola.
- **Batch / telemetria:** qualquer fluxo com `>=10` CNJs exige confirmação
  explícita (`--confirm-batch` ou flag equivalente no comando chamador).
- **Rate limit default:** `1 req/sec`, configurável por
  `JURIS_DATAJUD_RATE_LIMIT_PER_SECOND`.
- **Cache local:** respostas ficam em `~/.juris/cache/datajud/` ou no caminho
  definido por `JURIS_DATAJUD_CACHE_DIR`.
- **TTL default:** 24h para respostas com movimentações; 7 dias pode ser usado
  apenas para metadados estáticos.
- **Purge:** operador pode limpar o cache com `juris cache purge --datajud`.
- **Auditoria:** cada chamada DataJud deve registrar `datajud.request` com CNJ,
  tribunal, endpoint, cache hit/miss, status HTTP, duração e contagem de hits.
