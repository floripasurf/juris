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
  - `ANTHROPIC_API_KEY=` (opcional — só para o caminho de API sem PII).
  - `DATAJUD_API_KEY=` (se a chave do CNJ for exigida).
- [ ] Ollama rodando localmente (`ollama serve`) como **fallback** — o modelo de
  fronteira vem da sessão de IA do(a) advogado(a) (ver §3.5).
- [ ] Repertório indexado: arquivo `data/repertory.db` presente; senão:
  ```bash
  uv run juris repertory ingest
  ```

## 3.5 Sessão de IA (modelo de fronteira via assinatura)

O juris usa a **assinatura de IA do(a) próprio(a) advogado(a)** (Claude ou
ChatGPT) através de uma extensão de navegador na máquina dele(a) — o modelo de
fronteira faz a análise/estratégia/minuta, e a sessão **nunca sai do perímetro
do(a) advogado(a)** (ADR-0018). Passo a passo, **na ordem**:

- [ ] **Assinatura paga ativa**: Claude (Pro/Max) **ou** ChatGPT (Plus/Pro).
  O plano que o(a) advogado(a) já usa serve — sem custo adicional de API.

- [ ] **⚠️ DESLIGAR o treino / coleta de dados** (passo crítico — sigilo da OAB +
  LGPD: o conteúdo do processo **não pode** treinar o modelo de um terceiro):
  - **Claude.ai:** *Configurações → Privacidade* → desligue a opção de **ajudar a
    melhorar o Claude** / uso de conversas para treino.
  - **ChatGPT:** *Configurações → Controles de dados (Data Controls)* → **"Melhorar
    o modelo para todos" = DESLIGADO**.
  - Os rótulos exatos mudam com o tempo — confirme que **nenhuma** opção de uso de
    dados para treinamento esteja ativa. Em caso de dúvida, use também o modo de
    chat temporário/não salvo.
  - *Defesa em profundidade:* mesmo com o treino desligado, o juris **de-identifica**
    o que sai para a sessão e re-identifica a resposta — **identificadores estruturados**
    (CPF/CNPJ/CNJ/OAB) por regex e **nomes** via NER LeNER-Br.
  - **Pré-baixar o modelo NER** (uma vez, para o caminho cloud/sessão):
    `uv run python -c "from juris.core.ner import LegalNER; LegalNER().redact_entities('teste')"`.
    Sem o modelo, o caminho cloud **falha fechado** (não envia nomes) — é o
    comportamento seguro do ADR-0016.

- [ ] **Instalar a extensão juris + o host de mensagens nativas** e autorizá-la no
  navegador. *(Status: a cola de extensão/host está em construção — o lado juris
  do bridge já está pronto; ver `docs/design_browser_bridge.md`.)*

- [ ] **Logar no Claude.ai / ChatGPT** na mesma janela do navegador e deixar a aba
  aberta (a extensão usa a sessão autenticada).

- [ ] **Conectar e verificar**: o agente local detecta a sessão; faça um prompt de
  teste curto e confirme que a resposta volta ao juris. Se a sessão falhar (não
  logado, layout mudou, timeout), o juris **cai no modelo local** e avisa.

> **Escopo:** para o uso do **próprio escritório** este caminho é apropriado. Para
> revenda multi-tenant, revisitar os termos de uso do provedor e a base de DPA
> (ADR-0018).

## 4. Sessão de smoke test (1 hora)

### Sequência de comandos (no Mac Mini, com o token conectado)

```bash
# 0. Atualize a cópia local (a do Mac Mini pode estar atrás)
git fetch && git pull && uv sync

# 1. Pré-voo ÚNICO — token A3 + corpus + embeddings + Ollama num comando.
#    --live também valida o certificado do token (sem PIN). Qualquer FAIL aborta.
uv run juris pilot preflight --live

# 2. Primeira conexão: importa o acervo (avisos + seed) e calcula prazos.
uv run juris connect --cpf <CPF> --file acervo.txt   # nas próximas vezes: só o diferencial

# 3. Lê o processo, analisa, e gera a minuta com a linha estratégica selecionada.
uv run juris demo <NUMERO_CNJ> contestacao --source mni

# 4. Verifica a íntegra da cadeia de auditoria.
uv run juris audit verify juris-out/<NUMERO_CNJ>/audit.jsonl
```

> Se o `preflight --live` acusar **token_a3 FAIL**, o token não está conectado ou
> o certificado expirou — resolva antes de seguir. **Ollama indisponível** é WARN
> (cai no fallback); na arquitetura nova, o modelo de fronteira vem da §3.5.

### Estrutura sugerida

| Tempo | Atividade |
| ---: | --- |
| 0:00–0:05 | Revisão dos limites do piloto (§2 dos termos) + `juris pilot preflight --live`. |
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
