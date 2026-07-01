# Sprints de Engenharia — Próxima Sequência

**Atualizado:** 2026-06-30

Este plano registra a sequência operacional para transformar o Juris em produto
piloto confiável. A ordem é deliberada: fechar segurança/isolamento antes de
expandir corpus, protocolo e automação de IA por assinatura.

## Sprint 1 — Split-Trust na UI

**Status:** concluído no branch `feat/mni-mtls-token`.

Entregue:
- `/api/agent-mode` informa `remote` vs `inprocess`.
- UI de `connect` omite CPF/PIN em modo remoto.
- UI de novo caso só pede CPF para `source=mni` co-localizado.
- Falhas de agente/MNI no web demo viram erro controlado.

## Sprint 2 — Anti-Alucinação sem Falso Positivo

**Status:** concluído no branch `feat/mni-mtls-token`.

Entregue:
- Detecção de formatos reais de jurisprudência crua (`REsp n.`, `AREsp`,
  `Tema Repetitivo`, `Súmula Vinculante`, `IRDR`, `IAC`).
- Siglas ambíguas (`MS`, `HC`, `AI`, `RE`) exigem número qualificado para não
  bloquear texto comum como `MS 365`.
- `grounding` aparece no manifest, CLI, artefato e web console.

## Sprint 3 — Hardening Multi-Tenant de Produção

**Status:** em andamento.

Fatia entregue agora:
- `/api/agent-health` expõe readiness por tenant: binding configurado,
  alcançabilidade, token conectado, validade do certificado e versão, sem
  retornar segredo de pareamento.
- A UI mostra o estado do agente remoto na área de conexão.
- `JURIS_REQUIRE_TENANTS=1` tem preflight de startup: sem tenants configurados
  ou sem binding de agente por tenant em modo remoto, o processo falha fechado.
- Rate limit process-local por API key protege `/api/*` contra rajadas básicas.
- Erros de autenticação/rate limit/readiness de agente retornam códigos
  estruturados para a UI e operação.
- Testes cobrem isolamento de connect job, output de demo e audit root entre
  tenants configurados.

Próximas entregas:
- Exibir status consolidado por escritório em uma tela administrativa.
- Persistir eventos de erro operacional para suporte do piloto.
- Se houver múltiplos workers, mover rate limit para reverse proxy/Redis.

## Sprint 4 — Console de Rotina do Advogado

**Status:** em andamento.

Objetivo:
- Transformar o web console em mesa diária: prazos críticos, novas movimentações,
  casos prontos para rascunho, casos bloqueados e últimos artefatos.

Fatia entregue agora:
- A primeira tela do console virou `Mesa de trabalho`.
- `/api/workbench` agrega prazos críticos, processos com sync recente, processos
  prontos para rascunho, bloqueios de grounding e artefatos recentes.
- Bloqueios e artefatos recentes são recuperados de `run-manifest.json` no
  diretório do tenant, sobrevivendo a refresh/nova sessão.
- Ações rápidas: abrir detalhe, gerar minuta, abrir auditoria e copiar caminho
  do artefato.
- Filas de prazo/processo mostram indicadores do último run por caso: fonte,
  grounding e contagem de review.
- Acervo e Agenda têm filtro local e ordenação básica para volume real de
  processos/prazos.
- O frontend aceita erros estruturados da API sem mostrar `[object Object]`.

Próximas entregas:
- Evoluir filtros para backend/paginação quando houver volume acima de piloto.

## Sprint 5 — Piloto Real Instrumentado

**Status:** em andamento.

Objetivo:
- Medir valor em 5 a 10 casos reais: tempo economizado, modo usado, citações
  aceitas/rejeitadas, lacunas de corpus e utilidade percebida.

Fatia entregue agora:
- Aba `Piloto` no console para registrar feedback por caso.
- `/api/pilot-feedback` grava JSONL por tenant com: tempo economizado, modo
  usado, citações aceitas/rejeitadas, fonte faltante, erro de prazo/análise,
  utilidade percebida, notas e flag de aproveitamento para corpus.
- Exportação `/api/pilot-feedback/export?format=json|csv`.
- `/api/pilot-feedback/summary` agrega casos avaliados, tempo economizado,
  utilidade média, aceitação de citações, lacunas priorizadas e candidatos de
  corpus; a aba `Piloto` mostra esse resumo.
- Exportação Markdown (`format=md`) gera relatório do piloto para decisão
  comercial e priorização de corpus.
- CLI `juris pilot summary` / `juris pilot report -o piloto.md` gera as métricas e o
  relatório (evidência + backlog priorizado) sem a web.

Próxima entrega (HUMANA, não código — a instrumentação acima está pronta e testada):
- Rodar 5-10 casos reais com o advogado (exige e-CPF A3 + backend LLM) e alimentar o
  feedback estruturado → então `juris pilot report`. Passo a passo em
  **`docs/pilot_runbook.md`**. Sem casos reais não há evidência de valor pago; nenhum
  código substitui esse passo.

## Sprint 6 — Corpus Dirigido pelo Piloto

**Status:** em andamento.

Objetivo:
- Transformar lacunas reais do piloto em fontes aceitas, rastreáveis e prontas
  para reingestão controlada.

Fatia entregue agora:
- `/api/corpus/candidates` lista casos do feedback marcados como aproveitáveis
  para corpus.
- `/api/corpus/sources` registra fonte aceita com proveniência obrigatória:
  URL, data, tipo, tribunal, área, tema, status e `content_sha256` ou texto
  fonte para cálculo de hash.
- `/api/corpus/coverage` reporta cobertura por área, tema, tribunal, tipo e
  status, além de candidatos pendentes e fila de reingestão.
- `/api/corpus/sources/{id}/reingested` marca uma fonte como reingerida após o
  job controlado.
- A aba `Piloto` mostra fila de corpus, fontes aceitas e pendências de
  reingestão.
- `/api/corpus/reingest` executa reingestão real das fontes pendentes no
  `repertory.db`, gerando chunks com proveniência (`source_url`, `source_date`,
  `content_sha256`, área, tema e tribunal) e só marca `done` após upsert.
- `/api/pilot-feedback/comparison` compara primeira e última avaliação do mesmo
  CNJ: delta de tempo economizado, utilidade e aceitação de citações.
- A aba `Piloto` mostra a seção `Segunda execução dos casos`.

Próximas entregas:
- Rodar casos reais suficientes para popular a comparação com evidência.
- Usar os deltas da segunda execução para priorizar corpus vs UX vs estratégia.

## Sprint 7 — Qualidade de Minuta e Estratégia

**Status:** entregue em fatia operacional.

Objetivo:
- Ajudar o advogado a decidir estratégia antes da minuta e reduzir risco de
  tese sem lastro.

Entregas:
- `EstrategiaAgent` mantém matriz probatória e classificação do caso no
  relatório estruturado.
- O payload web expõe `classificacao`, `matriz_probatoria`, `lacunas_prova` e
  `tom_minuta`.
- A UI mostra o tom recomendado (`forte`, `cauteloso`, `rascunho`) e as lacunas
  de prova antes da minuta.
- O reviewer agora adiciona achados determinísticos para:
  - alegação sem prova indicada;
  - pedido sem fundamento explícito;
  - jurisprudência fraca/genérica ou não verificada;
  - risco de tese excessiva.

Critério atendido:
- Baixa confiança aparece como `rascunho`.
- Falhas jurídicas previsíveis são surfacadas sem depender exclusivamente do
  LLM.

Próximas entregas:
- Passar `tom_minuta` diretamente para o drafter quando houver ajuste de prompt
  do gerador final.
- Calibrar as heurísticas com feedback real do piloto para reduzir ruído.

## Sprint 8 — Assinatura e Protocolo Controlados

**Status:** entregue em fatia web segura.

Objetivo:
- Fechar o ciclo `minuta revisada -> protocolo` com preflight, consentimento e
  cadeia de custódia visíveis.

Entregas:
- Nova aba `Protocolo` no console.
- `/api/filing/status` lista filings pendentes e recibos recentes com hashes.
- `/api/filing/dry-run` executa render/preflight sem assinatura nem contato MNI.
- `/api/filing/submit` exige revisão humana confirmada e consentimento explícito
  antes de assinar/protocolar.
- `/api/filing/artifacts` lista minutas/rascunhos recentes e
  `/api/filing/artifacts/content` carrega o conteúdo com confinamento ao
  diretório do tenant.
- Em modo remoto, CPF/senha/PIN não são exigidos nem encaminhados; o agente local
  resolve segredos e retorna apenas metadados, recibo e hashes.
- A UI renderiza checklist de preflight, pendências recuperáveis, recibo e cadeia
  de custódia (`pdf_hash`, `signed_pdf_hash`, `submitted_payload_hash`,
  `receipt_hash`).
- A UI permite carregar uma minuta recente no formulário de protocolo sem colar
  Markdown manualmente.
- `/api/filing/pending/recovery` mostra plano de recuperação de `_pending`
  sem expor `signed.pdf`.
- `/api/filing/pending/archive` arquiva um pendente apenas com confirmação
  humana e justificativa, preservando os arquivos em diretório de resolução
  manual.

Critério atendido:
- Não há submit sem revisão e consentimento.
- O console mostra recibo/hashes quando o protocolo retorna cadeia de custódia.
- O fluxo remoto mantém PDF/recibo sensíveis no agente conforme a fronteira
  split-trust.

Próximas entregas:
- ~~Amarrar o protocolo diretamente à página do caso/processo selecionado.~~ **Feito**
  (detalhe do caso → seção Protocolo + retomar filing pendente por caso).
- Só considerar retry automático de `_pending` depois de desenhar salvaguarda
  contra protocolo duplicado. **(pendente — ver Sprint 11 abaixo)**


## Estado atual (pós-hardening + auditoria adversária)

Entregues e testados (código): segurança da browser session (token validado no native
host, de-id imposta), health multi-tenant v2 (`/api/health?deep=1`, painel admin, cache),
guard fail-closed do relay + `JURIS_RELAY_STICKY`, rate-limit **Redis** distribuído
(`JURIS_RATE_LIMIT_REDIS_URL`), `tom_minuta` no prompt + mini-benchmark, busca de corpus
explicável + `juris repertory ingest-file`, harness `corpus_improvement`, UX de caso
(paginação/filtros persistentes/protocolo por caso), + correções da auditoria adversária
(vazamento de nomes p/ claude.ai no fallback local, CPF só-dígitos, bypasses do guard,
isolamento fail-safe do corpus, thread-safety do search cacheado).

Bloqueado por dependência humana: **evidência de piloto** (rodar casos com A3 — ver
`docs/pilot_runbook.md`) e **fonte real de inteiro teor** (decisão de ToS).

## Próxima sequência proposta

- **Sprint 8 — Broker de canal reverso.** Sticky routing já entregue; o broker Redis/NATS
  do relay é a alternativa para escala horizontal sem afinidade de LB. Roteia filing →
  exige teste de integração contra Redis real antes de produção (determinismo em caminho
  legal-crítico), não só double in-memory.
- **Sprint 9 — Zero-PII-to-cloud completo.** Fechar o loop do `JURIS_AGENT_DEID_READS`:
  render + re-id + sign no agente, para que a nuvem SaaS nunca veja nome/CPF cru.
- **Sprint 10 — Escopo de tenant no path denso (Qdrant).** O FTS é tenant-scoped; o denso
  não. Escopar por `tenant_id` antes de ativar o Qdrant.
- **Sprint 11 — Loop noturno automático.** Overnight sync agendado por tenant, entrega de
  alertas (email/WhatsApp) com dedupe, e retry de `_pending` **com salvaguarda
  anti-duplicata**.
- **Sprint 12 — Entendimento de documento.** Ler acórdão/decisão/intimação recebidos →
  fatos estruturados para análise, minuta e corpus.
