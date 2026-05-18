# Smoke Session — Raphael Primeiro Teste

Data alvo: 2026-05-18  
Branch/PR: `feat/llm-cli-cloud-adapter` / PR #2  
Modo: fixture-only, sem PII, `rascunho-pesquisa`, CLI cloud `claude`  
Diretório de saída: `juris-out-smoke-2026-05-18`

## Decisão operacional

Ollama local não é rota de qualidade para informações jurídicas complexas no
piloto atual. A primeira sessão com Raphael deve validar UX, artefatos,
auditoria e fluxo de revisão usando fixture sintética sem PII. Caso real com
PII fica bloqueado até existir anonimização/consentimento/rota cloud adequada
ou backend local mais forte.

## Antes da sessão

- [ ] Confirmar branch atualizado: `git status -sb`.
- [ ] Confirmar CLI cloud autenticado: `claude --version`.
- [ ] Não inserir CNJ real, nomes, CPFs, documentos ou fatos sensíveis no LLM.
- [ ] Usar somente `--source fixture` nesta sessão.
- [ ] Remover run anterior da mesma sessão, se existir:
  `rm -rf juris-out-smoke-2026-05-18`.
- [ ] Manter PR #2 em draft até Raphael aprovar o smoke.

## Pré-flight obrigatório

```bash
uv run juris pilot preflight \
  --out juris-out-smoke-2026-05-18 \
  --fixture-only \
  --skip-ollama-probe \
  --cli-cloud claude
```

Critério:

- `Preflight OK (com avisos)` é aceitável.
- `WARN` sobre Ollama indisponível é aceitável nesta rota.
- Qualquer `FAIL` bloqueia a sessão.

## Smoke principal

```bash
uv run juris demo 0000000-00.0000.0.00.0000 contestacao \
  --out juris-out-smoke-2026-05-18 \
  --source fixture \
  --modo rascunho-pesquisa \
  --cli-cloud claude
```

Artefatos esperados em
`juris-out-smoke-2026-05-18/DEMO-0000000-00.0000.0.00.0000/`:

- `rascunho-pesquisa.md`
- `reviewer-report.md`
- `prazos.md`
- `case-summary.md`
- `audit.jsonl`
- `audit-summary.md`
- `run-manifest.json`

## Auditoria

```bash
uv run juris audit verify \
  juris-out-smoke-2026-05-18/DEMO-0000000-00.0000.0.00.0000/audit.jsonl
```

Critério: saída com integridade OK e código de saída 0.

## Critérios de piloto OK

- [ ] Preflight termina sem `FAIL`.
- [ ] Demo termina com código 0.
- [ ] Todos os artefatos esperados existem.
- [ ] `rascunho-pesquisa.md` está marcado como demonstração e não parece peça protocolável.
- [ ] `reviewer-report.md` aponta riscos de forma útil.
- [ ] `prazos.md` é legível e fácil de revisar.
- [ ] Auditoria passa em `juris audit verify`.
- [ ] Raphael consegue explicar em 2 minutos o que usaria e o que descartaria.
- [ ] Fricções ficam registradas abaixo antes de decidir merge/next sprint.

## Bloqueios explícitos

- Caso real com PII: bloqueado.
- Minuta protocolável: fora do smoke inicial.
- Fallback para Ollama em caso complexo: bloqueado.
- Merge do PR #2: bloqueado até o smoke passar.

## Notas da sessão

### Ambiente

- Commit testado:
- Hora de início:
- Hora de fim:
- CLI cloud:

### Resultado dos comandos

| Comando | Resultado | Observação |
| --- | --- | --- |
| `juris pilot preflight` |  |  |
| `juris demo` |  |  |
| `juris audit verify` |  |  |

### Fricções

1.
2.
3.

### Decisão

- [ ] PR #2 pode sair de draft depois de revisão final.
- [ ] Ajustar docs/comandos antes de novo smoke.
- [ ] Implementar correção antes de qualquer merge.
- [ ] Planejar sessão com caso real anonimizado/sem PII.
