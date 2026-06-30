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

Próximas entregas:
- Rodar 5-10 casos reais com o advogado e alimentar o feedback estruturado.
