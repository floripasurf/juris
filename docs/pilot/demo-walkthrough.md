# Demo Walkthrough — `juris demo`

Roteiro de 1 página para o(a) advogado(a) parceiro(a) executar o pipeline
ponta-a-ponta em um caso real ou em modo demo.

## O que o comando faz

`juris demo` lê o processo, analisa movimentos, calcula prazos, gera uma
minuta com citações verificadas e revisão automática, e exporta tudo —
incluindo o audit trail — para `juris-out/<caso>/`.

## Forma básica

```bash
uv run juris demo <NUMERO_CNJ> <TIPO_PETICAO> [opções]
```

| Argumento | Descrição |
| --- | --- |
| `NUMERO_CNJ` | Número CNJ do processo (com pontuação). |
| `TIPO_PETICAO` | `contestacao`, `inicial`, `apelacao`, `manifestacao`, ... |

## Opções principais

| Opção | Default | Descrição |
| --- | --- | --- |
| `--tribunal`, `-t` | `tjmg` | ID do tribunal (ver `juris tribunais`). |
| `--source` | `datajud` | Origem dos dados: `datajud` (real), `fixture` (DEMO). |
| `--out`, `-o` | `juris-out` | Pasta raiz dos artefatos. |
| `--cpf` | _(none)_ | CPF do(a) advogado(a) — futuro: MNI. |
| `--thesis`, `-T` | _(none)_ | Tese explícita (caso queira fixar). |
| `--instructions`, `-i` | `""` | Instruções extras para o(a) drafter. |
| `--cloud` | off | Usa Claude (cloud) em vez de Ollama (local). |
| `--cli-cloud` | _(none)_ | Usa assinatura CLI (`claude` ou `codex`) somente em `--source fixture --modo rascunho-pesquisa`, sem PII. |
| `--modo` | `minuta-sugerida` | `minuta-sugerida` ou `rascunho-pesquisa`. |
| `--skip-review` | off | Pula a revisão pós-draft (mais rápido, menos seguro). |

## Exemplos

**Modo demonstração (offline, fixture, sem credenciais):**

```bash
uv run juris demo 0000000-00.0000.0.00.0000 contestacao \
  --source fixture \
  --modo rascunho-pesquisa \
  --cli-cloud claude
```

Saída fica em `juris-out/DEMO-0000000-00.0000.0.00.0000/`. Cada documento
abre com banner amarelo de DEMO MODE.

**Modo real (DataJud, caso ativo do escritório, sem PII no LLM):**

```bash
uv run juris demo 5001234-56.2024.8.13.0024 contestacao \
  --tribunal tjmg \
  --thesis "Prescrição quinquenal aplicável" \
  --cloud
```

Use esse caminho apenas quando o(a) advogado(a) confirmar que o caso não
contém dados pessoais/sensíveis no contexto enviado ao LLM ou que o material
foi devidamente anonimizado. Não use Ollama local como rota de qualidade para
casos complexos no piloto atual; ele está considerado fraco para esse uso.

## Artefatos gerados

Em `juris-out/<numero_cnj>/`:

- `draft.md` — minuta principal (com rodapé de IA).
- `draft.contraponto.md` — argumentos contrários previstos (se aplicável).
- `rascunho-pesquisa.md` — memorando estruturado quando `--modo rascunho-pesquisa`.
- `reviewer-report.md` — apontamentos do revisor automático.
- `prazos.md` — tabela de prazos pendentes com status e base legal.
- `case-summary.md` — metadados + última movimentação + ações pendentes.
- `audit.jsonl` — cadeia de auditoria (hashes encadeados).
- `audit-summary.md` — recapitulação humana do audit log.
- `run-manifest.json` — metadados da execução + sha256 de cada artefato.

## Verificar a integridade da auditoria

```bash
uv run juris audit verify juris-out/<numero_cnj>/audit.jsonl
```

Sai com código 0 se a cadeia está íntegra, 2 se houver corrupção.

## Antes de protocolar

**Sempre**:

1. Revisar `draft.md` e `reviewer-report.md` linha a linha.
2. Validar `prazos.md` contra o sistema do tribunal.
3. Confirmar que o documento **não** está em modo DEMO (sem prefixo `DEMO-`
   e sem banner amarelo).
4. Aplicar correções pessoais conforme estilo do escritório.
5. Apenas então, assinar com A3 e protocolar — manualmente ou via
   `juris file <caso> draft.md`.

## Regra operacional do piloto atual

- Primeira sessão com Raphael: `--source fixture --modo rascunho-pesquisa --cli-cloud claude|codex`.
- Caso real com PII: não rodar no LLM até existir anonimização/consentimento
  explícito e uma rota cloud adequada, ou outro backend local forte o bastante.
- Ollama local: útil para testes técnicos pequenos; não é critério de aceite
  para redação jurídica complexa.
