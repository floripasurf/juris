# Spike — Descoberta e Importação de Processos

**Data:** 2026-06-24 · **Status:** investigação (não-código)

## Requisito (visão SaaS)

Na **1ª conexão** do token, importar **todo o acervo** do advogado para a conta.
Nas conexões seguintes, buscar **apenas** processos novos ou andamentos posteriores
ao último carregamento (incremental).

## Achado central: enumerar o acervo é o gargalo

O **MNI é por-CNJ** — `consultarProcesso(numeroProcesso)`. **Não existe** operação
MNI de "listar os processos do advogado" (verificado: só `consultarProcesso`,
`consultarAvisosPendentes`, `consultarTeorComunicacao`). Logo, para a 1ª importação
é preciso descobrir a lista de CNJs por outra via.

### Panorama das fontes de descoberta (por sistema do tribunal)

| Fonte | Enumera acervo por OAB? | Cobertura | Estado no código |
|---|---|---|---|
| **eSAJ** (`busca/consulta_publica.py`, code `NUMOAB`) | ✅ sim | TJSP, TJMS, TJAL, TJCE, TJAM, TJAC | implementado em `busca/channels/esaj.py` (carece de validação live + risco de captcha) |
| **DataJud** (API pública CNJ) | ❌ não indexa OAB/parte | todos | canal existe, `search_by_oab` retorna vazio por design |
| **PJe Consulta Pública** | ❌ captcha | TJMG e PJe em geral | inviável automatizar (regra do projeto: não burlar captcha) |
| **MNI `avisos`** (token) | parcial (só com intimação pendente) | qualquer tribunal MNI | ✅ validado live; `juris avisos --track` já popula a lista de rastreados |

**Consequência para o TJMG (o tribunal do piloto, PJe):** não há enumeração pública
automática do acervo completo. As vias reais são `avisos` (subconjunto com prazo
aberto) e/ou **seed manual** (lista de CNJs fornecida pelo advogado / importada do
sistema dele). eSAJ-OAB só ajuda em tribunais da família eSAJ.

## O que já está pronto (reutilizável)

- **Incremental / diferencial:** `LocalDB.get_last_sync` + `get_known_movimento_keys`
  + `mni/operations/differential.py` + `jobs/overnight.py` — busca e detecta só os
  movimentos novos por processo. **Esta é a metade "só o que mudou" do requisito, e está construída.**
- **Lista de processos rastreados:** `juris track` / `tracked` / `untrack`
  (`_get_tracked_processos`, hoje em Keychain). É o registro "meus processos".
- **Seed por avisos:** `juris avisos --track` liga intimação pendente → lista rastreada.
- **Enriquecimento por-CNJ:** `consultarProcesso` (MNI/token) e DataJud para detalhes.

## O que falta / está bloqueado

- **Enumeração do acervo PJe completo:** sem via pública/MNI. Bloqueado por design.
- **Armazenamento por-conta (multi-tenant):** `LocalDB` é single-user (sem `tenant_id`).
  Trabalho de Fase 2 (ver ADR-0015).
- **Validação live do eSAJ-OAB:** o canal existe mas precisa de probe real (e pode ter
  captcha) — relevante só para tribunais eSAJ, não para o TJMG do piloto.

## Modelo recomendado (mapeado no que existe)

**Descoberta em camadas, por sistema do tribunal:**
1. Tribunais **eSAJ** → enumerar por OAB via `busca/` (validar live; degradar se captcha).
2. Tribunais **PJe (TJMG)** → `avisos --track` (prazos abertos) **+ seed import** (o advogado
   cola/importa a lista de CNJs). Honesto: a "importação total automática" no PJe depende de seed.
3. **DataJud** → só enriquecimento por-CNJ, nunca descoberta.

**Importação na 1ª conexão:** rodar a descoberta → popular o conjunto rastreado → fetch
inicial completo (`consultarProcesso` por CNJ) → persistir processo + movimentos + `log_sync`.

**Conexões seguintes (incremental):** para cada rastreado, o **diferencial existente**
(last-sync + known-movimentos) traz só os andamentos novos; e um **delta de descoberta**
(re-rodar enumeração / `avisos`) adiciona CNJs novos que surgiram desde o último load.

## Recomendação de próximo passo

Para o piloto (TJMG/PJe), o caminho de maior valor e menor risco é:
**(1)** consolidar `avisos --track` + o diferencial como o ciclo "conectou → importa o que
tem prazo + atualiza o conhecido", e **(2)** adicionar um **seed import** (lista de CNJs do
advogado) para o acervo histórico que não tem intimação pendente. eSAJ-OAB e a enumeração
multi-tribunal entram quando houver tenant eSAJ. O "import-once + incremental" então é:
seed (avisos+lista) na 1ª vez, diferencial dali em diante.
