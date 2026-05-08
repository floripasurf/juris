# Onboarding — Piloto Juris

Checklist de pré-requisitos antes da sessão de smoke test (1h) com o(a)
advogado(a) parceiro(a). Prepare estes itens com antecedência — o objetivo
é que a sessão fique 100% focada no produto, não em configuração.

## 1. Credenciais e identidade

- [ ] **OAB do(a) advogado(a)** capturada (UF + número).
- [ ] **CPF do(a) advogado(a)** disponível (usado em comandos `--cpf`).
- [ ] **Token A3 (e-CPF)** físico em mãos, com PIN conhecido.
- [ ] **Senha PJe / portal do tribunal** ativa para o tribunal alvo.
- [ ] Termos do piloto (`docs/pilot/pilot-terms-pt.md`) **revisados e
  assinados** por ambas as partes antes do início.

## 2. Tribunal e MNI

- [ ] Tribunal alvo definido (`tjmg`, `tjsp`, `trf3`, ...).
  - Comando para listar disponíveis: `uv run juris tribunais`
- [ ] Cadastro MNI/PJe ativo do(a) advogado(a) no tribunal.
- [ ] Pelo menos **1 processo ativo** selecionado pelo(a) advogado(a):
  - Critérios sugeridos: rotineiro, baixo risco, com movimento recente.
  - Anote o **número CNJ completo** com pontuação (ex.:
    `5001234-56.2024.8.13.0024`).

## 3. Ambiente local

- [ ] Repositório `juris` clonado e atualizado:
  ```bash
  uv sync
  docker compose -f docker/docker-compose.yml up -d
  ```
- [ ] Variáveis de ambiente em `.env`:
  - `ANTHROPIC_API_KEY=` (se for usar `--cloud` para tarefas sem PII).
  - `DATAJUD_API_KEY=` (se a chave do CNJ for exigida).
- [ ] Ollama rodando localmente (`ollama serve`) caso o demo use LLM local.
- [ ] Repertório indexado: arquivo `data/repertory.db` presente; senão:
  ```bash
  uv run juris repertory ingest
  ```

## 4. Sessão de smoke test (1 hora)

Estrutura sugerida:

| Tempo | Atividade |
| ---: | --- |
| 0:00–0:05 | Revisão dos limites do piloto (§2 dos termos). |
| 0:05–0:15 | Demo em **modo fixture** para mostrar o pipeline sem pressão: `uv run juris demo 0000000-00.0000.0.00.0000 contestacao --source fixture` |
| 0:15–0:35 | Demo em modo real (DataJud) sobre o caso escolhido pelo(a) advogado(a). |
| 0:35–0:50 | Revisão conjunta de `draft.md`, `reviewer-report.md`, `prazos.md`. Capturar fricções em `docs/pilot/smoke-test-notes.md`. |
| 0:50–0:55 | Verificação de auditoria: `uv run juris audit verify <caso>/audit.jsonl` |
| 0:55–1:00 | Próximos passos, escolha do modelo de cobrança (§5 dos termos). |

## 5. Saída esperada

Ao final da sessão, o diretório `juris-out/<numero_cnj>/` deve conter:

- `draft.md` (com rodapé de IA)
- `draft.contraponto.md` (se houver)
- `reviewer-report.md`
- `prazos.md`
- `case-summary.md`
- `audit.jsonl`
- `audit-summary.md`
- `run-manifest.json`

A íntegra da cadeia de auditoria deve passar em `juris audit verify`.

## 6. Pós-sessão

- [ ] `docs/pilot/smoke-test-notes.md` preenchido com fricções, surpresas
  e backlog de melhorias.
- [ ] Decisão registrada: piloto pago segue ou pausa para correções?
- [ ] Próxima sessão agendada (idealmente em até 7 dias).
