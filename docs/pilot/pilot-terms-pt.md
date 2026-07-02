# Termos do Piloto — Juris (Assistência Jurídica por IA)

**Versão:** 1.0 — _Sprint 15 Demo Milestone_
**Vigência:** A partir da assinatura, pelo período do piloto

Este documento estabelece as condições de uso do sistema **Juris** durante o
piloto inicial entre o(a) advogado(a) signatário(a) e a equipe de
desenvolvimento da Juris. Define limites, responsabilidades e práticas de
proteção de dados, com base em parâmetros de uso responsável de IA jurídica
e na legislação brasileira aplicável (LGPD, CPC, Estatuto da OAB).

---

## 1. Natureza da ferramenta

A Juris é um **sistema de IA assistiva** voltado a profissionais inscritos(as)
na OAB. **Não é** software de aconselhamento jurídico ao público leigo. A
ferramenta opera em quatro frentes:

- Leitura nightly de movimentações via MNI (CNJ).
- Análise classificada de movimentos e cálculo determinístico de prazos.
- Pesquisa em corpus de jurisprudência pública e doutrina indexada.
- Geração de minutas de petição com citações verificadas e revisor de
  pré-protocolo.

Toda a geração textual passa por verificação de citações marcadas e
revisão estruturada, mas **nenhuma saída é definitiva**: sempre demanda
revisão e validação humana qualificada antes de qualquer uso processual.

---

## 2. Os quatro limites do piloto

Estes limites se aplicam em qualquer uso da Juris e prevalecem sobre quaisquer
defaults da ferramenta. Eles representam o núcleo da política de uso
responsável durante o piloto.

### 2.1. A IA assiste — o(a) advogado(a) responde

A IA produz minutas, análises e cálculos como insumo. **A
responsabilidade técnica, ética e processual sobre qualquer documento
permanece exclusivamente com o(a) advogado(a) inscrito(a) na OAB** que
revisar, assinar ou protocolar a peça. Em nenhuma hipótese a Juris substitui
a atuação profissional ou o juízo do(a) advogado(a).

### 2.2. Não há aconselhamento jurídico ao cliente final

A Juris não é canal de comunicação com o(a) cliente final do escritório, nem
fornece pareceres ou orientações diretamente a leigos. Toda interação
relevante com o(a) cliente passa pelo(a) advogado(a) responsável, que avalia
e adapta a saída antes de qualquer comunicação externa.

### 2.3. Tratamento explícito de dados de cliente

Todo dado pessoal de cliente, parte processual ou terceiros tratado pela
Juris está sujeito à LGPD (Lei 13.709/2018) e segue estes princípios:

- **Finalidade restrita**: dados são usados exclusivamente para a finalidade
  definida (leitura de processo, geração de minuta, pesquisa correlata).
- **LLM local para PII**: prompts contendo dados pessoais não anonimizados
  são roteados para LLM local (Ollama). LLM em nuvem só é usado quando
  expressamente autorizado pelo(a) advogado(a) (`--cloud`) e o caso permite
  desidentificação suficiente.
- **Audit trail**: toda decisão da IA, recuperação de fonte e alteração de
  estado é registrada com hash em cadeia (`audit.jsonl`).
- **Consentimento do cliente**: o(a) advogado(a) garante que o uso da Juris
  para processar dados de seus clientes está coberto pelo contrato de
  prestação de serviços ou por consentimento expresso, conforme aplicável.
- **DPA/ROPA/RIPD**: antes de piloto com casos reais, as partes devem revisar e
  preencher o pacote operacional em `docs/compliance/` (`dpa-template-pt.md`,
  `ropa-pilot.md` e `ripd-pilot.md`), ajustando subprocessadores, retenção e
  medidas de segurança ao escritório.

### 2.4. Revisão OAB obrigatória antes de protocolar

Toda saída destinada a uso processual — minuta, manifestação, recurso,
documento assinado digitalmente — exige **revisão humana qualificada por
profissional inscrito(a) na OAB** antes de assinatura e protocolo. Este
limite é não-negociável: aplica-se mesmo quando o relatório do revisor
interno não aponta problemas críticos.

---

## 3. Modo Demonstração (DEMO)

Quando o pipeline é executado contra dados de fixture (parâmetro
`--source fixture`), a Juris opera em **MODO DEMONSTRAÇÃO**. Nesse modo:

- Os artefatos gerados ficam em diretório com prefixo `DEMO-`.
- Cada documento traz banner explícito de modo demo no topo.
- Cada documento traz rodapé de IA na base.
- **A saída não pode, em nenhuma hipótese, ser usada processualmente.**

---

## 4. Escopo do piloto

- **Duração estimada**: 2 a 4 semanas a partir da assinatura, prorrogável de
  comum acordo.
- **Casos elegíveis**: processos ativos do escritório, escolhidos pelo(a)
  advogado(a) parceiro(a), idealmente de baixo risco para o uso inicial da
  ferramenta.
- **Tipos de petição cobertos**: contestação, manifestação, recurso e
  modelos do repositório, conforme disponibilidade.
- **Funcionalidades entregues no piloto**: pipeline `juris demo` ponta-a-ponta,
  audit chain verificável (`juris audit verify`), exportação de artefatos
  por caso, termos e checklist de onboarding.
- **Funcionalidades fora do piloto**: protocolo automático sem revisão
  humana, multi-tenant SaaS, integração com WhatsApp, módulos de inteligência
  sobre adversário/juiz/tribunal.

---

## 5. Cobrança no piloto

O piloto é faturado de forma manual (Pix/NF tradicional). Modelos
disponíveis:

- **Por petição/memorando**: R$ 300 a R$ 500, conforme complexidade.
- **Mensal flat**: R$ 1.500 a R$ 3.000 para uso limitado durante o piloto.

O modelo final é definido em conjunto entre as partes antes do início.

---

## 6. Limitação e indenização

A Juris é fornecida **"as is"** durante o piloto, sem garantia de
disponibilidade contínua, ausência de erros ou aderência a tribunal
específico além dos suportados pela versão. Eventuais erros, omissões ou
imprecisões de saídas geradas pela IA não geram responsabilidade da Juris
perante terceiros, dado o limite §2.4 (revisão OAB obrigatória).

---

## 7. Encerramento

Qualquer das partes pode encerrar o piloto por escrito a qualquer momento.
No encerramento:

- Os artefatos do(a) advogado(a) (drafts, audit logs) permanecem com o
  escritório.
- Dados de cliente em posse da Juris são apagados em até 30 dias, salvo
  obrigação legal em contrário. A operação segue o runbook
  `docs/deploy/data-erasure.md` e registra certificado sem conteúdo sensível em
  `compliance-erasure.jsonl`.
- Backups e fontes aceitas para corpus devem seguir, respectivamente,
  `docs/deploy/backup-restore.md` e `data/tos_compliance_log.md`.

---

## 8. Assinaturas

| Parte | Nome | OAB / Documento | Data | Assinatura |
| --- | --- | --- | --- | --- |
| Advogado(a) parceiro(a) |  |  |  |  |
| Juris |  |  |  |  |

---

_Documento sujeito a revisão pela OAB do(a) advogado(a) parceiro(a) antes da
assinatura. Em caso de dúvida sobre §2 (limites) ou §3 (LGPD), recomenda-se
consulta ao DPO ou ao compliance do escritório antes do início do piloto._
