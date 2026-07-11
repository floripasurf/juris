# DPA - Acordo de Tratamento de Dados do Piloto Juris

> Template operacional. Revisao juridica obrigatoria antes de assinatura.

## 1. Partes

- Controlador: `<escritorio / advogado responsavel>`, OAB `<UF/numero>`.
- Operador/suboperador: `Juris`, responsavel tecnico `<nome / contato>`.
- Encarregado/DPO ou contato LGPD do controlador: `<contato>`.
- Contato de seguranca da Juris: `<contato>`.

## 2. Escopo e finalidade

O tratamento ocorre exclusivamente para operar o piloto Juris:

- leitura de processos e movimentacoes autorizadas pelo advogado via MNI/DataJud;
- analise juridica assistiva, calculo de prazos, pesquisa e geracao de rascunhos;
- registro de auditoria, feedback de piloto e melhoria dirigida do corpus do
  escritorio;
- protocolo controlado quando habilitado e explicitamente autorizado.

E vedado usar os dados para publicidade, treinamento de modelo de terceiro sem
autorizacao expressa, venda de base, enriquecimento alheio ao caso ou atendimento
direto ao cliente final.

## 3. Categorias de dados

- Dados processuais: CNJ, classe, tribunal, partes, movimentos, documentos,
  intimacoes e prazos.
- Dados de identificacao: nomes, CPF/CNPJ, OAB, e-mail, telefone, endereco quando
  presentes no processo ou documentos.
- Dados profissionais: credenciais operacionais do advogado ficam no agente local e
  nao devem ser enviadas ao servidor Juris.
- Metadados: logs tecnicos, hashes, status de jobs, feedback do piloto e trilha de
  auditoria.

## 4. Base, duracao e retencao

- Base principal: execucao do contrato/servico juridico e interesse legitimo do
  escritorio, conforme avaliacao do controlador.
- Duracao: `<periodo do piloto>`.
- Retencao apos encerramento: ate 30 dias, salvo obrigacao legal/contratual ou
  instrucao documentada do controlador.
- Delecao: executar `juris tenant erase-data <tenant>` e guardar o certificado
  `compliance-erasure.jsonl`.

## 5. Subprocessadores e transferencias

Preencher antes do uso:

| Subprocessador | Finalidade | Dados enviados | Pais/regiao | Base/contrato | Observacao |
| --- | --- | --- | --- | --- | --- |
| Ollama local | LLM local | Dados do caso no host local | Brasil/local | N/A | Preferencial para PII crua |
| Anthropic/OpenAI | LLM cloud opcional | Texto de-identificado | `<pais>` | `<DPA/link>` | Usar apenas com gate de-id aprovado |
| Claude.ai/ChatGPT via browser | Sessao do advogado | Texto de-identificado | Conforme provedor | Termos da conta do advogado | Desligar treinamento/historico no onboarding |

Novo subprocessador exige atualizacao deste DPA e do RIPD.

## 6. Medidas de seguranca

- De-identificacao de CPF/CNPJ/CNJ/OAB/RG/CEP/e-mail/telefone/datas e nomes via NER
  antes de LLM externo.
- Agente remoto split-trust: token A3, CPF, senha e PIN ficam na maquina do
  advogado.
- Auditoria encadeada com HMAC em producao (`JURIS_AUDIT_HMAC_KEY`).
- Storage por tenant, API key por escritorio e `JURIS_REQUIRE_TENANTS=1` em
  producao.
- Backups com manifesto e SHA-256, armazenados com criptografia em repouso e acesso
  owner-only.
- Rate limit por API key, Redis/proxy para multi-worker e health checks de agente.

## 7. Incidentes

A Juris deve comunicar incidente de seguranca ao controlador em ate `<prazo>` apos
conhecimento razoavel, com:

- descricao do evento;
- dados e tenants potencialmente afetados;
- medidas de contencao;
- evidencias preservadas;
- recomendacao de notificacao a titulares/ANPD quando aplicavel.

## 8. Direitos dos titulares

O controlador responde aos titulares. A Juris coopera tecnicamente com exportacao,
correcao e delecao de dados dentro do escopo do piloto, sem responder diretamente ao
cliente final salvo instrucao expressa do controlador.

## 9. Auditoria e encerramento

O controlador pode solicitar evidencias de:

- configuracao de tenants/agente;
- trilha de auditoria;
- backup/restore;
- certificado de delecao;
- lista de subprocessadores.

No encerramento, executar o runbook `docs/deploy/data-erasure.md`.
