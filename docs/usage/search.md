# `juris search` — Busca unificada de jurisprudência

Pesquisa em paralelo nos portais públicos de jurisprudência de múltiplos
tribunais e devolve resultados mesclados e ranqueados. Substitui o fluxo
manual de abrir N abas de navegador.

**Resultados são efêmeros**: exibidos e descartados. Nada é gravado no
corpus de produção, em cache ou em disco.

## Uso

```bash
# Busca por tema (padrão: tst,stf,stj)
juris search --tema "improbidade administrativa"

# Escolhendo tribunais
juris search --tema "prescrição quinquenal trabalhista" --courts tst

# Todos os adapters que suportam o tipo de busca
juris search --tema "responsabilidade tributária" --courts all

# Busca por número CNJ (tribunal detectado automaticamente; ignora --courts)
juris search --cnj "0001234-56.2024.8.26.0001"

# Filtro por período e limite por tribunal
juris search --tema "dano moral" --from 01/01/2024 --to 31/12/2024 --max 10

# Formatos de saída: table (padrão), json, markdown
juris search --tema "dano moral" --format markdown
```

Exatamente um critério de busca deve ser informado: `--tema`, `--oab`,
`--nome`, `--cpf`, `--cnpj` ou `--cnj`.

## Diagnóstico

```bash
# Health check de todos os adapters registrados
juris search doctor

# Detalhes de roteamento, dedup e ranking de uma consulta
juris search --tema "..." --explain
```

## Status dos portais (validado em 12/06/2026)

| Tribunal | Status | Detalhe |
|---|---|---|
| TST | ✅ funcionando | API JSON (`jurisprudencia-backend2.tst.jus.br`) |
| STF | ❌ bloqueado | WAF descarta clientes não-navegador (HTTP 202 vazio) |
| STJ | ❌ bloqueado | WAF responde 403 com página de desafio |
| TRF3 | ❌ bloqueado | Akamai aceita o handshake TLS e descarta a requisição |
| TJSP | ❌ bloqueado | Busca CJSG do eSAJ exige captcha |
| TRF1, TRF2, TRF5 | ⚠️ endpoint inválido | Portais reestruturados; nova descoberta necessária |
| TRF4 | ⚠️ endpoint inválido | Busca eproc exige tokens gerados por JavaScript |
| TRF6 | ⚠️ endpoint inválido | Portal migrou para portal.trf6.jus.br |

Tribunais bloqueados ou com endpoint inválido falham graciosamente: a
resposta traz os resultados dos demais tribunais e lista as falhas em
`courts_failed`. Os testes live (`tests/integration/test_search_live.py`)
marcam os portais bloqueados como `xfail` — se um portal voltar a aceitar
acesso automatizado, ele aparece como `XPASS` na próxima execução.

Não contornamos WAF nem captcha: a regra do projeto é que portal que
impede acesso automatizado não recebe adapter funcional (ver ADR-0014).

## Ranking

Determinístico (sem ML): hierarquia do tribunal (STF > STJ > TST > TRF >
TJ), recência (boost para decisões dos últimos 24 meses) e sobreposição de
termos com a ementa. Use `--explain` para inspecionar.

## Boas práticas

- Rode buscas grandes fora do horário comercial para reduzir carga nos portais.
- O rate limit é por portal (mínimo 2s entre requisições) e é aplicado
  automaticamente.
- O User-Agent identifica a ferramenta; não nos passamos por navegador.
