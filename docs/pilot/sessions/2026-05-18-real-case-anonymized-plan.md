# Plano de Sessao — Caso Real Anonimizado

Data alvo: a agendar

Base: smoke fixture de 2026-05-18

Modo recomendado: `rascunho-pesquisa`

Fonte permitida: `datajud`

LLM permitido: cloud somente com caso sem PII ou anonimizado

## Objetivo

Validar se o Juris ajuda o(a) advogado(a) em um caso real de baixo risco sem
expor dados pessoais ou sensiveis ao LLM. Esta sessao nao tenta produzir
minuta protocolavel; o resultado esperado e um memorando revisavel, prazos,
relatorio do reviewer e audit trail integro.

## Gates antes de rodar

- [ ] O(a) advogado(a) confirmou por escrito que o caso escolhido pode ser
  tratado sem PII no contexto enviado ao LLM, ou que os fatos sensiveis foram
  anonimizados.
- [ ] O caso e rotineiro, de baixo risco e tem movimento recente.
- [ ] O numero CNJ esta anotado com pontuacao.
- [ ] O tipo de peticao esperado esta definido (`contestacao`, `manifestacao`,
  `apelacao`, etc.).
- [ ] A tese foi deixada em branco ou escrita sem nomes, CPFs, enderecos,
  documentos, dados medicos, dados bancarios ou outros identificadores.
- [ ] `juris pilot preflight` passou sem `FAIL`.
- [ ] O operador aceitou que `--source datajud` e read-only e nao protocola nada.

Se qualquer item acima falhar, nao rodar caso real. Voltar para fixture ou
registrar o bloqueio no fim deste arquivo.

## Preflight

```bash
uv run juris pilot preflight \
  --out juris-out-real-anon-YYYY-MM-DD \
  --skip-ollama-probe
```

Aceite:

- `Preflight OK` ou `Preflight OK (com avisos)`.
- `WARN` sobre Ollama indisponivel e aceitavel nesta rota.
- Qualquer `FAIL` bloqueia a sessao.

Confirmar corpus antes de prosseguir:

```bash
uv run juris repertory status
```

Aceite minimo para caso real:

- `Pronto para uso real: sim`
- Total de chunks igual ou acima do limiar configurado.
- Pelo menos dois tipos de fonte distintos.

## Comando principal

```bash
uv run juris demo <NUMERO_CNJ_REAL> <TIPO_PETICAO> \
  --source datajud \
  --tribunal <TRIBUNAL> \
  --out juris-out-real-anon-YYYY-MM-DD \
  --cloud \
  --modo rascunho-pesquisa
```

Se o(a) advogado(a) quiser fixar uma tese, usar apenas texto anonimizado:

```bash
uv run juris demo <NUMERO_CNJ_REAL> <TIPO_PETICAO> \
  --source datajud \
  --tribunal <TRIBUNAL> \
  --out juris-out-real-anon-YYYY-MM-DD \
  --cloud \
  --modo rascunho-pesquisa \
  --thesis "<TESE SEM PII>"
```

Nao usar `--cli-cloud` aqui. Esse caminho ficou restrito ao smoke fixture sem
PII. Para caso real, usar `--cloud` apenas depois dos gates de anonimização.

## Leitura dos artefatos

Abrir nesta ordem:

1. `case-summary.md`: validar se DataJud leu o processo correto.
2. `prazos.md`: checar se algum prazo importante esta ausente ou errado.
3. `rascunho-pesquisa.md`: avaliar se a analise, argumentos, riscos e esqueleto
   ajudam o trabalho do(a) advogado(a).
4. `reviewer-report.md`: separar achados legitimos de falsos positivos.
5. `audit-summary.md`: confirmar que os eventos importantes foram registrados.

Perguntas obrigatorias para o(a) advogado(a):

- A analise esta no foco correto do caso?
- O memorando economiza tempo ou cria mais trabalho?
- As citacoes e riscos sao uteis como ponto de partida?
- Qual e a primeira coisa que voce apagaria ou reescreveria?
- O que faltou para transformar isso em trabalho cobravel?

## Auditoria

```bash
uv run juris audit verify \
  juris-out-real-anon-YYYY-MM-DD/<NUMERO_CNJ_REAL>/audit.jsonl
```

Aceite:

- Codigo de saida 0.
- Integridade da cadeia OK.
- Manifest inclui os artefatos esperados.

## Bloqueios que encerram a sessao

- O caso contem PII que nao pode ser anonimizada.
- O advogado quer usar dados sensiveis sem consentimento/rota aprovada.
- O corpus nao esta pronto para uso real.
- DataJud retorna erro ou dados insuficientes para identificar o processo.
- `reviewer-report.md` indica risco critico que o operador nao consegue
  explicar durante a sessao.
- Auditoria falha.

## Decisao de fim de sessao

- [ ] Seguir para piloto pago manual (Pix/NF) com o mesmo escopo.
- [ ] Rodar segunda sessao com outro caso real anonimizado.
- [ ] Pausar para corrigir qualidade de corpus/retrieval/reviewer.
- [ ] Pausar por compliance/LGPD antes de qualquer novo caso real.
- [ ] Encerrar piloto.

## Notas

### Ambiente

- Data/hora:
- Advogado(a):
- Tribunal:
- Numero CNJ:
- Tipo de peticao:
- Commit:
- Diretorio de saida:

### Resultado

| Comando | Resultado | Observacao |
| --- | --- | --- |
| `juris pilot preflight` |  |  |
| `juris repertory status` |  |  |
| `juris demo` |  |  |
| `juris audit verify` |  |  |

### Friccoes

1.
2.
3.

### Backlog

1.
2.
3.
