# Smoke Test — Roteiro e Notas de Sessão

Este documento serve dois propósitos:

1. **Antes da sessão:** roteiro detalhado para a 1ª sessão de 1h com o(a)
   advogado(a) parceiro(a) — complementa `onboarding.md` (que cuida dos
   pré-requisitos de ambiente).
2. **Durante e depois da sessão:** template de captura de fricções,
   surpresas e correções pendentes. Preencha as seções `[NOTAS]` no fim.

> Mantém **um arquivo por sessão** — copie para
> `docs/pilot/sessions/<YYYY-MM-DD>-smoke.md` antes de começar e edite a
> cópia. O original fica como template em branco.

---

## Limitações conhecidas — leitura obrigatória antes de uma sessão com caso real

Não pular esta seção. Cada item abaixo afeta a confiabilidade da minuta
para o(a) parceiro(a) advogado(a) e tem ação explícita do operador.

### L1 · Corpus jurisprudencial precisa estar populado

Sem corpus, a recuperação de citações retorna lista vazia e a minuta
sai sem citações verificáveis. Para fechar este modo de falha o
`juris demo` em `--source datajud|mni` agora bloqueia a execução
quando o corpus não atinge os limiares mínimos (Sprint 16). Em modo
`--source fixture` a saída roda mas o banner DEMO deixa explícito que
não é protocolável.

**Ação obrigatória do operador antes de uma sessão com caso real:**

```bash
# Inspecionar corpus (saída humana ou --json)
uv run juris repertory status

# Saída esperada:
#   Pronto para uso real: sim
#   Total de chunks ≥ 100, Tipos de fonte distintos ≥ 2
```

Se aparecer `Pronto para uso real: não`, **abortar a sessão** e rodar
a ingestão (`uv run juris repertory ingest`) ou apontar
`JURIS_REPERTORY_PATH` para um DB populado. Tudo isso já está coberto
pelo `juris pilot preflight` na §0 — esta seção é a explicação do
"porquê", o pré-flight é a checagem operacional.

Caminho canônico do corpus: `~/.juris/repertory.db`. Override via
`JURIS_REPERTORY_PATH=/caminho/custom`. Limiares default
(`min_chunks=100`, `min_source_types=2`) podem ser ajustados via
`JURIS_MIN_REPERTORY_CHUNKS` / `JURIS_MIN_REPERTORY_SOURCE_TYPES` ou
flags `--min-chunks`/`--min-source-types` em `juris repertory status`.

### L2 · MNI ainda não implementado

`--source mni` lança `NotImplementedError`. Para a 1ª sessão use
`--source datajud` (consulta pública pelo CNJ) ou `--source fixture`
(offline). MNI entra em rotação assim que o token A3 for testado em
ambiente isolado.

### L3 · Audit log acumula entre execuções

Rodar `juris demo` várias vezes para o mesmo CNJ no mesmo diretório de
saída faz todos os eventos cairem no mesmo `audit.jsonl`. Mitigação no
pré-flight: limpar `juris-out/<numero_cnj>` antes da sessão.

---

## 0. Pré-flight (10 min antes da sessão)

Já tudo do `onboarding.md` está pronto. Esta lista cobre o que é
delicado nos minutos imediatamente antes da sessão.

**Único comando obrigatório:**

```bash
uv run juris pilot preflight --out juris-out
```

Tudo verde (`Preflight OK`) → seguir. Qualquer `FAIL` → abortar e
remediar. Itens com `WARN` são informativos (ex.: só Ollama OU só
Anthropic configurado, mas a sessão pode rodar com qualquer um deles).

Checks cobertos automaticamente: corpus pronto (§L1), modelo de
embeddings em cache, ao menos um provedor de LLM disponível,
diretório de saída sem runs anteriores (§L3), espaço em disco. Saída
em `--json` para automação.

**Itens manuais que o pré-flight não cobre** (físicos / em papel):

- [ ] Token A3 conectado e PIN testado num site qualquer da Receita.
- [ ] CNJ do caso real anotado **com pontuação** (`NNNNNNN-DD.AAAA.J.TT.OOOO`).
- [ ] Termos do piloto assinados (PDF arquivado).

---

## 1. Estrutura da sessão (1h)

| Tempo | Atividade | Comando / artefato |
| ---: | --- | --- |
| 0:00–0:03 | Boas-vindas, recapitular limites do piloto §2 | `pilot-terms-pt.md` |
| 0:03–0:08 | Demo em **modo fixture** (offline, dados sintéticos) | ver §2 |
| 0:08–0:12 | Mostrar artefatos gerados em modo DEMO | `juris-out/DEMO-*/` |
| 0:12–0:35 | Demo em **modo real** sobre o caso escolhido | ver §3 |
| 0:35–0:50 | Leitura conjunta dos artefatos | §4 + `[NOTAS]` |
| 0:50–0:55 | Verificação da auditoria | `juris audit verify` |
| 0:55–1:00 | Decisão: seguir, pausar, ajustar escopo | `[NOTAS] §10` |

---

## 2. Demo em modo fixture (3–5 min)

Objetivo: mostrar pipeline funcionando **sem expor dados reais**, validar
que o ambiente do(a) parceiro(a) está OK.

```bash
uv run juris demo 0000000-00.0000.0.00.0000 contestacao --source fixture
```

**O que esperar:**

- Banner amarelo `MODO DEMONSTRAÇÃO ATIVO`.
- Diretório de saída prefixado `DEMO-`.
- 6 artefatos no final (8 se gerar contraponto).
- Cada `.md` abre com bloco de aviso `MODO DEMONSTRAÇÃO — NÃO PROTOCOLAR`.
- Saída termina com mensagem **verde** `Concluído em Xs.`
- Código de saída: **0** (zero).

Mostre rapidamente abrindo `case-summary.md` e `audit-summary.md` no editor.

---

## 3. Demo em modo real (20–25 min)

Objetivo: produzir uma minuta navegável a partir de um caso real do(a)
parceiro(a). **Esta é a hora da verdade do produto.**

```bash
uv run juris demo \
  <NUMERO_CNJ_REAL> contestacao \
  --tribunal tjmg \
  --thesis "<tese sugerida pelo(a) advogado(a) ou deixe em branco>" \
  --cloud
```

**Recomendações:**

- Use `--cloud` se o caso **não** tiver dados sensíveis (PII de cliente,
  dados médicos, segredo de justiça). Caso contrário, omita `--cloud` e
  use Ollama local.
- Defina `--thesis` **somente** se o(a) advogado(a) quiser fixar a tese.
  Sem `--thesis`, o drafter infere via LLM.
- O comando leva **2–6 minutos**. Aproveite para discutir o caso,
  recapitular o objetivo da sessão, etc.

**O que observar durante a execução:**

- Logs estruturados (linhas começando com `[info]`/`[warning]`).
- `[warning] hyde_expansion_failed` ou `[warning] thesis_inference_failed`
  são **degradação silenciosa**: o pipeline continua mas a qualidade da
  recuperação cai. Anote em `[NOTAS] §6`.
- `audit_appended` indica cada evento auditado — esperar ≥10 entradas em
  uma execução completa.

**Quando terminar:**

- Se mensagem **verde** `Concluído em Xs.` → seguir para §4.
- Se mensagem **vermelha** `Falhou após Xs (artefatos parciais gravados)`
  → registrar erro em `[NOTAS] §7` e tentar uma vez de novo, ou cair para
  `--source fixture` para recuperar a sessão.

---

## 4. Leitura conjunta dos artefatos (15 min)

Abrir lado a lado, na ordem:

1. **`case-summary.md`** — confirmação de que o processo foi lido
   corretamente (classe, valor da causa, último movimento).
2. **`prazos.md`** — prazos pendentes, base legal, dias úteis vs.
   corridos. **Pergunta para o(a) advogado(a):** algum prazo crítico
   ausente ou divergente?
3. **`draft.md`** — minuta principal. Leia em silêncio durante 5 min,
   depois discuta:
   - Estrutura está aceitável?
   - Citações estão verificadas (ver `reviewer-report.md`)?
   - Tese é adequada ao caso?
   - O que o(a) advogado(a) reescreveria? **Capturar como fricções.**
4. **`draft.contraponto.md`** (se gerado) — argumentos contrários
   previstos. Útil ou ruído?
5. **`reviewer-report.md`** — severidade dos achados do revisor. Falsos
   positivos? Pontos legítimos perdidos pelo drafter?

**Não tente "polir" a minuta na sessão.** O ciclo é: gerar → ler →
listar fricções → ajustar prompts/templates fora da sessão.

---

## 5. Verificação da auditoria (3 min)

```bash
uv run juris audit verify juris-out/<numero_cnj>/audit.jsonl
```

Esperar:

- Saída: `Integridade da cadeia: OK`.
- Código de saída **0**.
- Se aparecer `corrupção detectada na entrada N` → **incidente sério**,
  registrar em `[NOTAS] §9` e investigar antes de qualquer outra demo.

---

## 6. Conhecidos (do dry-run interno em 2026-05-08)

Estes itens **não** são bugs novos a descobrir na sessão — são os pontos
já mapeados internamente. Validar se afetam o caso real, não voltar a
descobrir do zero.

- **Audit log acumula entre execuções no mesmo `<numero_cnj>` dir.**
  Se rodar `juris demo` várias vezes para o mesmo caso, todos os eventos
  vão para o mesmo `audit.jsonl`. Mitigação: limpar o diretório antes da
  sessão (passo do pré-flight).
- **`hyde_expansion_failed` exibe traceback longo** quando o LLM (Ollama
  ou cloud) está indisponível, antes da mensagem amigável de erro. É
  ruidoso mas não é um falha funcional — o `errors[]` do manifest captura
  corretamente.
- **Corpus ausente/vazio (Sprint 16, mitigado).** Caminho canônico é
  agora `~/.juris/repertory.db` (ou `JURIS_REPERTORY_PATH`). Em
  `--source datajud|mni`, `juris demo` aborta antes de gerar artefatos
  se o corpus não atinge `min_chunks`/`min_source_types`. Em
  `--source fixture` a saída roda normalmente, marcada DEMO. Validar
  com `juris repertory status` ou `juris pilot preflight` antes de
  qualquer sessão com caso real — ver §L1.
- **Modelo de embeddings baixa de HuggingFace na 1ª execução** (~400MB,
  warning sobre `HF_TOKEN` aparece). Pré-cachear antes da sessão.
- **`run-manifest.json` não inclui a si mesmo na lista de `artifacts`.**
  Por design — é o próprio manifest. Não é bug.
- **`MNI source ainda não implementado.`** Use `datajud` (pública) ou
  `fixture` (offline). Quando o token A3 entrar em rotação, o source
  `mni` será habilitado.

---

# 🟡 [NOTAS DA SESSÃO]

> Preencher durante e logo após a sessão. As seções abaixo viram input
> direto para a próxima iteração de Sprint.

## §6.1 Ambiente

- Data e hora: `____________`
- Advogado(a) parceiro(a): `OAB ____________`
- Tribunal/Caso: `____________`
- LLM usado (Ollama/cloud): `____________`
- Versão do juris (commit): `____________`

## §7 Erros e quedas

| Comando | Stage | Mensagem | Repete? |
| --- | --- | --- | --- |
|  |  |  |  |

## §8 Fricções de UX (CLI / artefatos)

1.
2.
3.

## §9 Qualidade da minuta (avaliação do(a) advogado(a))

- Estrutura: `(1–5)` — comentários:
- Argumentação: `(1–5)` — comentários:
- Citações verificadas: `(1–5)` — comentários:
- Tese inferida vs. desejada: `(1–5)` — comentários:
- Reviewer report: util? falsos positivos?
- O que o(a) advogado(a) reescreveria primeiro?

## §10 Prazos

- Algum prazo crítico **ausente**?
- Algum prazo **errado** (base legal, contagem)?

## §11 Auditoria

- `audit verify` passou? `[ ]` sim `[ ]` não
- Algum evento ausente que o(a) advogado(a) esperaria ver?

## §12 Decisão de fim de sessão

- [ ] Seguir para piloto pago (próxima sessão em até 7 dias)
- [ ] Pausar — ajustes obrigatórios primeiro (listar):
- [ ] Reduzir escopo — quais petições/áreas mantemos:
- [ ] Encerrar piloto

## §13 Backlog imediato

Itens novos descobertos na sessão (vão para o próximo Sprint):

1.
2.
3.

---

_Saída gerada com a colaboração do(a) advogado(a). A IA assiste; a
responsabilidade jurídica permanece exclusivamente com o(a)
profissional inscrito(a) na OAB._
