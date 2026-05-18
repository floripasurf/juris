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

### L4 · DataJud é read-only, mas batch precisa de guarda operacional

`--source datajud` consulta a API Pública do CNJ. Para a smoke test com
**um único CNJ**, isso é apropriado: read-only, sem token A3, sem assinatura
e sem protocolo. Para qualquer telemetria com listas de CNJs, o Juris deve
respeitar a política em `docs/compliance/datajud-terms-snapshot-2026-05-09.md`:
rate limit default de `1 req/sec`, cache local, auditoria de cada chamada e
confirmação explícita para batches com `>=10` CNJs.

**Ação obrigatória do operador antes de batch DataJud:**

- Revalidar o snapshot de termos se a sessão não for no mesmo dia.
- Confirmar que `JURIS_DATAJUD_RATE_LIMIT_PER_SECOND` não está acima do
  limite operacional aprovado.
- Confirmar que o cache pode armazenar metadados processuais localmente sob
  LGPD; se não puder, rodar com `--no-cache` e purgar qualquer resíduo com:

```bash
uv run juris cache purge --datajud
```

---

## 0. Pré-flight (10 min antes da sessão)

Já tudo do `onboarding.md` está pronto. Esta lista cobre o que é
delicado nos minutos imediatamente antes da sessão.

**Único comando obrigatório:**

```bash
uv run juris pilot preflight --out juris-out --fixture-only --skip-ollama-probe --cli-cloud claude
```

`Preflight OK (com avisos)` → seguir para fixture sem PII. Qualquer `FAIL`
→ abortar e remediar. `WARN` sobre Ollama indisponível é aceitável nesta
rota, porque a primeira sessão não usa PII real nem depende de Ollama.

Checks cobertos automaticamente: corpus pronto (§L1), modelo de embeddings
em cache, CLI cloud disponível para a fixture, diretório de saída sem runs
anteriores (§L3), espaço em disco. Saída em `--json` para automação.

**Itens manuais que o pré-flight não cobre** (físicos / em papel):

- [ ] Token A3 conectado e PIN testado num site qualquer da Receita.
- [ ] CNJ do caso real anotado **com pontuação** (`NNNNNNN-DD.AAAA.J.TT.OOOO`).
- [ ] Termos do piloto assinados (PDF arquivado).

---

## 1. Estrutura da sessão (1h)

| Tempo | Atividade | Comando / artefato |
| ---: | --- | --- |
| 0:00–0:03 | Boas-vindas, recapitular limites do piloto §2 | `pilot-terms-pt.md` |
| 0:03–0:25 | Demo em **modo fixture** (offline, dados sintéticos, cloud CLI sem PII) | ver §2 |
| 0:25–0:35 | Discutir o caso real de Raphael sem inserir PII no LLM | ver §3 |
| 0:35–0:50 | Leitura conjunta dos artefatos | §4 + `[NOTAS]` |
| 0:50–0:55 | Verificação da auditoria | `juris audit verify` |
| 0:55–1:00 | Decisão: seguir, pausar, ajustar escopo | `[NOTAS] §10` |

---

## 1.1. Escolha do modo de saída (`--modo`)

A partir do Sprint 17 o `juris demo` aceita dois modos de saída,
**escolhidos manualmente pelo operador antes da execução**. O modo afeta o
artefato principal entregue ao(à) advogado(a) — todos os demais artefatos
(prazos, reviewer report, audit, manifest) são produzidos igualmente.

| Modo | Flag | Artefato principal | Quando usar |
| --- | --- | --- | --- |
| **MINUTA SUGERIDA** (default) | `--modo minuta-sugerida` (ou omitir) | `draft.md` — minuta de petição com banner de revisão obrigatória | Caso de área/peça em que o repertório tem cobertura razoável e o(a) advogado(a) confia que conseguirá revisar e adaptar a peça |
| **RASCUNHO DE PESQUISA** | `--modo rascunho-pesquisa` | `rascunho-pesquisa.md` — memorando estruturado (análise + argumentos + riscos + esqueleto), **sem prosa de petição** | Caso atípico, área pouco coberta no repertório, ou quando o(a) advogado(a) prefere começar a redação manualmente com um memorando de apoio |

**Regra prática para a primeira sessão:**

> Pergunte ao(à) advogado(a): _"se eu te mostrar uma minuta agora, você
> conseguiria revisá-la com confiança em 15 minutos?"_ Se a resposta for
> hesitante, comece em `--modo rascunho-pesquisa`. Não use o modo MINUTA
> SUGERIDA como prova de capacidade do produto — use-o como ferramenta
> útil quando faz sentido.

**Por que dois modos:** quando o suporte do corpus e dos templates é
fraco, uma minuta com aviso ainda **parece** uma peça pronta. O
`RASCUNHO DE PESQUISA` codifica a limitação no próprio artefato (nome de
arquivo distinto, banner explícito, sem prosa de petição) — o(a)
advogado(a) **não** corre o risco de tratar o memorando como peça
fileável. Codex Sprint 17 ruling: nenhuma pontuação numérica de
"prontidão" automatizada nesta versão; a calibração começa pelos dados
da primeira sessão real.

---

## 2. Demo em modo fixture (3–5 min)

Objetivo: mostrar pipeline funcionando **sem expor dados reais**, validar
que o ambiente do(a) parceiro(a) está OK.

```bash
uv run juris demo 0000000-00.0000.0.00.0000 contestacao \
  --source fixture \
  --modo rascunho-pesquisa \
  --cli-cloud claude
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

## 3. Caso real: gate de PII e qualidade (10 min)

Objetivo: escolher o primeiro caso real sem quebrar o limite de PII. A
decisão de Raphael nesta sessão foi clara: Ollama local é fraco demais para
informações jurídicas complexas. Portanto, o piloto não deve tratar "rodar
local no Ollama" como caminho viável para caso real.

**Matriz operacional atual:**

| Contexto | Rota permitida agora | Observação |
| --- | --- | --- |
| Fixture sintética | `--source fixture --modo rascunho-pesquisa --cli-cloud claude|codex` | Rota principal do smoke com Raphael. |
| Caso real anonimizado/sem PII | `--source datajud --cloud --modo rascunho-pesquisa` | Só com confirmação explícita do(a) advogado(a). |
| Caso real com PII | **bloqueado** | Requer anonimização/consentimento/rota cloud aprovada ou backend local mais forte. |
| Minuta protocolável | **fora do smoke inicial** | Primeiro validar memorando, citações, auditoria e UX. |

Se o caso real estiver apto para uso sem PII, o comando base é:

```bash
# Modo RASCUNHO DE PESQUISA — produz rascunho-pesquisa.md (memo)
uv run juris demo \
  <NUMERO_CNJ_REAL> contestacao \
  --tribunal tjmg \
  --thesis "<tese sugerida pelo(a) advogado(a) ou deixe em branco>" \
  --cloud \
  --modo rascunho-pesquisa
```

**Recomendações:**

- Use `--source datajud` apenas para caso real sem PII no contexto enviado ao
  LLM. Isso faz consulta pública read-only ao CNJ. Use `--no-cache` se o
  operador não puder manter resposta DataJud em disco local.
- Não cair para Ollama local em caso complexo. Se houver PII, parar e
  registrar o bloqueio em `[NOTAS] §13`.
- Defina `--thesis` **somente** se o(a) advogado(a) quiser fixar a tese.
  Sem `--thesis`, o drafter infere via LLM.
- `--modo` deve corresponder à decisão tomada em §1.1. O CLI confirma o
  modo escolhido em uma linha logo após o `Demo:` inicial — **conferir
  antes de aguardar o pipeline**.
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
3. **Artefato principal — depende do modo escolhido em §1.1:**
   - **MINUTA SUGERIDA → `draft.md`** — minuta principal. Leia em
     silêncio durante 5 min, depois discuta:
     - Estrutura está aceitável?
     - Citações estão verificadas (ver `reviewer-report.md`)?
     - Tese é adequada ao caso?
     - O que o(a) advogado(a) reescreveria? **Capturar como fricções.**
   - **RASCUNHO DE PESQUISA → `rascunho-pesquisa.md`** — memorando.
     Não pergunte _"você assinaria essa minuta após editar?"_ — esse não
     é o teste correto para este modo. Em vez disso:
     - A análise jurídica acerta o foco do caso?
     - Os argumentos sugeridos (com `[CITE:...]`) são úteis como ponto
       de partida?
     - Os riscos/contraponto antecipam o que a parte adversa
       argumentaria?
     - O esqueleto sugerido reflete a estrutura que o(a) advogado(a)
       usaria? **Capturar fricções específicas do memorando, não da
       prosa.**
4. **`draft.contraponto.md`** (apenas em modo MINUTA, quando gerado) —
   argumentos contrários previstos. Útil ou ruído?
5. **`reviewer-report.md`** — severidade dos achados do revisor. Falsos
   positivos? Pontos legítimos perdidos pelo drafter?

**Não tente "polir" a minuta/memorando na sessão.** O ciclo é: gerar →
ler → listar fricções → ajustar prompts/templates fora da sessão.

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
- **DataJud batch não é parte desta smoke test.** Um CNJ real via
  `--source datajud` é consulta pública read-only. Listas de CNJs entram em
  Sprint posterior e exigem confirmação explícita, rate limit, cache/auditoria
  e leitura do snapshot em `docs/compliance/datajud-terms-snapshot-2026-05-09.md`.

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
