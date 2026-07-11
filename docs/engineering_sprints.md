# Sprints de Engenharia — Próxima Sequência

**Atualizado:** 2026-07-01

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

**Status:** instrumentação concluída; validação comercial bloqueada pelo gate de casos reais.

Fatia entregue agora:
- `/api/agent-health` expõe readiness por tenant: binding configurado,
  alcançabilidade, token conectado, validade do certificado e versão, sem
  retornar segredo de pareamento.
- A UI mostra o estado do agente remoto na área de conexão.
- `JURIS_REQUIRE_TENANTS=1` tem preflight de startup: sem tenants configurados
  ou sem binding de agente por tenant em modo remoto, o processo falha fechado.
- Rate limit por API key protege `/api/*`; o handshake de `/ws/agent-relay` tem
  bucket proprio por tenant/IP. Em single-worker usa contador local e, quando
  `JURIS_RATE_LIMIT_REDIS_URL` esta definido, usa Redis compartilhado para
  multi-worker.
- Erros de autenticação/rate limit/readiness de agente retornam códigos
  estruturados para a UI e operação.
- Testes cobrem isolamento de connect job, output de demo e audit root entre
  tenants configurados.
- `/api/health?deep=1` faz probe real de agente/browser bridge; `/api/admin/health`
  consolida status por escritório.
- O canal reverso falha fechado em multi-worker sem `JURIS_RELAY_BROKER` ou
  `JURIS_RELAY_STICKY=1`.

Próximas entregas:
- Persistir eventos de erro operacional para suporte do piloto.
- Substituir sticky routing por broker Redis/NATS se o deploy precisar escalar sem
  afinidade de load balancer.

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
- CLI `juris pilot gate` falha até existirem pelo menos 5 CNJs reais distintos no
  feedback do piloto (meta recomendada: 10). Esse é o gate operacional para
  afirmar valor pago; sem ele, o produto segue como piloto não validado.

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
- Calibrar as heurísticas e o `tom_minuta` com feedback real do piloto para reduzir
  ruído e excesso de cautela.

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
(`JURIS_RATE_LIMIT_REDIS_URL`) com buckets separados para rotas comuns, caras e
handshake do relay,
`tom_minuta` no prompt + mini-benchmark, busca de corpus
explicável + `juris repertory ingest-file`, harness `corpus_improvement`, UX de caso
(paginação/filtros persistentes/protocolo por caso), + correções da auditoria adversária
(vazamento de nomes p/ claude.ai no fallback local, CPF só-dígitos, bypasses do guard,
isolamento fail-safe do corpus, thread-safety do search cacheado), de-id com checksum
para CPF/CNPJ/CNJ crus, `juris overnight --send-alerts` com SMTP e template launchd,
backup explícito do engine local gitignored, e `to_thread` nos caminhos web/sync
mais bloqueantes; `DeidentifyingLLM` agora falha fechado por padrão e exige opt-in
explícito para de-id parcial; `ENVIRONMENT=prod` agora força tenants configurados
mesmo sem `JURIS_REQUIRE_TENANTS`, e o transporte MNI PKCS#11 valida certificado
do servidor com `-verify_return_error` + `-verify_hostname`; `audit.jsonl` pode
ser ancorado com HMAC (`JURIS_AUDIT_HMAC_KEY`) e `doctor` cobra essa chave em
produção; `juris backup create/restore` agora cobre `JURIS_HOME`, `JURIS_OUT_ROOT`,
`repertory.db`, audit logs e recibos com manifesto e SHA-256 por arquivo; e
`juris tenant erase-data` implementa deleção LGPD/piloto por tenant com dry-run,
confirmação explícita, limpeza de connect jobs/chunks privados e certificado em
`compliance-erasure.jsonl`; e o CI agora tem `mypy src/juris` como hard gate,
cobertura unitária com baseline real de 72%, scanner de segredos de alto risco,
`pip-audit --local --strict`, `uv sync --frozen`, `npm ci` sem fallback e
`BLE001` ativo no Ruff para impedir novo `except Exception` sem justificativa. A
sanitização compartilhada de diagnósticos agora reaproveita o detector estruturado
do de-id para redigir CPF/CNPJ/CNJ/OAB/RG/CEP/e-mail/telefone/datas em logs, e os
knobs web `JURIS_API_RATE_LIMIT_PER_MINUTE`, `JURIS_RATE_LIMIT_REDIS_URL`,
`JURIS_API_EXPENSIVE_RATE_LIMIT_PER_MINUTE`,
`JURIS_WS_AGENT_RELAY_RATE_LIMIT_PER_MINUTE` e `JURIS_CONNECT_TIMEOUT_SECONDS`
passaram a fazer parte do `Settings` validado; o pacote LGPD/compliance minimo
agora existe em `docs/compliance/` (DPA, ROPA, RIPD) e o log de liberacao de
fontes/ToS em `data/tos_compliance_log.md` deixa ingesters de inteiro teor
explicitamente bloqueados ate aprovacao por fonte; o fetcher TST agora usa o
backend JSON real (`pesquisa-textual`) em vez da URL SPA com `#/`, mas permanece
gated por `JURIS_TST_INTEIRO_TEOR_ENABLED` ate aprovacao de ToS. A cadeia web
`minuta gerada -> carregar artefato -> dry-run -> revisão/consentimento -> submit`
agora tem teste de costura unitario, cobrindo o ponto em que o console transforma
artefato revisado em protocolo controlado sem acionar tribunal real; no modo
split-trust com `JURIS_AGENT_DEID_READS=1`, o filing remoto mantém o markdown
de-identificado no wire e reidentifica o rascunho apenas no agente local antes de
renderizar/assinar/protocolar; o canal reverso agora tem broker Redis opcional
(`JURIS_RELAY_BROKER`) com roteamento request/reply por tenant e dedupe de
`request_id` pendente, permitindo que uma requisição recebida em um worker alcance
o agente conectado em outro; filings `_pending` agora carregam metadados de
recuperação e têm retry controlado do submit já assinado, com confirmação humana
de inexistência de protocolo, `retry.json` com idempotency key e bloqueio de nova
tentativa quando o resultado fica indeterminado; os catálogos de defesas CPC/CPP/CLT agora têm
registry (`defesas/registry.py`) e entram no `DefesaAnalyzer`, que registra o
código/institutos consultados no relatório em vez de deixar esses arquivos como
referência órfã. A SPA agora tem gate de login: `apiFetch` anexa `X-API-Key`
(sessionStorage) em toda chamada `/api/*`, 401 reabre o login e o console passa
a funcionar em modo prod com tenants exigidos — pré-requisito do endereço de
teste `juris.blackcube.dev` (runbook em `docs/deploy/blackcube-pilot.md`,
launchd em `docs/deploy/com.juris.web.plist`). Biblioteca do Escritório (Fase 1,
2026-07-06): tier-3 com eixo uso fundamento/estilo, guarda determinística no
retrieval+verifier, upload em lote (.pdf/.docx/.txt/.md), exemplar de estilo do
próprio escritório no drafter e aba Biblioteca no console. Spec em
`docs/superpowers/specs/2026-07-06-biblioteca-escritorio-design.md`. Fechamento
(L6): `juris tenant erase-data` também revoga a entrada do tenant em
`JURIS_TENANTS_FILE` — a chave antiga passa a ser rejeitada (401) em vez de
autenticar num tenant já esvaziado (`access_revoked` no certificado de erasure).

Bloqueado por dependência humana: **evidência de piloto** (rodar casos com A3 e
passar `juris pilot gate` — ver `docs/pilot_runbook.md`) e **fonte real de inteiro
teor** (decisão de ToS).

**Consolidação de Git (2026-07-05):** criado o branch `main` a partir de
`feat/mni-mtls-token` e tornado o default do repositório (o antigo default
`feat/sprint-14-unified-search` estava ~297 commits atrás). Os PRs #3 e #7 foram
fechados após integração/consolidação. Todo branch antigo foi preservado como tag
`archive/*` antes de remoção.

**Decisão (2026-07-05) — adapter CLI-cloud (PRs #2/#6):** o adapter de LLM via
CLI de assinatura (Haiku sem API key) que vivia em `feat/cli-cloud-haiku` /
`feat/llm-cli-cloud-adapter` **não foi portado** para `main`: o caminho de nuvem
por assinatura foi superado pela sessão de browser do provedor (ADR-0018,
`llm/browser_session.py`), e os seeds de corpus daqueles branches já existem em
`data/corpus/` (súmulas/OJs TST, temas de repercussão geral do STF). Os branches
ficam arquivados como tags `archive/*`; se a demanda "Haiku por assinatura via
CLI" voltar, partir do ADR-0018, não do branch antigo.

## Próxima sequência proposta

- **Sprint 8 — Broker de canal reverso.** Entregue em código com Redis pub/sub:
  worker com agente assina o canal do tenant, qualquer worker publica a operação e
  aguarda reply correlacionado; `SET NX` dedupe protege `request_id` pendente.
  **Concluído (2026-07-05):** smoke real automatizado em
  `scripts/smoke_relay_broker.py` (Redis 7 + dois `RelayHub`/workers) prova
  roteamento cross-worker + dedupe de `request_id`; runbook em `docs/deployment.md`.
- **Sprint 9 — Zero-PII-to-cloud completo.** Entregue em fatia técnica: o
  `RemoteFilingService` envia markdown de-identificado e sem mapa de re-id; o
  agente carrega o mapa local por tenant/CNJ e restaura o rascunho apenas antes
  de render + sign + file. Falta validar o fluxo contra um agente real com A3 no
  piloto operacional.
- **Sprint 10 — Escopo de tenant no path denso (Qdrant).** Implementado no contrato
  `VectorStore`, no `QdrantVectorStore` e no `HybridRetriever`: busca densa recebe
  `tenant_id` e filtra seed público + corpus privado do próprio tenant. Antes de ativar
  Qdrant em produção, reingerir pontos legados sem marcador de tenant; eles falham
  fechado e não aparecem na busca nova.
- **Sprint 11 — Loop noturno v2.** O job local básico (launchd + email) já existe;
  dedupe de alertas por prazo/canal foi adicionado com ledger local (`sent_alerts`) e
  a mesa de trabalho expõe `sync_status` com última execução, contadores e falhas
  recentes. Retry de `_pending` com salvaguarda anti-duplicata foi entregue no console:
  reenvio só com confirmação humana de que não há protocolo existente; erro de submissão
  marca o estado como indeterminado e bloqueia nova tentativa automática. A CLI agora
  tem `juris overnight --all-tenants`, que percorre cada tenant configurado, usa o
  banco/ledger isolado do escritório e roteia leitura MNI pelo agente remoto daquele
  tenant. Falta WhatsApp opcional e smoke operacional com tenants reais/Redis antes
  de tratar como rotina SaaS de produção.
- **Sprint 12 — Entendimento de documento.** Ler acórdão/decisão/intimação recebidos →
  fatos estruturados para análise, minuta e corpus.
