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

- [x] Confirmar branch atualizado: `git status -sb`.
- [x] Confirmar CLI cloud autenticado: `claude --version`.
- [x] Não inserir CNJ real, nomes, CPFs, documentos ou fatos sensíveis no LLM.
- [x] Usar somente `--source fixture` nesta sessão.
- [x] Remover run anterior da mesma sessão, se existir:
  `rm -rf juris-out-smoke-2026-05-18`.
- [x] Marcar PR #2 como ready-for-review depois do smoke e da revisão final.

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

- [x] Preflight termina sem `FAIL`.
- [x] Demo termina com código 0.
- [x] Todos os artefatos esperados existem.
- [x] `rascunho-pesquisa.md` está marcado como demonstração e não parece peça protocolável.
- [x] `reviewer-report.md` aponta riscos de forma útil.
- [x] `prazos.md` é legível e fácil de revisar.
- [x] Auditoria passa em `juris audit verify`.
- [ ] Raphael consegue explicar em 2 minutos o que usaria e o que descartaria.
- [x] Fricções ficam registradas abaixo antes de decidir merge/next sprint.

## Bloqueios explícitos

- Caso real com PII: bloqueado.
- Minuta protocolável: fora do smoke inicial.
- Fallback para Ollama em caso complexo: bloqueado.
- Merge do PR #2: bloqueado até decisão explícita de merge.

## Notas da sessão

### Ambiente

- Commit testado: base `19130bf` com correção local do adapter CLI/schema.
- Hora de início: 2026-05-18 16:15:01 PDT
- Hora de fim: 2026-05-18 16:23:25 PDT
- CLI cloud: `claude` 2.1.143 (Claude Code)

### Resultado dos comandos

| Comando | Resultado | Observação |
| --- | --- | --- |
| `juris pilot preflight` | PASS com avisos | `Preflight OK (com avisos)`; CLI cloud `claude` disponível; Ollama indisponível esperado nesta rota; banco legado detectado. |
| `juris demo` | PASS | Código 0 em 504.6s; 7 artefatos gerados em `juris-out-smoke-2026-05-18/DEMO-0000000-00.0000.0.00.0000/`. |
| `juris audit verify` | PASS | `Total entries: 10`; `Chain integrity: OK`. |

### Fricções

1. O smoke anterior expôs bug real: `LocalCliLLM` não aceitava `schema` estruturado, o que deixava o reviewer vazio. A correção local fez o reviewer rodar e produzir riscos úteis.
2. `reviewer-report.md` agora é útil e severo: `4 problemas criticos`, `18 problemas importantes`, `15 sugestoes`.
3. `uv run pytest -q` não ficou verde por falhas fora deste smoke: `10 failed, 1020 passed, 1 skipped`; corpus local incompleto (`stf-sv: 0`, total ativo `685 < 800`) e testes live de tribunais com SSL/403/timeout/HTML não JSON. Testes focados da correção passaram: `8 passed`.

### Decisão

- [x] PR #2 saiu de draft depois da revisão final e está pronto para review.
- [x] Ajustar docs/comandos antes de novo smoke.
- [x] Implementar correção antes de qualquer merge.
- [ ] Planejar sessão com caso real anonimizado/sem PII.
