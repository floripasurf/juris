# Escavação — o moat de inteiro teor

A espinha (súmulas/temas) diz *quais* casos-líderes importam; a escavação coleta o
**inteiro teor** deles e o ingere no corpus profundo com proveniência. É o fosso:
jurisprudência que ninguém mais tem indexada do mesmo jeito.

## Fluxo

```
espinha → construir_fila → executar_escavacao(FailoverFetcher) → write_inteiro_teor
        → (engine) ingestão no corpus canônico → busca com score explicado
```

`juris escavacao run --seed <espinha.json> --out <dir>` roda até `write_inteiro_teor`
(o limite do que é versionável/tracked). A ingestão no corpus vetorial é engine-local.

## Modelo de dados (`InteiroTeor`)

Cada registro carrega **proveniência**: `fonte`, `url`, `licenca`, `data_coleta`,
`parcial` (trilha DataJud vs acórdão completo), `content_hash` (sha256 do texto) e
`origem_tema` (qual espinha o trouxe). **Dedup** por `dedup_key = (content_hash,
numero_cnj, fonte)`: re-coleta é idempotente, mas o mesmo acórdão de **outra fonte**
é mantido — corroboração é sinal, não ruído (`dedup_inteiro_teor`).

`write_inteiro_teor` grava um arquivo por registro, nomeado
`<cnj>__<fonte>__<hash12>.json`, espelhando o `dedup_key` — TST e DataJud do mesmo
processo ficam em arquivos distintos, **nunca se sobrescrevem**. `load_inteiro_teor`
lê todos de volta para a ingestão.

## Fontes (Source Mesh — `FailoverFetcher`)

`build_escavacao_fetcher()` compõe as fontes em ordem de qualidade:

1. **TST** (`TSTEscavacaoFetcher`) — primeira fonte real, acórdão completo
   (`parcial=False`), da jurisprudência pública do TST. **Sem bypass de WAF/captcha**:
   falha de fetch/parse → `None` → cai para a próxima fonte.
2. **DataJud** (`DataJudEscavacaoFetcher`) — trilha de movimentos (`parcial=True`),
   o fallback honesto quando não há acórdão completo.

Uma fonte **completa** vence qualquer trilha parcial imediatamente.

## Sinais de ranking (contrato p/ o ranker composto — ADR-0017)

O ranker engine (local) usa, além de relevância/autoridade/vigência:

- **`inteiro_teor`** — tem o texto completo? (vs. só ementa/trilha)
- **`parcial`** — `True` penaliza (DataJud) quando há acórdão completo da mesma decisão.
- **`fonte_confianca`** — `escavacao/fontes.py::fonte_confianca(fonte)` ∈ [0,1]
  (TST/STF/STJ=1.0, esaj/cjsg=0.9, DataJud=0.3). É o **contrato tracked** que o
  ranker importa; expõe-se no `score_components` (auditabilidade).

**DoD:** a busca mostra o precedente com inteiro teor, a fonte e o score explicado.

## Smoke test (selectors do TST)

Os selectors de `parse_tst_acordao` são validados contra uma fixture realista. Antes
de apontar para o TST ao vivo, valide-os contra um acórdão real (a estrutura HTML
pode diferir): rode o fetcher com `fetch_html` apontando para uma amostra salva e
confira se `texto` traz ementa + acórdão. Ajuste `_PRIMARY_SELECTORS` se necessário.
