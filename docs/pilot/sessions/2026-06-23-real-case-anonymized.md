# Sessão — Caso Real Anonimizado (2026-06-23)

Base do roteiro: `docs/pilot/sessions/2026-05-18-real-case-anonymized-plan.md`
Branch/commit preparado: `feat/cli-cloud-haiku` / `8a4a9a3`
Modo recomendado: `rascunho-pesquisa`
Fonte permitida: `datajud` (consulta pública read-only — não protocola nada)
LLM: **Haiku via assinatura Claude Code** (`--cli-cloud claude`, default Haiku),
**sem `ANTHROPIC_API_KEY`**. Liberado para `datajud` apenas com `--anonimizado`
(operador confirma contexto sem PII). `mni` permanece bloqueado nesta rota.

## Estado da preparação (preenchido por Claude)

| Item | Estado |
| --- | --- |
| Corpus | ✅ PASS — 7390 chunks em 8 tipos de fonte (`repertory status` = pronto) |
| Embeddings (BAAI/bge-m3) | ✅ em cache |
| Banco legado vazio | ✅ removido (warning eliminado) |
| Diretório de saída | ✅ `juris-out-real-anon-2026-06-23` livre (primeiro uso) |
| Disco | ✅ ~28 GB livres |
| LLM provider | ✅ WARN aceitável — CLI cloud `claude` disponível (Haiku via assinatura, sem API key) |

> Sem bloqueio técnico. A rota usa o `claude` da sua assinatura (Haiku),
> verificado ao vivo. Não precisa de `ANTHROPIC_API_KEY`. `WARN` de Ollama
> indisponível é aceitável nesta rota.

## Gates de PII (humanos — confirmar com o(a) advogado(a) ANTES de rodar)

- [ ] Advogado(a) confirmou por escrito que o caso pode ser tratado **sem PII**
      no contexto enviado ao LLM (ou que os fatos sensíveis foram anonimizados).
- [ ] Caso rotineiro, de baixo risco, com movimento recente.
- [ ] Número CNJ anotado **com pontuação** (`NNNNNNN-DD.AAAA.J.TT.OOOO`).
- [ ] Tipo de petição definido (`contestacao`, `manifestacao`, `apelacao`, ...).
- [ ] Tese deixada em branco **ou** escrita sem nomes, CPFs, endereços,
      documentos, dados médicos/bancários ou qualquer identificador.
- [ ] Termos do piloto assinados (PDF arquivado) — `docs/pilot/pilot-terms-pt.md`.

Se qualquer item falhar: **não rodar caso real.** Voltar para fixture ou
registrar o bloqueio na seção Notas.

## 1. Preflight (rodar no dia)

```bash
uv run juris pilot preflight \
  --out juris-out-real-anon-2026-06-23 \
  --skip-ollama-probe \
  --cli-cloud claude
```

Aceite: `Preflight OK` (ou com avisos). `llm_availability` deve ser `WARN`
(CLI cloud `claude` disponível; Ollama indisponível é aceitável). Qualquer
`FAIL` bloqueia a sessão.

Confirmar corpus:

```bash
uv run juris repertory status
```

Aceite: `Pronto para uso real: sim` (hoje: 7390 chunks / 8 tipos). ✅ já validado.

## 2. Comando principal

```bash
uv run juris demo <NUMERO_CNJ_REAL> <TIPO_PETICAO> \
  --source datajud \
  --tribunal <TRIBUNAL> \
  --out juris-out-real-anon-2026-06-23 \
  --cli-cloud claude \
  --anonimizado \
  --modo rascunho-pesquisa
```

`--cli-cloud claude` usa Haiku por default (`--cli-model haiku`; troque para
`sonnet` se quiser mais qualidade no mesmo plano). `--anonimizado` afirma que
o contexto vai sem PII — só usar com o gate do(a) advogado(a) confirmado.

Com tese fixada (apenas texto anonimizado, sem PII):

```bash
uv run juris demo <NUMERO_CNJ_REAL> <TIPO_PETICAO> \
  --source datajud \
  --tribunal <TRIBUNAL> \
  --out juris-out-real-anon-2026-06-23 \
  --cli-cloud claude \
  --anonimizado \
  --modo rascunho-pesquisa \
  --thesis "<TESE SEM PII>"
```

Use `--no-cache` se não puder manter a resposta DataJud em disco local (LGPD).

## 3. Leitura dos artefatos (nesta ordem)

1. `case-summary.md` — DataJud leu o processo correto? (classe, valor, último mov.)
2. `prazos.md` — algum prazo crítico ausente ou errado?
3. `rascunho-pesquisa.md` — análise/argumentos/riscos/esqueleto ajudam?
4. `reviewer-report.md` — achados legítimos vs. falsos positivos.
5. `audit-summary.md` — eventos importantes registrados.

Perguntas obrigatórias ao(à) advogado(a):
- A análise está no foco correto do caso?
- O memorando economiza tempo ou cria mais trabalho?
- As citações e riscos são úteis como ponto de partida?
- O que você apagaria/reescreveria primeiro?
- O que faltou para virar trabalho cobrável?

## 4. Auditoria

```bash
uv run juris audit verify \
  juris-out-real-anon-2026-06-23/<NUMERO_CNJ_REAL>/audit.jsonl
```

Aceite: código de saída 0, integridade da cadeia OK, manifest com os artefatos.

## Bloqueios que encerram a sessão

- Caso contém PII não anonimizável.
- Advogado quer usar dados sensíveis sem consentimento/rota aprovada.
- DataJud retorna erro/dados insuficientes para identificar o processo.
- `reviewer-report.md` indica risco crítico inexplicável na sessão.
- Auditoria falha.

## Decisão de fim de sessão

- [ ] Seguir para piloto pago manual (Pix/NF) com o mesmo escopo.
- [ ] Rodar segunda sessão com outro caso real anonimizado.
- [ ] Pausar para corrigir qualidade de corpus/retrieval/reviewer.
- [ ] Pausar por compliance/LGPD antes de qualquer novo caso real.
- [ ] Encerrar piloto.

## Notas da sessão

### Ambiente
- Data/hora:
- Advogado(a) / OAB:
- Tribunal:
- Número CNJ:
- Tipo de petição:
- Commit:
- Diretório de saída:

### Resultado

| Comando | Resultado | Observação |
| --- | --- | --- |
| `juris pilot preflight` |  |  |
| `juris repertory status` |  |  |
| `juris demo` |  |  |
| `juris audit verify` |  |  |

### Fricções
1.
2.
3.

### Backlog
1.
2.
3.
